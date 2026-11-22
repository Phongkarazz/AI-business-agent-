"""Stage-1 / Step-3 regression tests for DataMate engine hardening."""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datamate.agent import (
    AgentConfig,
    DataMateAgent,
    check_preflight_unanswerable,
    classify_expected_type,
    extract_temporal_context,
    normalize_vn_question,
    verify_sql_semantics,
)
from datamate.llm_backend import LLMBackend, MockLLMBackend
from datamate.loader import load_business_workspace
from datamate.schema_context import build_workspace_knowledge


def _build_temp_shop(root: Path) -> Path:
    biz_dir = root / "biz_test_stage1"
    biz_dir.mkdir(parents=True, exist_ok=True)
    (biz_dir / "README.md").write_text(
        "# Shop Test\n"
        "## Quy ước\n"
        "- Doanh thu bỏ qua đơn `Đã huỷ` và `Hoàn trả`.\n"
        "- Công nợ bỏ qua COD.\n",
        encoding="utf-8",
    )

    with open(biz_dir / "khach_hang.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ma_kh", "ten_kh", "gioi_tinh", "dia_chi", "nhom_kh"])
        w.writerow(["KH01", "Nguyễn Văn An", "", "", ""])
        w.writerow(["KH02", "Trần Thị Bình", "", "", ""])

    with open(biz_dir / "don_hang.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ma_don", "ngay_dat", "ma_kh", "ten_hang", "so_luong", "thanh_tien", "da_tra", "chua_tra", "trang_thai"])
        # 2025-06-24 (hôm qua): DH01 has 2 line items (revenue 150000), DH02 cancelled, DH03 valid (250000) -> 2 valid orders, 400000 total
        w.writerow(["DH01", "2025-06-24", "KH01", "Otrivin 0,1% chai 10ml", 1, 100000, 100000, 0, "Hoàn thành"])
        w.writerow(["DH01", "2025-06-24", "KH01", "Efticol 0,9%", 1, 50000, 50000, 0, "Hoàn thành"])
        w.writerow(["DH02", "2025-06-24", "KH02", "Paracetamol", 2, 80000, 0, 0, "Đã huỷ"])
        w.writerow(["DH03", "2025-06-24", "KH02", "Vitamin C", 5, 250000, 250000, 0, "Hoàn thành"])
        # 2025-06-25 (hôm nay): single huge order line DH04 (300000) < daily sum of 2025-06-24 (400000)
        w.writerow(["DH04", "2025-06-25", "KH01", "Vitamin C", 6, 300000, 300000, 0, "Hoàn thành"])
        w.writerow(["DH05", "2025-06-25", "KH02", "Vitamin C", 1, 50000, 0, 0, "Hoàn trả"])

    return biz_dir


