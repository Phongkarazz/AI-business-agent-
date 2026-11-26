"""Regression tests for Veraxus UI regex safety, chart X-axis labeling, source_sheet date rewrites, and trend/peak SQL generation."""

from __future__ import annotations

import pathlib
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace

import pandas as pd

from datamate.agent import (
    _allows_negative_net_result,
    build_entity_and_metric_listing_sql_spec,
    build_time_series_or_period_ranking_sql_spec,
    classify_expected_type,
    rewrite_misused_source_sheet_date_filter,
    rewrite_signed_cashflow_sql,
    verify_sql_semantics,
)
from datamate.loader import load_business_workspace
from datamate.schema_context import build_workspace_knowledge
from datamate.sql_executor import SQLExecutionResult
from src.analytics.anomaly import analyze_data_anomalies
from src.analytics.heuristics import (
    generate_categorized_starter_prompts,
    generate_hypothesis_tree,
    humanize_name_vi,
    pick_label_column,
)
from src.llm.datamate_bridge import build_datamate_suggested_questions, run_datamate_enhanced_turn


def _build_synthetic_salon_workspace(td: str):
    ws_dir = pathlib.Path(td)
    db_path = ws_dir / "data.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE banggia (
            dich_vu TEXT, nhom TEXT, gia INTEGER,
            hoa_hong_tho_chinh INTEGER, hoa_hong_tho_chinh_dong INTEGER, hoa_hong_tho_phu_dong INTEGER
        );
        INSERT INTO banggia VALUES
            ('Cắt tạo kiểu', 'Tóc', 150000, 10, 0, 0),
            ('Uốn phục hồi', 'Hóa chất', 850000, 10, 0, 0),
            ('Gội dưỡng sinh', 'Chăm sóc', 120000, 10, 0, 0);

        CREATE TABLE danhbakhach (ho_ten TEXT, hay_goi TEXT, dien_thoai TEXT);
        INSERT INTO danhbakhach VALUES
            ('Khách Thử A', 'Thử A', '0900000001'),
            ('Khách Thử B', 'Thử B', '0900000002');

        CREATE TABLE danhsachtho (ho_ten TEXT, ten_goi TEXT);
        INSERT INTO danhsachtho VALUES
            ('Nguyễn Văn Thử', 'Thử'),
            ('Phạm Thị Mẫu', 'Mẫu');

        CREATE TABLE lichhen (ngay TEXT, cot_2 TEXT, khach TEXT, lam TEXT, hen_tho TEXT, ghi_chu TEXT);
        INSERT INTO lichhen VALUES
            ('2026-08-10', '09:00', 'Thử A', 'Cắt tạo kiểu', 'Thử', '');

        CREATE TABLE sothu (
            ngay TEXT, gio TEXT, khach TEXT, dich_vu TEXT, tho TEXT, tho_phu TEXT,
            tien REAL, tip REAL, the TEXT, source_sheet TEXT
        );
        INSERT INTO sothu VALUES
            ('2025-10-15', '10:00', 'Thử A', 'Cắt tạo kiểu', 'Thử', '', 150000, 0, '', 'T10.2025'),
            ('2026-07-20', '10:00', 'Thử A', 'Cắt tạo kiểu', 'Thử', '', 150000, 0, '', '2026'),
            ('2026-08-05', '10:00', 'Thử A', 'Cắt tạo kiểu', 'Thử', '', 150000, 20000, '', '2026'),
            ('2026-08-12', '14:00', 'Thử B', 'Uốn phục hồi', 'Mẫu', 'Thử', 850000, 50000, '', '2026'),
            ('2026-08-12', '16:00', 'Thử A', 'Gội dưỡng sinh', 'Mẫu', '', 120000, 0, 'THE01', '2026'),
            ('2026-08-25', '11:00', 'Thử B', 'Cắt tạo kiểu', 'Thử', '', 150000, 0, '', '2026');

        CREATE TABLE thelieutrinh (
            ma_the TEXT, ngay_mua TEXT, khach TEXT, goi TEXT,
            so_buoi INTEGER, tang_them INTEGER, tien_the INTEGER, han_dung TEXT
        );
        INSERT INTO thelieutrinh VALUES
            ('THE01', '2026-07-01', 'Thử A', 'Gội dưỡng sinh', 10, 2, 1200000, '2027-09-01');
        """
    )
    conn.commit()
    conn.close()
    ws = load_business_workspace(ws_dir)
    return build_workspace_knowledge(ws)


class _DummyCompletions:
    def __init__(self, responses):
        self._responses = list(responses)
        self._idx = 0

    def create(self, **kwargs):
        txt = self._responses[min(self._idx, len(self._responses) - 1)]
        self._idx += 1
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=txt))]
        )


class _FakeLLMClient:
    def __init__(self, responses):
        self.chat = SimpleNamespace(completions=_DummyCompletions(responses))


class TestVeraxusUIAndQueryFixes(unittest.TestCase):
    def test_hypothesis_tree_and_anomaly_no_regex_pattern_error(self):
        df = pd.DataFrame(
            {
                "Phieu": ["PH001", "PH001"],
                "Ma Do": ["ITEM_01", "ITEM_02"],
                "Ngày Đặt": ["2026-02-24", "2026-02-24"],
                "Ngày Lay": [None, None],
                "Ngày Hen Tra": ["2026-04-06", "2026-04-06"],
                "Tiền Thue": [7900000, 2750000],
            }
        )
        anom = analyze_data_anomalies(df)
        self.assertIsInstance(anom, dict)
        tree = generate_hypothesis_tree(df, user_query="Cho xem chi tiết các mã đồ", is_en=False)
        self.assertIsInstance(tree, dict)

        df_qtr = pd.DataFrame(
            {
                "Kỳ": ["2026-Q1", "q2"],
                "Nhóm": ["Nhóm A", "Nhóm B"],
                "Doanh thu": [1200000, 450000],
            }
        )
        tree_qtr = generate_hypothesis_tree(df_qtr, user_query="Doanh thu theo kỳ", is_en=True)
        self.assertIn("2026-Q1", str(tree_qtr))

    def test_pick_label_column_skips_constant_receipt_column_when_item_varies(self):
        df = pd.DataFrame(
            {
                "Phieu": ["PH001", "PH001"],
                "Ma Do": ["ITEM_01", "ITEM_02"],
                "Ngày Đặt": ["2026-02-24", "2026-02-24"],
                "Tiền Thue": [7900000, 2750000],
            }
        )
        lbl_col, lbl_series, _ = pick_label_column(df)
        self.assertEqual(lbl_col, "Ma Do")
        self.assertEqual(list(lbl_series), ["ITEM_01", "ITEM_02"])

    def test_schema_semantics_and_source_sheet_rewrite_on_salon_workspace(self):
        with tempfile.TemporaryDirectory() as td:
            kw = _build_synthetic_salon_workspace(td)
            self.assertIn("sothu", kw.semantic_summary)
            self.assertIn("TUYỆT ĐỐI KHÔNG lọc `source_sheet BETWEEN", kw.semantic_summary)
            self.assertTrue(any(t.get("table") == "sothu" and t.get("date_col") == "ngay" for t in kw.order_status_targets))

            bad_sql = (
                "SELECT strftime('%Y-%m-%d', f.ngay) AS period, ROUND_HALF_UP(SUM(f.tien), 0) AS doanh_thu "
                "FROM sothu f WHERE f.source_sheet BETWEEN '2026-08-01' AND '2026-08-31' GROUP BY period ORDER BY period"
            )
            fixed_sql = rewrite_misused_source_sheet_date_filter(bad_sql, kw)
            self.assertIn("substr(f.ngay, 1, 10) BETWEEN '2026-08-01' AND '2026-08-31'", fixed_sql)
            self.assertNotIn("source_sheet BETWEEN", fixed_sql)

            followups = build_datamate_suggested_questions(kw, lang="vi")
            self.assertTrue(any("08/2026" in q for q in followups), f"Expected sales month 08/2026 in {followups}")

    def test_trend_classification_semantic_guard_and_bridge_execution(self):
        analysis_trend = classify_expected_type("Xu hướng Doanh Thu dịch vụ theo từng ngày trong tháng 08/2026?")
        self.assertEqual(analysis_trend.expected_type, "table")

        with tempfile.TemporaryDirectory() as td:
            kw = _build_synthetic_salon_workspace(td)
            # Semantic guard must catch missing aggregate even without ORDER BY on trend GROUP BY
            no_agg_sql = "SELECT substr(f.ngay, 1, 10) AS ngay FROM sothu f GROUP BY ngay"
            ok, msg, fatal = verify_sql_semantics(
                no_agg_sql,
                SQLExecutionResult(ok=True, sql=no_agg_sql, columns=["ngay"], rows=[("2026-08-05",)]),
                "Xu hướng Doanh Thu dịch vụ theo từng ngày trong tháng 08/2026?",
                kw,
                analysis_trend,
            )
            self.assertFalse(ok)
            self.assertTrue(fatal)
            self.assertIn("LỖI THIẾU HÀM TỔNG HỢP", msg)

            # Even if LLM emits `WHERE f.source_sheet BETWEEN ...`, bridge rewrites it cleanly & succeeds!
            fake_trend_client = _FakeLLMClient(
                [
                    '{"status":"ok","sql":"SELECT strftime(\'%Y-%m-%d\', f.ngay) AS ngay, ROUND_HALF_UP(SUM(f.tien), 0) AS doanh_thu FROM sothu f WHERE f.source_sheet BETWEEN \'2026-08-01\' AND \'2026-08-31\' GROUP BY ngay ORDER BY ngay ASC;"}'
                ]
            )
            out_trend = run_datamate_enhanced_turn(
                "Xu hướng Doanh Thu dịch vụ theo từng ngày trong tháng 08/2026?",
                fake_trend_client,
                "Ollama (Local AI Offline)",
                "veraxus-coder:3b",
                kw,
                lang="vi",
            )
            self.assertIsNotNone(out_trend.get("df"))
            self.assertGreaterEqual(len(out_trend["df"]), 3)
            self.assertIn("substr(f.ngay, 1, 10) BETWEEN '2026-08-01' AND '2026-08-31'", out_trend.get("sql", ""))

            # Even if LLM keeps returning empty/invalid SQL, deterministic peak-period fallback recovers 2026-08-12!
            fake_peak_client = _FakeLLMClient(
                [
                    '{"status":"ok","sql":"SELECT substr(f.ngay, 1, 10) AS ngay FROM sothu f GROUP BY ngay"}',
                    '{"status":"ok","sql":"SELECT substr(f.ngay, 1, 10) AS ngay FROM sothu f GROUP BY ngay"}',
                    '{"status":"ok","sql":"SELECT substr(f.ngay, 1, 10) AS ngay FROM sothu f GROUP BY ngay"}',
                ]
            )
            out_peak = run_datamate_enhanced_turn(
                "Ngày nào có Doanh Thu dịch vụ cao nhất trong tháng 08/2026?",
                fake_peak_client,
                "Ollama (Local AI Offline)",
                "veraxus-coder:3b",
                kw,
                lang="vi",
            )
            self.assertIsNotNone(out_peak.get("df"))
            self.assertEqual(len(out_peak["df"]), 1)
            self.assertEqual(str(out_peak["df"].iloc[0, 0]), "2026-08-12")
            self.assertEqual(float(out_peak["df"].iloc[0, 1]), 970000.0)
            spec_peak = build_time_series_or_period_ranking_sql_spec(
                "Ngày nào có Doanh Thu dịch vụ cao nhất trong tháng 08/2026?",
                kw,
                classify_expected_type("Ngày nào có Doanh Thu dịch vụ cao nhất trong tháng 08/2026?"),
            )
            self.assertIsNotNone(spec_peak)
            self.assertEqual(spec_peak["date_col"], "ngay")

    def test_signed_bank_statement_cashflow_positive_ranking_and_diacritics(self):
        self.assertEqual(humanize_name_vi("so_tien"), "Số Tiền")
        self.assertEqual(humanize_name_vi("tong_so_tien"), "Tổng Số Tiền")

        schema_txt = "\n".join(
            [
                "- Bảng `nganhanga_saoke`: ngay_giao_dich, mo_ta, danh_muc, so_tien, nguoi_thuc_hien, ghi_chu",
                "- Bảng `so_chi`: ngay, khoan_chi, nhom, so_tien, nguoi_chi",
            ]
        )
        cats = generate_categorized_starter_prompts(["nganhanga_saoke", "so_chi"], schema_txt, lang="vi")
        all_prompts = [c["prompt"] for cards in cats.values() for c in cards]
        self.assertFalse(any("nganhanga saoke" in p.lower() for p in all_prompts), f"Raw table prompt leaked: {all_prompts}")
        self.assertFalse(any("so tiền" in p.lower() for p in all_prompts), f"Unaccented 'so tiền' in: {all_prompts}")

        with tempfile.TemporaryDirectory() as td:
            ws_dir = pathlib.Path(td)
            db_path = ws_dir / "data.sqlite"
            conn = sqlite3.connect(str(db_path))
            conn.executescript(
                """
                CREATE TABLE nganhanga_saoke (
                    ngay_giao_dich TEXT, mo_ta TEXT, danh_muc TEXT, so_tien INTEGER, nguoi_thuc_hien TEXT, ghi_chu TEXT
                );
                INSERT INTO nganhanga_saoke VALUES
                    ('2026-08-01', 'Siêu thị Alpha', 'Đi chợ, siêu thị', -83052000, 'Thành viên A', ''),
                    ('2026-08-02', 'Chuyển khoản vãng lai', NULL, -81300000, 'Thành viên A', ''),
                    ('2026-08-03', 'Lãi không kỳ hạn', NULL, 318323, 'Ngân hàng', ''),
                    ('2026-08-04', 'Điện nước', 'Nhà cửa', -26352000, 'Thành viên B', ''),
                    ('2026-08-05', 'Nhà hàng', 'Ăn uống', -21562000, 'Thành viên A', ''),
                    ('2026-08-06', 'Rạp chiếu phim', 'Giải trí', -13759000, 'Thành viên B', ''),
                    ('2026-08-07', 'Khám sức khoẻ', 'Y tế, sức khoẻ', -3918000, 'Thành viên A', '');
                """
            )
            conn.commit()
            conn.close()

            kw = build_workspace_knowledge(load_business_workspace(ws_dir))
            self.assertIn("nganhanga_saoke.so_tien", kw.signed_amount_columns)
            self.assertGreater(kw.signed_amount_columns["nganhanga_saoke.so_tien"]["neg_count"], 4)
            self.assertIn("SUM(ABS(so_tien))", kw.semantic_summary)

            q_tbl = "Top 10 nganhanga saoke có tổng so tien cao nhất"
            spec = build_entity_and_metric_listing_sql_spec(
                q_tbl, kw, classify_expected_type(q_tbl), entity_matches=()
            )
            self.assertIsNotNone(spec)
            self.assertIn("ABS(", spec["suggested_sql"])
            self.assertIn("so_tien < 0", spec["suggested_sql"])

            # Simulate LLM returning inverted negative SQL without ABS() or IS NOT NULL
            fake_saoke_client = _FakeLLMClient(
                [
                    '{"status":"ok","sql":"SELECT danh_muc AS nganhanga_saoke, ROUND_HALF_UP(SUM(so_tien), 0) AS doanh_thu FROM nganhanga_saoke GROUP BY danh_muc ORDER BY doanh_thu DESC LIMIT 10;"}'
                ]
            )
            out = run_datamate_enhanced_turn(
                q_tbl,
                fake_saoke_client,
                "Ollama (Local AI Offline)",
                "veraxus-coder:3b",
                kw,
                lang="vi",
            )
            self.assertIsNotNone(out.get("df"))
            df_out = out["df"]
            self.assertEqual(len(df_out), 5)
            self.assertFalse(df_out.iloc[:, 0].isna().any())
            self.assertEqual(df_out.iloc[0, 0], "Đi chợ, siêu thị")
            self.assertEqual(float(df_out.iloc[0, 1]), 83052000.0)
            self.assertEqual(df_out.iloc[-1, 0], "Y tế, sức khoẻ")
            self.assertEqual(float(df_out.iloc[-1, 1]), 3918000.0)
            self.assertTrue((df_out.iloc[:, 1] > 0).all())

            # Semantic guard rejects negative ranking result directly
            bad_sql = "SELECT danh_muc, ROUND_HALF_UP(SUM(so_tien), 0) AS doanh_thu FROM nganhanga_saoke GROUP BY danh_muc ORDER BY doanh_thu DESC"
            ok_neg, msg_neg, fatal_neg = verify_sql_semantics(
                bad_sql,
                SQLExecutionResult(
                    ok=True,
                    sql=bad_sql,
                    columns=["danh_muc", "doanh_thu"],
                    rows=[("Y tế, sức khoẻ", -3918000), ("Đi chợ, siêu thị", -83052000)],
                    row_count=2,
                ),
                "Top 10 danh mục có tổng số tiền cao nhất",
                kw,
                classify_expected_type("Top 10 danh mục có tổng số tiền cao nhất"),
            )
            self.assertFalse(ok_neg)
            self.assertTrue(fatal_neg)
            self.assertIn("LỖI DẤU ÂM", msg_neg)

            # Explicit net cashflow question MUST keep signed arithmetic
            net_q = "Chênh lệch thu chi ròng trong nganhanga_saoke là bao nhiêu?"
            self.assertTrue(_allows_negative_net_result("chenh lech thu chi rong trong nganhanga_saoke la bao nhieu"))
            net_sql = "SELECT ROUND_HALF_UP(SUM(so_tien), 0) AS thu_chi_rong FROM nganhanga_saoke;"
            self.assertEqual(
                rewrite_signed_cashflow_sql(net_sql, net_q, kw, classify_expected_type(net_q)),
                net_sql,
            )


if __name__ == "__main__":
    unittest.main()
