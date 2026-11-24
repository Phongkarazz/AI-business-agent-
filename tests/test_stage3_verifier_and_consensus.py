"""Unit tests for Stage 3: Bare Lunar Dates, Quote Healing, Grain/Sanity Verifiers, Forced Python & When2Call Consensus Gate."""

from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

import openpyxl

from datamate.agent import (
    AgentConfig,
    DataMateAgent,
    QuestionAnalysis,
    classify_expected_type,
    verify_result_sanity_bounds,
    verify_sql_semantics,
)
from datamate.llm_backend import MockLLMBackend, extract_json_object
from datamate.loader import load_business_workspace
from datamate.schema_context import build_workspace_knowledge
from datamate.sql_executor import SQLExecutionResult, extract_sql_from_response
from datamate.temporal import SolarLunarCalendar, parse_date_value


def _write_mini_calendar(cal_path: pathlib.Path) -> None:
    rows = [
        "date,weekday,lunar_day,lunar_month,lunar_year,lunar_leap,holiday",
        "2025-03-16,6,17,2,2025,False,",
        "2026-02-10,1,23,12,2025,False,",
        "2026-02-12,3,25,12,2025,False,",
        "2026-02-15,6,28,12,2025,False,",
        "2026-02-24,1,8,1,2026,False,",
        "2026-04-04,5,17,2,2026,False,",
        "2026-04-06,0,19,2,2026,False,",
    ]
    cal_path.write_text("\n".join(rows) + "\n", encoding="utf-8")