class TestStage1NormalizationAndClassifier(unittest.TestCase):
    def test_teencode_and_telex_normalization(self) -> None:
        s1 = normalize_vn_question("hnay dthu cua shop la bnhiu vay?")
        self.assertIn("hom nay", s1)
        self.assertIn("doanh thu", s1)
        self.assertIn("bao nhieu", s1)

        s2 = normalize_vn_question("ngayf naof co ddown nhuwngx hangf ban chay nhaats?")
        self.assertIn("ngay nao", s2)
        self.assertIn("don", s2)
        self.assertIn("nhung", s2)
        self.assertIn("nhat", s2)

        w, _, bounded, _ = extract_temporal_context("hqua bán đc mấy đơn", "2025-06-25", None)
        self.assertEqual(bounded, ("2025-06-24", "2025-06-24"))
        self.assertTrue(any(s == "2025-06-24" and e == "2025-06-24" for _, s, e in w))

        _, _, bounded_dm, _ = extract_temporal_context("doanh thu ngày 15/3", "2025-06-25", None)
        self.assertEqual(bounded_dm, ("2025-03-15", "2025-03-15"))

        _, _, bounded_q, _ = extract_temporal_context("doanh thu quý 1", "2025-06-25", None)
        self.assertEqual(bounded_q, ("2025-01-01", "2025-03-31"))

    def test_classify_expected_type_edge_cases(self) -> None:
        self.assertEqual(
            classify_expected_type("hết hôm nay, Otrivin 0,1% chai 10ml còn bao nhiêu chai?").expected_type,
            "number",
        )
        self.assertEqual(
            classify_expected_type("het hom nay, Efticol 0,9% loc 10 lo x 10ml con lai may lo trong kho").expected_type,
            "number",
        )
        self.assertEqual(
            classify_expected_type("tháng 5/2026 cửa hàng có nhiêu % đơn bị huỷ").expected_type,
            "percent",
        )
        self.assertEqual(
            classify_expected_type("dthu nhóm hàng sắt thép chiếm nhiêu % toongr doanh thu").expected_type,
            "percent",
        )
        self.assertEqual(
            classify_expected_type("khach mua nhiu tien nhat thang 1/2026 la ai").expected_type,
            "string",
        )
        self.assertEqual(
            classify_expected_type("Tháng 4/2025 ai mua hàng nhiều tiền nhất vậy?").expected_type,
            "string",
        )
        self.assertEqual(
            classify_expected_type("năm 2025 hàng nào bán chạy nhất?").expected_type,
            "string",
        )
        a_unit = classify_expected_type("trong kho còn bao nhiêu hộp nguyên và bao nhiêu vỉ lẻ?")
        self.assertEqual(a_unit.expected_type, "list")
        self.assertTrue(a_unit.is_list_unit_pair)
        self.assertEqual(
            classify_expected_type("Khách Vũ Cường Quân tháng 9/2025 nợ thêm bao nhiêu, trả được bao nhiêu?").expected_type,
            "list",
        )


