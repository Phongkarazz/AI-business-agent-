"""Unit & end-to-end integration tests for DataMate Step 2 (agent, executor, grounding, splits)."""

import pathlib
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from datamate.agent import (
    AgentConfig,
    DataMateAgent,
    classify_expected_type,
    extract_temporal_context,
)
from datamate.evaluator_pa import evaluate_records
from datamate.llm_backend import MockLLMBackend
from datamate.loader import load_business_workspace
from datamate.schema_context import build_workspace_knowledge, ground_query_entities
from datamate.splits import VAL_BUSINESS_IDS, load_split_dataset
from datamate.sql_executor import adapt_sql_to_sqlite, execute_sql_safe, round_half_up


class TestSqlExecutor(unittest.TestCase):
    def test_rounding_and_readonly_safety(self):
        self.assertEqual(round_half_up(12.5, 0), 13)
        self.assertEqual(round_half_up(2.5, 0), 3)
        self.assertEqual(round_half_up(12.345, 2), 12.35)

        def fake_conn():
            con = sqlite3.connect(":memory:")
            con.execute("CREATE TABLE items (ten TEXT, gia INTEGER)")
            con.execute("INSERT INTO items VALUES ('Nước ép dưa hấu (L)', 45000)")
            return con

        res = execute_sql_safe(
            fake_conn,
            "```sql\nSELECT ten, ROUND_HALF_UP(gia / 2.0, 0) FROM item WHERE NORM_VN(ten) LIKE '%nuoc ep dua hau%';\n```",
            valid_tables=["items"],
        )
        self.assertTrue(res.ok, res.error)
        self.assertEqual(res.rows, [("Nước ép dưa hấu (L)", 22500)])

        bad = execute_sql_safe(fake_conn, "DROP TABLE items;", valid_tables=["items"])
        self.assertFalse(bad.ok)
        self.assertIn("SELECT or WITH", bad.error)

    def test_mysql_to_sqlite_adaptation(self):
        sql = "SELECT YEAR(ngay), MONTH(ngay) FROM don WHERE ten ILIKE '%ca phe%' AND IFNULL(NVL(sl, 0), 0) > 0"
        adapted = adapt_sql_to_sqlite(sql)
        self.assertIn("strftime('%Y', ngay)", adapted)
        self.assertIn("strftime('%m', ngay)", adapted)
        self.assertIn("COALESCE(sl, 0)", adapted)
        self.assertNotIn("ILIKE", adapted)


class TestQuestionClassificationAndTemporal(unittest.TestCase):
    def test_classify_all_types(self):
        self.assertEqual(classify_expected_type("Doanh thu tháng 3/2026 là bao nhiêu?").expected_type, "number")
        self.assertEqual(classify_expected_type("Tỉ lệ đơn huỷ trong tháng là bao nhiêu %?").expected_type, "percent")
        d_day = classify_expected_type("Tháng 6/2025 ngày nào bán nhiều tiền nhất?")
        self.assertEqual((d_day.expected_type, d_day.date_granularity), ("date", "day"))
        d_mon = classify_expected_type("Xét 3 tháng 1/2026, 2/2026 và 3/2026, tháng nào lớn nhất?")
        self.assertEqual((d_mon.expected_type, d_mon.date_granularity), ("date", "month"))
        self.assertEqual(classify_expected_type("Từ tháng 9/2025 đến 11/2025, doanh thu có tăng liên tục không?").expected_type, "boolean")
        self.assertEqual(classify_expected_type("Mặt hàng nào bán chạy nhất tháng 1/2026?").expected_type, "string")
        self.assertEqual(classify_expected_type("Top 3 mặt hàng bán chạy nhất tuần này là gì?").expected_type, "list")
        self.assertEqual(classify_expected_type("Hôm nay Bánh croissant còn mấy hộp chẵn, mấy cái lẻ?").expected_type, "list")
        self.assertEqual(classify_expected_type("Cho bảng 3 khách còn nợ nhiều nhất kèm số tiền còn nợ").expected_type, "table")

    def test_temporal_resolution_windows(self):
        _, summary, bounded, prior_end = extract_temporal_context(
            "So với tháng liền trước, doanh thu tháng 2/2025 tăng bao nhiêu %?",
            as_of_date="2026-09-14",
            cal=None,
        )
        self.assertEqual(bounded, ("2025-02-01", "2025-02-28"))
        self.assertEqual(prior_end, "2025-01-31")
        self.assertIn("2025-01-01", summary)