class TestStage3VerifierAndConsensus(unittest.TestCase):
    def test_bare_lunar_date_cell_conversion_with_row_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cal_path = root / "calendar.csv"
            _write_mini_calendar(cal_path)
            cal = SolarLunarCalendar(cal_path)

            # Without lunar_cal, bare '17/2 ÂL' must never misparse as solar 2026-02-17
            self.assertEqual(parse_date_value("17/2 ÂL", default_year=2026, lunar_cal=None), (None, None))
            # With lunar_cal + row anchor near 2026-02-24 -> 2026-04-04; cross-year Tet '25/12 ÂL' near 2026-02-10 -> 2026-02-12
            self.assertEqual(
                parse_date_value("17/2 ÂL", default_year=2026, lunar_cal=cal, anchor_date="2026-02-24"),
                ("2026-04-04", None),
            )
            self.assertEqual(
                parse_date_value("25/12 ÂL", default_year=2026, lunar_cal=cal, anchor_date="2026-02-10"),
                ("2026-02-12", None),
            )

            data_dir = root / "data" / "shop_lunar"
            data_dir.mkdir(parents=True)
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Lịch thuê"
            ws.append(["Mã phiếu", "Ngày đặt", "Ngày lấy", "Ngày hẹn trả", "Khách"])
            ws.append(["P0493", "2026-02-24", "17/2 ÂL", "2026-04-06", "Chị Hoa"])
            ws.append(["P0494", "2026-02-10", "25/12 ÂL", "2026-02-15", "Anh Minh"])
            ws.append(["P0495", "2026-04-04", "2026-04-05", "2026-04-06", "Chị Lan"])
            wb.save(data_dir / "lich_thue.xlsx")

            loaded = load_business_workspace(data_dir, cache_dir=root / "cache")
            conn = loaded.open_connection()
            try:
                rows = conn.execute(
                    "SELECT ma_phieu, ngay_lay FROM lich_thue ORDER BY ma_phieu"
                ).fetchall()
            finally:
                conn.close()
            self.assertEqual(rows, [("P0493", "2026-04-04"), ("P0494", "2026-02-12"), ("P0495", "2026-04-05")])

    def test_unclosed_backtick_and_dquote_healing(self) -> None:
        self.assertEqual(
            extract_sql_from_response("SELECT COUNT(*) FROM `dm_coso"),
            "SELECT COUNT(*) FROM `dm_coso`",
        )
        self.assertEqual(
            extract_sql_from_response('SELECT COUNT(*) FROM "don hang'),
            'SELECT COUNT(*) FROM "don hang"',
        )
        # Balanced backticks / single-quoted apostrophes remain untouched
        self.assertEqual(
            extract_sql_from_response("SELECT COUNT(*) FROM `dm_coso` WHERE note = 'a`b'"),
            "SELECT COUNT(*) FROM `dm_coso` WHERE note = 'a`b'",
        )
        # Lenient \' recovery inside small-LLM JSON objects
        self.assertEqual(
            extract_json_object(r'{"status": "ok", "sql": "SELECT \'abc\'"}'),
            {"status": "ok", "sql": "SELECT 'abc'"},
        )

    def test_order_grain_average_guard_check_3c(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            bdir = root / "biz_aov"
            bdir.mkdir()
            (bdir / "chi_tiet_don.csv").write_text(
                "ma_don,ngay_ban,ten_hang,thanh_tien,trang_thai\n"
                "DH01,2025-03-05,Sữa,300000,Hoàn thành\n"
                "DH01,2025-03-05,Bánh,300000,Hoàn thành\n"
                "DH02,2025-03-08,Trà,400000,Hoàn thành\n",
                encoding="utf-8",
            )
            ws = load_business_workspace(bdir, cache_dir=root / "cache")
            know = build_workspace_knowledge(ws)
            self.assertTrue(know.table_grains["chi_tiet_don"]["has_repeating_orders"])

            def mock_llm(prompt: str, system_prompt: str) -> str:
                if "LỖI ĐƠN VỊ TRUNG BÌNH TRÊN ĐƠN" in prompt:
                    return (
                        '{"status": "ok", "sql": "SELECT ROUND_HALF_UP(SUM(thanh_tien) * 1.0 / COUNT(DISTINCT ma_don), 0) '
                        'FROM chi_tiet_don WHERE trang_thai = \'Hoàn thành\' AND ngay_ban LIKE \'2025-03-%\'"}'
                    )
                return (
                    '{"status": "ok", "sql": "SELECT ROUND_HALF_UP(SUM(thanh_tien) * 1.0 / COUNT(*), 0) '
                    'FROM chi_tiet_don WHERE trang_thai = \'Hoàn thành\' AND ngay_ban LIKE \'2025-03-%\'"}'
                )

            agent = DataMateAgent(
                backend=MockLLMBackend(mock_llm),
                config=AgentConfig(max_sql_retries=3, enable_llm_formatter_fallback=False),
            )
            res = agent.answer_question(
                {
                    "id": "q_aov",
                    "business_id": "biz_aov",
                    "as_of_date": "2025-03-31",
                    "question": "Doanh thu trung bình trên một đơn tháng 3/2025 là bao nhiêu?",
                },
                know,
            )
            self.assertEqual(res.sql_attempts, 2)
            self.assertEqual(res.prediction, {"id": "q_aov", "type": "number", "answer": 500000})

    def test_percentage_share_bound_and_growth_over_100(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            bdir = root / "biz_pct"
            bdir.mkdir()
            (bdir / "sobanhang.csv").write_text(
                "ma_don,ngay_ban,thanh_tien,trang_thai\n"
                "D1,2025-05-05,100000,Hoàn thành\n"
                "D2,2025-06-05,250000,Hoàn thành\n"
                "D3,2025-06-06,200000,Đã huỷ\n"
                "D4,2025-06-07,100000,Hoàn thành\n"
                "D5,2025-06-08,100000,Hoàn thành\n"
                "D6,2025-06-09,100000,Hoàn thành\n",
                encoding="utf-8",
            )
            ws = load_business_workspace(bdir, cache_dir=root / "cache")
            know = build_workspace_knowledge(ws)

            # Bounded share rate (> 100%) blocked as fatal
            q_cancel = "tỉ lệ huỷ đơn tháng 6/2025 là nhiêu %"
            qa_cancel = classify_expected_type(q_cancel)
            bad_pct_res = SQLExecutionResult(ok=True, sql="SELECT 6801109.54", columns=["pct"], rows=[(6801109.54,)], row_count=1)
            ok, msg, fatal = verify_result_sanity_bounds("SELECT ...", bad_pct_res, q_cancel, know, qa_cancel)
            self.assertFalse(ok)
            self.assertTrue(fatal)
            self.assertIn("[0%, 100%]", msg)

            # Growth % over 100% MUST remain allowed
            q_growth = "doanh thu tháng 6/2025 tăng bao nhiêu % so với tháng 5/2025?"
            qa_growth = classify_expected_type(q_growth)
            growth_res = SQLExecutionResult(ok=True, sql="SELECT 450.0", columns=["pct"], rows=[(450.0,)], row_count=1)
            ok_g, _, _ = verify_result_sanity_bounds("SELECT ...", growth_res, q_growth, know, qa_growth)
            self.assertTrue(ok_g)

            # Negative gross revenue blocked as fatal
            q_rev = "Tổng doanh thu tháng 6/2025 là bao nhiêu?"
            qa_rev = classify_expected_type(q_rev)
            neg_res = SQLExecutionResult(ok=True, sql="SELECT -50000", columns=["dt"], rows=[(-50000,)], row_count=1)
            ok_n, _, fatal_n = verify_result_sanity_bounds("SELECT ...", neg_res, q_rev, know, qa_rev)
            self.assertFalse(ok_n)
            self.assertTrue(fatal_n)

    def test_forced_python_escalation_and_dual_path_consensus_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            bdir = root / "biz_stage3_gate"
            bdir.mkdir()
            (bdir / "sobanhang.csv").write_text(
                "ma_don,ngay_ban,khach_hang,thanh_tien,trang_thai\n"
                "D1,2025-06-05,Chị Lan,527k + 338000,Hoàn thành\n"
                "D2,2025-06-06,Anh Tú,200000,Đã huỷ\n"
                "D3,2025-06-07,Chị Mai,100000,Hoàn thành\n"
                "D4,2025-06-08,Chị Mai,100000,Hoàn thành\n",
                encoding="utf-8",
            )
            ws = load_business_workspace(bdir, cache_dir=root / "cache")
            know = build_workspace_knowledge(ws)

            # 1. Compound cells force Python-First prompt -> exact 865000 + 200000 = 1065000
            seen_prompts: list[str] = []

            def py_first_llm(prompt: str, system_prompt: str) -> str:
                seen_prompts.append(prompt)
                return json.dumps({
                    "status": "ok",
                    "python": (
                        "df = query_df(\"SELECT thanh_tien, trang_thai FROM sobanhang WHERE trang_thai != 'Đã huỷ'\")\n"
                        "result = round_half_up(df['thanh_tien'].apply(sum_compound_vn_nums).sum(), 0)"
                    ),
                })

            agent_py = DataMateAgent(
                backend=MockLLMBackend(py_first_llm),
                config=AgentConfig(
                    enable_llm_formatter_fallback=False,
                    force_stage3_on_custom_backend=True,
                ),
            )
            res_py = agent_py.answer_question(
                {
                    "id": "q_comp",
                    "business_id": "biz_stage3_gate",
                    "as_of_date": "2025-06-30",
                    "question": "Tổng doanh thu hợp lệ tháng 6/2025 là bao nhiêu?",
                },
                know,
            )
            self.assertTrue(any("BẮT BUỘC DÙNG PYTHON SANDBOX" in p for p in seen_prompts))
            self.assertTrue(res_py.sql.startswith("-- [PYTHON_SANDBOX]"))
            self.assertEqual(res_py.prediction, {"id": "q_comp", "type": "number", "answer": 1065000})

            # 2. Dual-path Consensus AGREE vs DISAGREE on repaired/percent queries
            (bdir / "sobanhang.csv").write_text(
                "ma_don,ngay_ban,khach_hang,thanh_tien,trang_thai\n"
                "D1,2025-06-05,Chị Lan,300000,Hoàn thành\n"
                "D2,2025-06-06,Anh Tú,200000,Đã huỷ\n"
                "D3,2025-06-07,Chị Mai,100000,Hoàn thành\n"
                "D4,2025-06-08,Chị Mai,400000,Hoàn thành\n",
                encoding="utf-8",
            )
            ws2 = load_business_workspace(bdir, cache_dir=root / "cache", force_rebuild=True)
            know2 = build_workspace_knowledge(ws2)

            def agree_llm(prompt: str, system_prompt: str) -> str:
                if "KIỂM CHỨNG ĐỘC LẬP" in prompt:
                    return json.dumps({
                        "status": "ok",
                        "python": (
                            "df = query_df('SELECT ma_don, trang_thai FROM sobanhang')\n"
                            "result = round((df['trang_thai'] == 'Đã huỷ').mean() * 100.0, 2)"
                        ),
                    })
                return '{"status": "ok", "sql": "SELECT ROUND(SUM(CASE WHEN trang_thai = \'Đã huỷ\' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) FROM sobanhang"}'

            agent_agree = DataMateAgent(
                backend=MockLLMBackend(agree_llm),
                config=AgentConfig(enable_llm_formatter_fallback=False, force_stage3_on_custom_backend=True),
            )
            res_agree = agent_agree.answer_question(
                {"id": "q_agree", "business_id": "biz_stage3_gate", "as_of_date": "2025-06-30", "question": "Tỉ lệ đơn huỷ là bao nhiêu %?"},
                know2,
            )
            self.assertEqual(res_agree.prediction, {"id": "q_agree", "type": "percent", "answer": 25.0})
            self.assertGreaterEqual(res_agree.confidence, 0.94)
            self.assertTrue(any("AGREE" in n for n in res_agree.notes))

            def disagree_llm(prompt: str, system_prompt: str) -> str:
                if "KIỂM CHỨNG ĐỘC LẬP" in prompt:
                    return json.dumps({
                        "status": "ok",
                        "python": (
                            "df = query_df('SELECT ma_don, trang_thai FROM sobanhang')\n"
                            "result = round((df['trang_thai'] == 'Đã huỷ').mean() * 100.0, 2)"
                        ),
                    })
                return '{"status": "ok", "sql": "SELECT 50.0"}'

            agent_dis = DataMateAgent(
                backend=MockLLMBackend(disagree_llm),
                config=AgentConfig(enable_llm_formatter_fallback=False, force_stage3_on_custom_backend=True),
            )
            res_dis = agent_dis.answer_question(
                {"id": "q_dis", "business_id": "biz_stage3_gate", "as_of_date": "2025-06-30", "question": "Tỉ lệ đơn huỷ là bao nhiêu %?"},
                know2,
            )
            self.assertEqual(res_dis.prediction["type"], "abstain")
            self.assertLess(res_dis.confidence, 0.52)

            # 3. Unresolved suspicious 0 on named entity abstains via When2Call gate instead of emitting wrong 0
            def zero_llm(prompt: str, system_prompt: str) -> str:
                return (
                    '{"status": "ok", "sql": "SELECT COALESCE(SUM(thanh_tien), 0) FROM sobanhang '
                    'WHERE khach_hang = \'Nhi\' AND ngay_ban = \'2025-06-05\'"}'
                )

            agent_zero = DataMateAgent(
                backend=MockLLMBackend(zero_llm),
                config=AgentConfig(max_sql_retries=2, enable_llm_formatter_fallback=False, force_stage3_on_custom_backend=True),
            )
            res_zero = agent_zero.answer_question(
                {
                    "id": "q_zero",
                    "business_id": "biz_stage3_gate",
                    "as_of_date": "2025-06-30",
                    "question": "Khách tên Nhi mua ngày 05/06/2025 hết bao nhiêu tiền?",
                },
                know2,
            )
            self.assertEqual(res_zero.prediction["type"], "abstain")
            self.assertLess(res_zero.confidence, 0.52)


if __name__ == "__main__":
    unittest.main()