class TestStage1SchemaAndSemanticGuard(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.biz_dir = _build_temp_shop(self.tmp_path)
        self.cache_dir = self.tmp_path / "cache"
        self.ws = load_business_workspace(self.biz_dir, cache_dir=self.cache_dir, force_rebuild=True)
        self.know = build_workspace_knowledge(self.ws)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_empty_columns_ignored_and_order_semantics(self) -> None:
        self.assertFalse(self.know.capabilities["has_customer_gender"])
        self.assertFalse(self.know.capabilities["has_customer_address"])
        self.assertFalse(self.know.capabilities["has_customer_group"])
        self.assertTrue(self.know.capabilities["has_customers"])
        self.assertTrue(self.know.capabilities["has_debt_or_payments"])
        self.assertTrue(self.know.order_status_targets)
        tgt = self.know.order_status_targets[0]
        self.assertEqual(tgt["table"], "don_hang")
        self.assertTrue(tgt["has_repeating_orders"])
        self.assertEqual(tgt["order_id_col"], "ma_don")
        self.assertIn("Đã huỷ", tgt["valid_filter"])
        self.assertIn("Hoàn trả", tgt["valid_filter"])

        # Preflight catches missing customer gender when 100% NULL
        a_gender = classify_expected_type("khách nam nào mua nhiều nhất tháng 6/2025")
        self.assertIsNotNone(check_preflight_unanswerable("khách nam nào mua nhiều nhất", "2025-06-25", self.know, a_gender))

        # Preflight allows valid day count query
        a_ok = classify_expected_type("hqua bán được mấy đơn")
        w, ts, bounded, prior_s = extract_temporal_context("hqua bán được mấy đơn", "2025-06-25", None)
        a_ok.temporal_windows, a_ok.temporal_summary, a_ok.bounded_period, a_ok.prior_needed_start = (
            w, ts, bounded, prior_s
        )
        self.assertIsNone(check_preflight_unanswerable("hqua bán được mấy đơn", "2025-06-25", self.know, a_ok))

    def test_semantic_guard_repairs_all_major_failures(self) -> None:
        calls = []

        def mock_handler(prompt: str, system_prompt: str) -> str:
            calls.append((prompt, system_prompt))
            is_repair = "SQL lỗi:" in prompt

            # Case A: Spurious da_tra = 0 on revenue question
            if "doanh thu ngày 24/06/2025" in prompt:
                if not is_repair:
                    return json.dumps({
                        "status": "ok",
                        "sql": "SELECT SUM(thanh_tien) FROM don_hang WHERE ngay_dat = '2025-06-24' AND da_tra = 0 AND chua_tra = 0",
                    })
                return json.dumps({
                    "status": "ok",
                    "sql": "SELECT SUM(thanh_tien) FROM don_hang WHERE ngay_dat = '2025-06-24' AND trang_thai NOT IN ('Đã huỷ', 'Hoàn trả')",
                })

            # Case B: Cumulative '<=' leak on 'hqua' -> should repair to '= 2025-06-24' and DISTINCT ma_don!
            if "hqua có mấy đơn" in prompt:
                if not is_repair:
                    return json.dumps({
                        "status": "ok",
                        "sql": "SELECT COUNT(*) FROM don_hang WHERE ngay_dat <= '2025-06-24' AND trang_thai NOT IN ('Đã huỷ', 'Hoàn trả')",
                    })
                if "LỖI THỜI GIAN" in prompt:
                    return json.dumps({
                        "status": "ok",
                        "sql": "SELECT COUNT(*) FROM don_hang WHERE ngay_dat = '2025-06-24' AND trang_thai NOT IN ('Đã huỷ', 'Hoàn trả')",
                    })
                return json.dumps({
                    "status": "ok",
                    "sql": "SELECT COUNT(DISTINCT ma_don) FROM don_hang WHERE ngay_dat = '2025-06-24' AND trang_thai NOT IN ('Đã huỷ', 'Hoàn trả')",
                })

            # Case C: Peak date query missing GROUP BY
            if "ngày nào trong tháng 6/2025" in prompt:
                if not is_repair:
                    return json.dumps({
                        "status": "ok",
                        "sql": "SELECT ngay_dat FROM don_hang WHERE ngay_dat BETWEEN '2025-06-01' AND '2025-06-30' AND trang_thai NOT IN ('Đã huỷ', 'Hoàn trả') ORDER BY thanh_tien DESC LIMIT 1",
                    })
                return json.dumps({
                    "status": "ok",
                    "sql": "SELECT ngay_dat FROM don_hang WHERE ngay_dat BETWEEN '2025-06-01' AND '2025-06-30' AND trang_thai NOT IN ('Đã huỷ', 'Hoàn trả') GROUP BY ngay_dat ORDER BY SUM(thanh_tien) DESC LIMIT 1",
                })

            # Case D: Unresolved fatal semantic bug -> must abstain safely
            if "doanh thu tháng 6/2025" in prompt:
                return json.dumps({
                    "status": "ok",
                    "sql": "SELECT SUM(thanh_tien) FROM don_hang WHERE ngay_dat BETWEEN '2025-06-01' AND '2025-06-30' AND da_tra = 0",
                })

            return json.dumps({"status": "unanswerable", "reason": "unknown"})

        agent = DataMateAgent(
            backend=MockLLMBackend(mock_handler),
            config=AgentConfig(max_sql_retries=3),
        )

        # Case A -> 400000 after 2 attempts
        r_a = agent.answer_question(
            {"id": "qa", "question": "doanh thu ngày 24/06/2025 là bao nhiêu?", "as_of_date": "2025-06-25"},
            self.know,
        )
        self.assertEqual(r_a.prediction, {"id": "qa", "type": "number", "answer": 400000})
        self.assertEqual(r_a.sql_attempts, 2)

        # Case B -> caught <= first, then COUNT(*) without DISTINCT -> repaired on attempt 3 to 2 orders!
        r_b = agent.answer_question(
            {"id": "qb", "question": "hqua có mấy đơn hàng?", "as_of_date": "2025-06-25"},
            self.know,
        )
        self.assertEqual(r_b.prediction, {"id": "qb", "type": "number", "answer": 2})
        self.assertEqual(r_b.sql_attempts, 3)

        # Case C -> caught missing GROUP BY (2025-06-25 had single 300k line > 250k line, whereas 2025-06-24 sum = 400k > 300k!)
        r_c = agent.answer_question(
            {"id": "qc", "question": "ngày nào trong tháng 6/2025 có doanh thu cao nhất?", "as_of_date": "2025-06-25"},
            self.know,
        )
        self.assertEqual(r_c.prediction, {"id": "qc", "type": "date", "answer": "2025-06-24"})
        self.assertEqual(r_c.sql_attempts, 2)

        # Case D -> stubborn semantic bug -> safe abstain (0 pts instead of -1)
        r_d = agent.answer_question(
            {"id": "qd", "question": "doanh thu tháng 6/2025 là bao nhiêu?", "as_of_date": "2025-06-25"},
            self.know,
        )
        self.assertEqual(r_d.prediction, {"id": "qd", "type": "abstain"})
        self.assertEqual(r_d.sql_attempts, 3)

    def test_json_mode_and_token_budget_forwarding(self) -> None:
        seen = []

        class RecordingBackend(LLMBackend):
            def generate(
                self,
                prompt: str,
                system_prompt: str = "",
                temperature: float = 0.0,
                max_tokens: int = 1024,
                json_mode: bool = False,
            ) -> str:
                seen.append({"max_tokens": max_tokens, "json_mode": json_mode})
                return json.dumps({
                    "status": "ok",
                    "sql": "SELECT SUM(thanh_tien) FROM don_hang WHERE ngay_dat = '2025-06-25' AND trang_thai NOT IN ('Đã huỷ', 'Hoàn trả')",
                })

        agent = DataMateAgent(
            backend=RecordingBackend(),
            config=AgentConfig(use_json_mode=True, sql_max_tokens=320),
        )
        r = agent.answer_question(
            {"id": "qj", "question": "hôm nay doanh thu là bao nhiêu", "as_of_date": "2025-06-25"},
            self.know,
        )
        self.assertEqual(r.prediction, {"id": "qj", "type": "number", "answer": 300000})
        self.assertEqual(seen, [{"max_tokens": 320, "json_mode": True}])

    def test_workspace_cache_invalidates_when_source_files_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ws_dir = tmp_path / "my_business"
            cache_dir = tmp_path / "_sqlite_cache"
            ws_dir.mkdir(parents=True, exist_ok=True)
            with open(ws_dir / "old_northwind.csv", "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["category_id", "category_name"])
                w.writerow([1, "Beverages"])

            ws1 = load_business_workspace(ws_dir, cache_dir=cache_dir)
            self.assertEqual(list(ws1.tables.keys()), ["old_northwind"])
            manifest_path = cache_dir / "my_business.manifest.json"
            self.assertTrue(manifest_path.exists())

            # Replace source file inside the same workspace name without deleting cache manually
            (ws_dir / "old_northwind.csv").unlink()
            with open(ws_dir / "donhang_moi.csv", "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["ma_don", "ngay_gd", "ten_mon", "thanh_tien"])
                w.writerow(["CF001", "2026-10-01", "Cà phê sữa đá", 58000])

            ws2 = load_business_workspace(ws_dir, cache_dir=cache_dir)
            self.assertEqual(list(ws2.tables.keys()), ["donhang_moi"])

    def test_binary_blob_values_excluded_from_schema_prompt(self) -> None:
        import sqlite3
        from src.database.business_upload import build_knowledge_from_sqlite_path

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "blob_northwind.sqlite"
            con = sqlite3.connect(str(db_path))
            con.execute("CREATE TABLE Categories (CategoryID INTEGER PRIMARY KEY, CategoryName TEXT, Description TEXT, Picture BLOB)")
            jpeg_blob = b"\xff\xd8\xff\xe0" + (b"\xab\xcd\xef\x12" * 8000)
            con.execute(
                "INSERT INTO Categories VALUES (?, ?, ?, ?)",
                (1, "Beverages", "Coffee, teas, beers", jpeg_blob),
            )
            con.commit()
            con.close()

            kn = build_knowledge_from_sqlite_path(db_path)
            self.assertIsNotNone(kn)
            self.assertLess(len(kn.schema_prompt), 4000)
            self.assertNotIn("xff", kn.schema_prompt.lower())
            self.assertIn("Categories", kn.schema_prompt)
            self.assertIn("CategoryName", kn.schema_prompt)

    def test_cafe_pho_viet_semantic_guards_starter_prompts_and_workspace_resolution(self) -> None:
        from datamate.agent import classify_expected_type, verify_sql_semantics
        from datamate.sql_executor import SQLExecutionResult
        from src.analytics.heuristics import generate_dynamic_heuristic_prompts
        from src.database.business_upload import build_datamate_workspace_engine, compose_connection_schema
        from src.database.schema import auto_extract_schema, clear_schema_caches, get_table_names
        from src.ui.onboarding import _resolve_workspace_dir_candidate

        resolved = _resolve_workspace_dir_candidate("cafe_pho_viet/")
        self.assertIsNotNone(resolved)
        self.assertTrue((resolved / "bao_cao_ban_hang.xlsx").exists())

        eng, know = build_datamate_workspace_engine(resolved)
        try:
            clear_schema_caches()
            setattr(eng, "_veraxus_cache_epoch", 1)
            tables = get_table_names(eng)
            self.assertEqual(sorted(tables), ["danhmucmon", "donhang"])
            full_schema = compose_connection_schema(auto_extract_schema(eng, force_refresh=True), "", know)

            prompts = generate_dynamic_heuristic_prompts(tables, full_schema, lang="vi")
            all_prompts = " | ".join(c["prompt"] for cards in prompts.values() for c in cards)
            self.assertIn("thành tiền", all_prompts.lower())
            self.assertIn("nhóm món", all_prompts.lower())

            dummy_res = SQLExecutionResult(ok=True, sql="", columns=["c"], rows=[(1,)], row_count=1)
            # Double multiplication (so_luong * thanh_tien) rejected
            ok, msg, _ = verify_sql_semantics(
                "SELECT SUM(so_luong * thanh_tien) FROM donhang WHERE trang_thai = 'Hoàn thành'",
                dummy_res,
                "Báo cáo số lượng và thành tiền",
                know,
                classify_expected_type("Báo cáo số lượng và thành tiền"),
            )
            self.assertFalse(ok)
            self.assertIn("nhân", msg.lower())

            # Missing explicit requested table ('bảng danhmucmon') rejected
            ok_tbl, _, _ = verify_sql_semantics(
                "SELECT SUM(thanh_tien) FROM donhang WHERE trang_thai = 'Hoàn thành'",
                dummy_res,
                "Thống kê tổng quan các chỉ số chính của bảng danhmucmon",
                know,
                classify_expected_type("Thống kê tổng quan các chỉ số chính của bảng danhmucmon"),
            )
            self.assertFalse(ok_tbl)

            # Missing requested 'nhom_mon' group dimension rejected
            ok_dim, _, _ = verify_sql_semantics(
                "SELECT ten_mon, SUM(thanh_tien) FROM donhang WHERE trang_thai = 'Hoàn thành' GROUP BY ten_mon",
                dummy_res,
                "Nhóm món nào mang lại doanh thu cao nhất?",
                know,
                classify_expected_type("Nhóm món nào mang lại doanh thu cao nhất?"),
            )
            self.assertFalse(ok_dim)

            # COUNT(*) substituting for SUM(so_luong) rejected
            ok_qty, _, _ = verify_sql_semantics(
                "SELECT ngay_ban, COUNT(*) FROM donhang WHERE trang_thai = 'Hoàn thành' GROUP BY ngay_ban",
                dummy_res,
                "Xu hướng tổng số lượng theo từng ngày thay đổi như thế nào?",
                know,
                classify_expected_type("Xu hướng tổng số lượng theo từng ngày thay đổi như thế nào?"),
            )
            self.assertFalse(ok_qty)

            # Broken grouped denominator share without OVER () or scalar subquery rejected
            ok_pct, _, _ = verify_sql_semantics(
                "SELECT dm.nhom_mon, COUNT(*) * 100.0 / SUM(dh.thanh_tien) FROM donhang dh JOIN danhmucmon dm ON dh.ten_mon = dm.ten_mon WHERE dh.trang_thai = 'Hoàn thành' GROUP BY dm.nhom_mon",
                dummy_res,
                "Tỷ lệ đóng góp thành tiền của từng nhóm món vào tổng số",
                know,
                classify_expected_type("Tỷ lệ đóng góp thành tiền của từng nhóm món vào tổng số"),
            )
            self.assertFalse(ok_pct)

            # Mismatched numerator/denominator metric in window/subquery share rejected
            ok_pct_mismatch, msg_mismatch, _ = verify_sql_semantics(
                "SELECT dm.nhom_mon, ROUND(SUM(dh.thanh_tien) / SUM(SUM(dh.so_luong)) OVER () * 100.0, 2) AS percent FROM donhang dh JOIN danhmucmon dm ON dh.ten_mon = dm.ten_mon WHERE dh.trang_thai = 'Hoàn thành' GROUP BY dm.nhom_mon",
                dummy_res,
                "Tỷ lệ đóng góp thành tiền của từng nhóm món vào tổng số",
                know,
                classify_expected_type("Tỷ lệ đóng góp thành tiền của từng nhóm món vào tổng số"),
            )
            self.assertFalse(ok_pct_mismatch)
            self.assertIn("so_luong", msg_mismatch)

            # Valid window share & subquery share accepted
            ok_pct_win, _, _ = verify_sql_semantics(
                "SELECT dm.nhom_mon, SUM(dh.thanh_tien) * 100.0 / SUM(SUM(dh.thanh_tien)) OVER () FROM donhang dh JOIN danhmucmon dm ON dh.ten_mon = dm.ten_mon WHERE dh.trang_thai = 'Hoàn thành' GROUP BY dm.nhom_mon",
                dummy_res,
                "Tỷ lệ đóng góp thành tiền của từng nhóm món vào tổng số",
                know,
                classify_expected_type("Tỷ lệ đóng góp thành tiền của từng nhóm món vào tổng số"),
            )
            self.assertTrue(ok_pct_win)

            # Missing GROUP BY on peak-date aggregate (e.g. MAX(ngay_ban), SUM(thanh_tien)) rejected
            ok_nogrp_max, msg_nogrp, _ = verify_sql_semantics(
                "SELECT MAX(ngay_ban), SUM(thanh_tien) FROM donhang WHERE trang_thai NOT IN ('Đã hủy', 'Trả lại') AND ngay_ban BETWEEN '2026-10-01' AND '2026-10-06'",
                dummy_res,
                "Ngày nào có Doanh Thu cao nhất trong tháng 10/2026?",
                know,
                classify_expected_type("Ngày nào có Doanh Thu cao nhất trong tháng 10/2026?"),
            )
            self.assertFalse(ok_nogrp_max)
            self.assertIn("GROUP BY", msg_nogrp)

            # Mixed unaggregated dimension column + SUM without GROUP BY rejected
            ok_nogrp_mix, _, _ = verify_sql_semantics(
                "SELECT ngay_ban, SUM(thanh_tien) FROM donhang WHERE trang_thai = 'Hoàn thành'",
                dummy_res,
                "Ngày nào có Doanh Thu cao nhất trong tháng 10/2026?",
                know,
                classify_expected_type("Ngày nào có Doanh Thu cao nhất trong tháng 10/2026?"),
            )
            self.assertFalse(ok_nogrp_mix)

            # Valid grouped peak-date query accepted
            ok_grp_peak, _, _ = verify_sql_semantics(
                "SELECT ngay_ban, SUM(thanh_tien) AS doanh_thu FROM donhang WHERE trang_thai NOT IN ('Đã hủy', 'Trả lại') GROUP BY ngay_ban ORDER BY doanh_thu DESC LIMIT 1",
                dummy_res,
                "Ngày nào có Doanh Thu cao nhất trong tháng 10/2026?",
                know,
                classify_expected_type("Ngày nào có Doanh Thu cao nhất trong tháng 10/2026?"),
            )
            self.assertTrue(ok_grp_peak)

            # Rulebook prompt injects explicit JOIN danhmucmon & GROUP BY hint on Attempt 1
            from datamate.agent import _select_rulebook_prompt
            rb_cat = _select_rulebook_prompt(
                "Nhóm món nào mang lại doanh thu cao nhất?",
                know.data_max_date or "2026-10-06",
                know,
                classify_expected_type("Nhóm món nào mang lại doanh thu cao nhất?"),
            )
            self.assertIn("danhmucmon.nhom_mon", rb_cat)
            self.assertIn("JOIN danhmucmon", rb_cat)
        finally:
            eng.dispose()


if __name__ == "__main__":
    unittest.main()
