"""Regression tests for suggested/follow-up query buttons in Streamlit UI."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from sqlalchemy import create_engine, text
from streamlit.testing.v1 import AppTest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def _render_unanswerable_turn():
    import streamlit as st
    from src.ui.components import render_result

    turn = st.session_state["test_turn"]
    render_result(turn, turn_id="hist0")


def _render_dataframe_turn():
    import streamlit as st
    from src.ui.components import render_result

    turn = st.session_state["test_turn"]
    render_result(turn, turn_id="hist0")


class TestFollowupButtonsUI(unittest.TestCase):
    def test_compatible_suggested_button_sets_pending_prompt(self):
        at = AppTest.from_function(_render_unanswerable_turn)
        at.session_state["test_turn"] = {
            "query": "Liệt kê 5 khách hàng (CustomerID) có tỷ lệ hoàn trả đơn hàng (return rate) cao nhất.",
            "explanation": "🛡️ Dữ liệu không đủ thông tin để trả lời chính xác.",
            "df": None,
            "sql": None,
            "logs": ["[BLOCKED] UNANSWERABLE_BLOCKED"],
            "lang": "vi",
            "followups": [
                "Tổng Doanh Thu và tổng số hộp (Boxes) theo từng quốc gia (Geo) là bao nhiêu?",
                "Top 5 sản phẩm có Doanh Thu cao nhất và thuộc Category nào?",
                "Top 5 nhân viên bán hàng bán được nhiều hộp (Boxes) nhất?",
            ],
        }
        at.run(timeout=15)
        self.assertFalse(at.exception)

        compat_btns = [b for b in at.button if b.label.startswith("💬 ")]
        self.assertEqual(len(compat_btns), 3)

        compat_btns[1].click().run(timeout=15)
        self.assertFalse(at.exception)
        self.assertEqual(
            at.session_state["pending_prompt"],
            "Top 5 sản phẩm có Doanh Thu cao nhất và thuộc Category nào?",
        )
        self.assertIsNone(at.session_state["submitted_query"])
        self.assertEqual(at.session_state["view_mode"], "chat")

    def test_bottom_followup_dedup_and_click(self):
        at = AppTest.from_function(_render_dataframe_turn)
        df = pd.DataFrame({"Geo": ["India", "USA"], "Revenue": [1000.0, 2000.0]})
        at.session_state["test_turn"] = {
            "query": "Doanh thu theo quốc gia?",
            "explanation": None,
            "df": df,
            "sql": "SELECT Geo, SUM(Amount) AS Revenue FROM sales GROUP BY Geo",
            "logs": ["[SQL] OK"],
            "lang": "vi",
            "followups": [
                "",
                None,
                {"question": "Doanh thu theo Team?"},
                "Doanh thu theo Team?",
                "Top 5 sản phẩm bán chạy nhất?",
            ],
        }
        at.run(timeout=15)
        self.assertFalse(at.exception)

        fup_btns = [b for b in at.button if b.label.startswith("👉 ")]
        self.assertEqual(len(fup_btns), 2)
        self.assertEqual(fup_btns[0].label, "👉 Doanh Thu theo Team?")
        self.assertEqual(fup_btns[1].label, "👉 Top 5 sản phẩm bán chạy nhất?")

        fup_btns[0].click().run(timeout=15)
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["pending_prompt"], "Doanh Thu theo Team?")

    def test_empty_df_followup_button_sets_pending_prompt(self):
        at = AppTest.from_function(_render_dataframe_turn)
        at.session_state["test_turn"] = {
            "query": "Truy vấn không ra dữ liệu",
            "explanation": None,
            "df": pd.DataFrame(),
            "sql": "SELECT * FROM sales WHERE 1=0",
            "logs": [],
            "lang": "vi",
            "followups": ["Tổng doanh thu toàn công ty là bao nhiêu?"],
        }
        at.run(timeout=15)
        self.assertFalse(at.exception)

        empty_btns = [b for b in at.button if b.label.startswith("💬 ")]
        self.assertEqual(len(empty_btns), 1)
        empty_btns[0].click().run(timeout=15)
        self.assertEqual(
            at.session_state["pending_prompt"],
            "Tổng Doanh Thu toàn công ty là bao nhiêu?",
        )

    def test_full_app_compatible_and_followup_buttons_execute_agent(self):
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE geo (GeoID TEXT, Geo TEXT, Region TEXT)"))
            conn.execute(text("INSERT INTO geo VALUES ('G1', 'India', 'APAC')"))

        calls = []

        def fake_run_agent(*, user_query, **kwargs):
            calls.append(user_query)
            return {
                "query": user_query,
                "explanation": None,
                "df": pd.DataFrame({"Geo": ["India", "USA"], "TotalRevenue": [12000, 9500], "TotalBoxes": [300, 210]}),
                "sql": "SELECT g.Geo, SUM(s.Amount) AS TotalRevenue, SUM(s.Boxes) AS TotalBoxes FROM geo g",
                "logs": ["[MOCK] executed"],
                "lang": "vi",
                "followups": [
                    "Phân tích doanh thu theo sản phẩm?",
                    "So sánh hiệu suất theo từng đội ngũ (Team)?",
                ],
                "evaluator": {"score": 100},
            }

        at = AppTest.from_file(str(ROOT_DIR / "app.py"))
        at.session_state["_auto_connect_attempted"] = True
        at.session_state["connected"] = True
        at.session_state["engine"] = engine
        at.session_state["db_dialect"] = "SQLite"
        at.session_state["provider"] = "Ollama (Local AI Offline)"
        at.session_state["model_name"] = "qwen2.5-coder:3b"
        at.session_state["schema_context"] = "Table: geo(GeoID, Geo, Region)"
        at.session_state["view_mode"] = "chat"
        at.session_state["history"] = [
            {
                "query": "Liệt kê 5 khách hàng (CustomerID) có tỷ lệ hoàn trả đơn hàng (return rate) cao nhất.",
                "explanation": "🛡️ Dữ liệu không đủ thông tin để trả lời chính xác.",
                "df": None,
                "sql": None,
                "logs": ["[GATEKEEPER] UNANSWERABLE_BLOCKED"],
                "lang": "vi",
                "followups": [
                    "Tổng Doanh Thu và tổng số hộp (Boxes) theo từng quốc gia (Geo) là bao nhiêu?",
                    "Top 5 sản phẩm có Doanh Thu cao nhất và thuộc Category nào?",
                    "Top 5 nhân viên bán hàng bán được nhiều hộp (Boxes) nhất?",
                ],
            }
        ]

        old_cwd = os.getcwd()
        os.chdir(ROOT_DIR)
        try:
            import src.llm.agent  # noqa: F401
            with patch("importlib.reload", side_effect=lambda m: m), patch("src.llm.agent.run_agent", side_effect=fake_run_agent):
                at.run(timeout=20)
                self.assertFalse(at.exception)

                compat_btns = [b for b in at.button if b.label.startswith("💬 ")]
                self.assertEqual(len(compat_btns), 3)

                # Click compatible suggested query button
                compat_btns[0].click().run(timeout=20)
                self.assertFalse(at.exception)
                self.assertEqual(
                    calls,
                    ["Tổng Doanh Thu và tổng số hộp (Boxes) theo từng quốc gia (Geo) là bao nhiêu?"],
                )
                self.assertEqual(len(at.session_state["history"]), 2)
                self.assertIsNone(at.session_state["pending_prompt"])
                self.assertIsNone(at.session_state["submitted_query"])

                # Click bottom follow-up button rendered on the newly appended turn
                fup_btns = [b for b in at.button if b.label.startswith("👉 ")]
                self.assertEqual(len(fup_btns), 2)
                fup_btns[1].click().run(timeout=20)
                self.assertFalse(at.exception)
                self.assertEqual(len(calls), 2)
                self.assertEqual(calls[1], "So sánh hiệu suất theo từng đội ngũ (Team)?")
                self.assertEqual(len(at.session_state["history"]), 3)
                self.assertIsNone(at.session_state["pending_prompt"])
        finally:
            os.chdir(old_cwd)
            engine.dispose()

    def test_full_app_submitted_query_fallback_consumes_and_clears(self):
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE geo (GeoID TEXT, Geo TEXT)"))
            conn.execute(text("INSERT INTO geo VALUES ('G1', 'India')"))

        calls = []

        def fake_run_agent(*, user_query, **kwargs):
            calls.append(user_query)
            return {
                "query": user_query,
                "explanation": None,
                "df": pd.DataFrame({"Geo": ["India"], "Cnt": [1]}),
                "sql": "SELECT Geo, COUNT(*) AS Cnt FROM geo GROUP BY Geo",
                "logs": [],
                "lang": "vi",
                "followups": [],
                "evaluator": {"score": 100},
            }

        at = AppTest.from_file(str(ROOT_DIR / "app.py"))
        at.session_state["_auto_connect_attempted"] = True
        at.session_state["connected"] = True
        at.session_state["engine"] = engine
        at.session_state["db_dialect"] = "SQLite"
        at.session_state["provider"] = "Ollama (Local AI Offline)"
        at.session_state["model_name"] = "qwen2.5-coder:3b"
        at.session_state["schema_context"] = "Table: geo(GeoID, Geo)"
        at.session_state["view_mode"] = "chat"
        at.session_state["submitted_query"] = "Thống kê số quốc gia?"

        old_cwd = os.getcwd()
        os.chdir(ROOT_DIR)
        try:
            import src.llm.agent  # noqa: F401
            with patch("importlib.reload", side_effect=lambda m: m), patch("src.llm.agent.run_agent", side_effect=fake_run_agent):
                at.run(timeout=20)
                self.assertFalse(at.exception)
                self.assertEqual(calls, ["Thống kê số quốc gia?"])
                self.assertEqual(len(at.session_state["history"]), 1)
                self.assertIsNone(at.session_state["submitted_query"])
                self.assertIsNone(at.session_state["pending_prompt"])
        finally:
            os.chdir(old_cwd)
            engine.dispose()

    def test_auditor_integrity_badge_respects_eval_score(self):
        def _render_badges_only():
            import streamlit as st
            from src.ui.components import render_agent_workflow_badges

            render_agent_workflow_badges(st.session_state["badge_result"], turn_id="badge0")

        # 1. Degraded evaluator score (< 100) must NOT show fake "Độ tin cậy 100%"
        at_warn = AppTest.from_function(_render_badges_only)
        at_warn.session_state["badge_result"] = {
            "df": pd.DataFrame({"Country": ["Australia"], "TotalSales": [1854356]}),
            "evaluator": {"score": 75, "verdict": "NEEDS_IMPROVEMENT"},
            "attempts": 3,
            "logs": [],
            "lang": "vi",
        }
        at_warn.run(timeout=15)
        self.assertFalse(at_warn.exception)
        warn_html = " ".join(getattr(m, "value", "") for m in at_warn.markdown)
        self.assertNotIn("Độ tin cậy 100%", warn_html)
        self.assertNotIn("Hội đồng 5 Agent", warn_html)
        self.assertIn("75/100", warn_html)

        # 2. Passing 100/100 score stays silent (no noisy "Độ tin cậy 100%" / "100% minh bạch" clutter)
        at_ok = AppTest.from_function(_render_badges_only)
        at_ok.session_state["badge_result"] = {
            "df": pd.DataFrame({"Country": ["Australia"], "TotalSales": [1854356]}),
            "evaluator": {"score": 100, "verdict": "PASS"},
            "attempts": 1,
            "logs": [],
            "lang": "vi",
        }
        at_ok.run(timeout=15)
        self.assertFalse(at_ok.exception)
        ok_html = " ".join(getattr(m, "value", "") for m in at_ok.markdown)
        self.assertEqual(ok_html.strip(), "")
        self.assertNotIn("Độ tin cậy 100%", ok_html)
        self.assertNotIn("100% minh bạch", ok_html)


if __name__ == "__main__":
    unittest.main()
