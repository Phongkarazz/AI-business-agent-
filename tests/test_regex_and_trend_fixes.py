"""Regression tests for Veraxus UI regex safety, chart X-axis labeling, source_sheet date rewrites, and trend/peak SQL generation."""

from __future__ import annotations

import pathlib
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace

import pandas as pd

from datamate.agent import (
    build_time_series_or_period_ranking_sql_spec,
    classify_expected_type,
    rewrite_misused_source_sheet_date_filter,
    verify_sql_semantics,
)
from datamate.loader import load_business_workspace
from datamate.schema_context import build_workspace_knowledge
from datamate.sql_executor import SQLExecutionResult
from src.analytics.anomaly import analyze_data_anomalies
from src.analytics.heuristics import generate_hypothesis_tree, pick_label_column
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


if __name__ == "__main__":
    unittest.main()