class TestAgentEndToEndMocked(unittest.TestCase):
    def _build_fixture_shop(self, root: pathlib.Path) -> pathlib.Path:
        bdir = root / "biz_fixture"
        bdir.mkdir()
        (bdir / "README.md").write_text(
            "# Fixture Shop\nĐơn hoàn thành có status='Hoàn thành'.\n",
            encoding="utf-8",
        )
        (bdir / "sobanhang.csv").write_text(
            "ma_don,ngay_ban,khach_hang,ten_hang,so_luong,thanh_tien,status\n"
            "D01,01/02/2025,Chị Lan,Cà phê sữa (M),2,60.000đ,Hoàn thành\n"
            "D02,15/02/2025,Anh Tú,Nước ép dưa hấu (L),1,45.000đ,Hoàn thành\n"
            "D03,15/02/2025,Anh Tú,Cà phê sữa (M),1,30.000đ,Đã huỷ\n"
            "D04,10/03/2025,Chị Lan,Nước ép dưa hấu (L),3,135.000đ,Hoàn thành\n"
            "D05,20/03/2025,Anh Tú,Bạc xỉu (M),2,70.000đ,Hoàn thành\n",
            encoding="utf-8",
        )
        return bdir

    def test_end_to_end_sql_repair_unanswerable_abstain_and_pa(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            bdir = self._build_fixture_shop(root)
            ws = load_business_workspace(bdir, cache_dir=root / "cache", force_rebuild=True)
            know = build_workspace_knowledge(ws)

            self.assertEqual(know.data_min_date, "2025-02-01")
            self.assertEqual(know.data_max_date, "2025-03-20")
            self.assertFalse(know.capabilities["has_cost_price"])
            self.assertTrue(know.capabilities["has_customers"])

            grounded = ground_query_entities("thang 3/2025 nuoc ep dua hau (l) ban bao nhieu", know)
            self.assertTrue(any(v == "Nước ép dưa hấu (L)" for _, _, v in grounded))

            repair_seen = {"flag": False}

            def mock_llm(prompt: str, system_prompt: str) -> str:
                if "ép lỗi để abstain" in prompt.lower():
                    return '{"status": "ok", "sql": "SELECT broken_col FROM nowhere"}'
                if "SQL lỗi" in prompt and "doanh thu tháng 3/2025" in prompt.lower():
                    repair_seen["flag"] = True
                    return '{"status": "ok", "sql": "SELECT SUM(thanh_tien) FROM sobanhang WHERE status = \'Hoàn thành\' AND ngay_ban LIKE \'2025-03-%\'"}'
                if "doanh thu tháng 3/2025" in prompt.lower() and not repair_seen["flag"]:
                    # Intentionally trigger 1 SQL self-repair via bad column name
                    return '{"status": "ok", "sql": "SELECT SUM(nonexistent_col) FROM sobanhang"}'
                if "ngày nào bán được nhiều" in prompt.lower():
                    return '{"status": "ok", "sql": "SELECT ngay_ban FROM sobanhang WHERE status = \'Hoàn thành\' GROUP BY ngay_ban ORDER BY SUM(thanh_tien) DESC LIMIT 1"}'
                if "tỉ lệ đơn huỷ" in prompt.lower():
                    return '{"status": "ok", "sql": "SELECT ROUND(SUM(CASE WHEN status = \'Đã huỷ\' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) FROM sobanhang WHERE ngay_ban LIKE \'2025-02-%\'"}'
                if "tăng liên tục" in prompt.lower():
                    return '{"status": "ok", "sql": "SELECT CASE WHEN m3 > m2 THEN 1 ELSE 0 END FROM (SELECT SUM(CASE WHEN ngay_ban LIKE \'2025-02-%\' THEN thanh_tien ELSE 0 END) AS m2, SUM(CASE WHEN ngay_ban LIKE \'2025-03-%\' THEN thanh_tien ELSE 0 END) AS m3 FROM sobanhang WHERE status = \'Hoàn thành\')"}'
                if "mặt hàng nào bán chạy nhất" in prompt.lower():
                    return '{"status": "ok", "sql": "SELECT ten_hang FROM sobanhang WHERE status = \'Hoàn thành\' GROUP BY ten_hang ORDER BY SUM(so_luong) DESC, ten_hang ASC LIMIT 1"}'
                if "top 2 mặt hàng" in prompt.lower():
                    return '{"status": "ok", "sql": "SELECT ten_hang FROM sobanhang WHERE status = \'Hoàn thành\' GROUP BY ten_hang ORDER BY SUM(so_luong) DESC, ten_hang ASC LIMIT 2"}'
                if "bảng 2 khách" in prompt.lower():
                    return '{"status": "ok", "sql": "SELECT khach_hang, SUM(thanh_tien) AS dt FROM sobanhang WHERE status = \'Hoàn thành\' GROUP BY khach_hang ORDER BY dt DESC LIMIT 2"}'
                return '{"status": "unanswerable", "reason": "Không đủ dữ liệu"}'

            agent = DataMateAgent(
                backend=MockLLMBackend(mock_llm),
                config=AgentConfig(max_sql_retries=3, enable_llm_formatter_fallback=False),
            )

            questions = [
                {"id": "q1", "business_id": "biz_fixture", "as_of_date": "2025-03-31", "question": "Doanh thu tháng 3/2025 là bao nhiêu?"},
                {"id": "q2", "business_id": "biz_fixture", "as_of_date": "2025-03-31", "question": "Tỉ lệ đơn huỷ tháng 2/2025 là bao nhiêu %?"},
                {"id": "q3", "business_id": "biz_fixture", "as_of_date": "2025-03-31", "question": "Trong tháng 3/2025 ngày nào bán được nhiều tiền nhất?"},
                {"id": "q4", "business_id": "biz_fixture", "as_of_date": "2025-03-31", "question": "Từ tháng 2/2025 đến 3/2025 doanh thu có tăng liên tục không?"},
                {"id": "q5", "business_id": "biz_fixture", "as_of_date": "2025-03-31", "question": "Mặt hàng nào bán chạy nhất?"},
                {"id": "q6", "business_id": "biz_fixture", "as_of_date": "2025-03-31", "question": "Top 2 mặt hàng bán chạy nhất là gì?"},
                {"id": "q7", "business_id": "biz_fixture", "as_of_date": "2025-03-31", "question": "Cho bảng 2 khách mua nhiều nhất kèm doanh thu"},
                # Preflight unanswerable (before data_min_date & missing gia_von)
                {"id": "q8", "business_id": "biz_fixture", "as_of_date": "2025-03-31", "question": "Doanh thu tháng 1/2025 là bao nhiêu?"},
                {"id": "q9", "business_id": "biz_fixture", "as_of_date": "2025-03-31", "question": "Lãi gộp tháng 3/2025 là bao nhiêu?"},
                # Broken SQL -> should abstain cleanly (0 points instead of -1)
                {"id": "q10", "business_id": "biz_fixture", "as_of_date": "2025-03-31", "question": "Câu ép lỗi để abstain là bao nhiêu?"},
            ]
            refs = [
                {"id": "q1", "type": "number", "answer": 205000, "alias": []},
                {"id": "q2", "type": "percent", "answer": 33.33, "alias": []},
                {"id": "q3", "type": "date", "answer": "2025-03-10", "alias": []},
                {"id": "q4", "type": "boolean", "answer": True, "alias": []},
                {"id": "q5", "type": "string", "answer": "Nước ép dưa hấu (L)", "alias": []},
                {"id": "q6", "type": "list", "answer": ["Nước ép dưa hấu (L)", "Bạc xỉu (M)"], "alias": []},
                {"id": "q7", "type": "table", "answer": {"columns": ["khach_hang", "dt"], "rows": [["Chị Lan", 195000], ["Anh Tú", 115000]]}, "alias": []},
                {"id": "q8", "type": "unanswerable", "answer": None, "alias": []},
                {"id": "q9", "type": "unanswerable", "answer": None, "alias": []},
                {"id": "q10", "type": "number", "answer": 123, "alias": []},
            ]

            results = [agent.answer_question(q, know) for q in questions]
            self.assertEqual(results[0].sql_attempts, 2)  # q1 repaired on attempt 2!
            self.assertEqual(results[9].prediction["type"], "abstain")

            preds = [r.prediction for r in results]
            rep = evaluate_records(refs, preds)
            # 9 correct (+1 each), 1 abstain (0), 0 wrong -> PA = 0.9
            self.assertEqual((rep.correct, rep.wrong, rep.abstain), (9, 0, 1))
            self.assertAlmostEqual(rep.pa, 0.9)

    def test_train_val_split_integrity(self):
        train_dir = pathlib.Path("/Users/phongha/Downloads/train")
        if not train_dir.exists():
            self.skipTest("Local train dataset directory not present")
        tr_qs, ans = load_split_dataset(train_dir, split="train")
        va_qs, _ = load_split_dataset(train_dir, split="val")
        self.assertEqual(len(tr_qs), 2369)
        self.assertEqual(len(va_qs), 631)
        self.assertEqual(len(ans), 3000)
        self.assertTrue({q["business_id"] for q in va_qs} == set(VAL_BUSINESS_IDS))
        self.assertTrue({q["business_id"] for q in tr_qs}.isdisjoint(set(VAL_BUSINESS_IDS)))


if __name__ == "__main__":
    unittest.main()
