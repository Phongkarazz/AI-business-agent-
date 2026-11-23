"""Regression UI/integration tests for Classic Northwind and Universal Imported Dashboards."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
from streamlit.testing.v1 import AppTest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.database.business_upload import build_datamate_workspace_engine
from src.database.crm_queries import (
    detect_dashboard_domain,
    discover_generic_database_schema,
    fetch_generic_overview_data,
)


def _render_dashboard_fn():
    import streamlit as st
    from src.ui.crm_dashboard import _render_northwind_dashboard, _render_generic_dashboard

    eng = st.session_state["test_dash_engine"]
    dom = st.session_state["test_dash_domain"]
    st.session_state["lang"] = "vi"
    if dom == "northwind_erp":
        _render_northwind_dashboard(eng)
    else:
        _render_generic_dashboard(eng)


def _build_minimal_classic_northwind():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE Categories (CategoryID INTEGER PRIMARY KEY, CategoryName TEXT, Description TEXT)"))
        conn.execute(text("CREATE TABLE Suppliers (SupplierID INTEGER PRIMARY KEY, CompanyName TEXT, ContactName TEXT, ContactTitle TEXT, City TEXT, Country TEXT)"))
        conn.execute(text("CREATE TABLE Products (ProductID INTEGER PRIMARY KEY, ProductName TEXT, SupplierID INTEGER, CategoryID INTEGER, QuantityPerUnit TEXT, UnitPrice REAL, UnitsInStock INTEGER, UnitsOnOrder INTEGER)"))
        conn.execute(text("CREATE TABLE Customers (CustomerID TEXT PRIMARY KEY, CompanyName TEXT, ContactName TEXT, ContactTitle TEXT, City TEXT, Country TEXT)"))
        conn.execute(text("CREATE TABLE Employees (EmployeeID INTEGER PRIMARY KEY, LastName TEXT, FirstName TEXT, Title TEXT, City TEXT, Country TEXT)"))
        conn.execute(text("CREATE TABLE Orders (OrderID INTEGER PRIMARY KEY, CustomerID TEXT, EmployeeID INTEGER, OrderDate TEXT, ShippedDate TEXT, Freight REAL, ShipCity TEXT, ShipCountry TEXT)"))
        conn.execute(text('CREATE TABLE "Order Details" (OrderID INTEGER, ProductID INTEGER, UnitPrice REAL, Quantity INTEGER, Discount REAL)'))

        conn.execute(text("INSERT INTO Categories VALUES (1, 'Beverages', 'Coffee & Tea'), (2, 'Confections', 'Desserts')"))
        conn.execute(text("INSERT INTO Suppliers VALUES (1, 'Exotic Liquids', 'Charlotte Cooper', 'Purchasing Manager', 'London', 'UK')"))
        conn.execute(text("INSERT INTO Products VALUES (1, 'Côte de Blaye', 1, 1, '12 bottles', 263.5, 17, 0), (2, 'Chai', 1, 1, '10 boxes', 18.0, 39, 0)"))
        conn.execute(text("INSERT INTO Customers VALUES ('ALFKI', 'Alfreds Futterkiste', 'Maria Anders', 'Sales Representative', 'Berlin', 'Germany')"))
        conn.execute(text("INSERT INTO Employees VALUES (1, 'Davolio', 'Nancy', 'Sales Representative', 'Seattle', 'USA')"))
        conn.execute(text("INSERT INTO Orders VALUES (10248, 'ALFKI', 1, '2022-07-04 00:00:00', '2022-07-16 00:00:00', 32.38, 'Berlin', 'Germany')"))
        conn.execute(text('INSERT INTO "Order Details" VALUES (10248, 1, 263.5, 10, 0.0), (10248, 2, 18.0, 5, 0.1)'))
    return eng


class TestDashboardRendering(unittest.TestCase):
    def test_classic_northwind_dashboard_renders_nonzero_metrics(self) -> None:
        eng = _build_minimal_classic_northwind()
        try:
            self.assertEqual(detect_dashboard_domain(eng), "northwind_erp")
            at = AppTest.from_function(_render_dashboard_fn)
            at.session_state["test_dash_engine"] = eng
            at.session_state["test_dash_domain"] = "northwind_erp"
            at.session_state["northwind_dashboard_layer"] = "overview"
            at.run(timeout=20)
            self.assertFalse(at.exception)
            rendered_html = " ".join(getattr(m, "value", "") for m in at.markdown)
            self.assertIn("$2,716.00", rendered_html)
            self.assertNotIn("$0.00", rendered_html)
            self.assertEqual(len(at.get("plotly_chart")), 4)
        finally:
            eng.dispose()

    def test_imported_cafe_excel_dashboard_renders_rich_kpis_and_charts(self) -> None:
        cafe_dir = ROOT_DIR / "data" / "demo_businesses" / "cafe_pho_viet"
        eng, _ = build_datamate_workspace_engine(cafe_dir)
        try:
            self.assertEqual(detect_dashboard_domain(eng), "generic")
            at = AppTest.from_function(_render_dashboard_fn)
            at.session_state["test_dash_engine"] = eng
            at.session_state["test_dash_domain"] = "generic"
            at.session_state["generic_dashboard_layer"] = "overview"
            at.run(timeout=20)
            self.assertFalse(at.exception)
            rendered_html = " ".join(getattr(m, "value", "") for m in at.markdown)
            self.assertIn("1,262,000 đ", rendered_html)
            self.assertNotIn("1,427,000 đ", rendered_html)
            self.assertIn("Cà phê sữa đá", rendered_html)
            self.assertGreaterEqual(len(at.get("plotly_chart")), 3)
        finally:
            eng.dispose()

    def test_imported_vlxd_excel_dashboard_renders_receivables_and_charts(self) -> None:
        vlxd_dir = ROOT_DIR / "data" / "demo_businesses" / "vlxd_minh_phat"
        eng, _ = build_datamate_workspace_engine(vlxd_dir)
        try:
            self.assertEqual(detect_dashboard_domain(eng), "generic")
            at = AppTest.from_function(_render_dashboard_fn)
            at.session_state["test_dash_engine"] = eng
            at.session_state["test_dash_domain"] = "generic"
            at.session_state["generic_dashboard_layer"] = "overview"
            at.run(timeout=20)
            self.assertFalse(at.exception)
            rendered_html = " ".join(getattr(m, "value", "") for m in at.markdown)
            self.assertIn("50,500,000 đ", rendered_html)
            self.assertIn("16,000,000 đ", rendered_html)
            self.assertNotIn("54,700,000 đ", rendered_html)
            self.assertGreaterEqual(len(at.get("plotly_chart")), 3)
        finally:
            eng.dispose()

    def test_nha_thuoc_dashboard_clean_alert_strip_and_humanized_labels(self) -> None:
        nt_dir = ROOT_DIR / "data" / "demo_businesses" / "nha_thuoc_an_tam"
        eng, _ = build_datamate_workspace_engine(nt_dir)
        try:
            self.assertEqual(detect_dashboard_domain(eng), "generic")
            sm = discover_generic_database_schema(eng)
            ov = fetch_generic_overview_data(eng, sm)
            cat_map = {
                str(r["Category"]): float(r["MetricSum"])
                for _, r in ov["cat_dist_df"].iterrows()
            }
            self.assertEqual(ov["sum_val"], 1780000.0)
            self.assertEqual(ov["excluded_status_count"], 1)
            self.assertEqual(cat_map.get("Panadol Extra"), 540000.0)
            self.assertEqual(cat_map.get("Nước muối sinh lý"), 120000.0)
            self.assertAlmostEqual(
                cat_map["Panadol Extra"] / cat_map["Nước muối sinh lý"],
                4.5,
                places=4,
            )

            at = AppTest.from_function(_render_dashboard_fn)
            at.session_state["test_dash_engine"] = eng
            at.session_state["test_dash_domain"] = "generic"
            at.session_state["generic_dashboard_layer"] = "overview"
            at.run(timeout=20)
            self.assertFalse(at.exception)

            rendered_html = " ".join(getattr(m, "value", "") for m in at.markdown)
            btn_labels = [str(getattr(b, "label", "") or "") for b in at.button]
            all_btn_text = " ".join(btn_labels)

            # Redundant multi-layer panel, Resolution, Copilot dialog, leaked HR/count/cancelled bugs must be gone
            for forbidden in (
                "Phân Tích Dữ Liệu & Chiến Lược Quản Trị",
                "Ban Hành Nghị Quyết Chiến Lược",
                "Hỏi Trợ Lý Copilot Về Điểm Này",
                "Đứt gãy tuyển dụng",
                "Xu Hướng doanh_thu",
                "Xếp Hạng ten_thuoc",
                "Cơ Cấu Theo kenh_ban",
                "1,840,000 đ",
                "3.0x",
                "37.5%",
                "Nhóm hàng",
            ):
                self.assertNotIn(forbidden, rendered_html)
                self.assertNotIn(forbidden, all_btn_text)

            # Parity numbers (1,780,000 đ / 4.5x / 30.3%) & humanized Vietnamese labels must be present
            self.assertIn("1,780,000 đ", rendered_html)
            self.assertIn("4.5x", rendered_html)
            self.assertIn("30.3%", rendered_html)
            self.assertIn("Doanh thu", rendered_html)
            self.assertIn("Tên thuốc", rendered_html)
            self.assertIn("Kênh bán", rendered_html)
            self.assertIn("Điểm cần chú ý", rendered_html)

            chat_btn = next((b for b in at.button if "Phân tích trong Chat" in str(getattr(b, "label", ""))), None)
            self.assertIsNotNone(chat_btn, f"Missing 'Phân tích trong Chat' button in {btn_labels}")
            chat_btn.click().run(timeout=20)
            self.assertFalse(at.exception)
            self.assertEqual(at.session_state["view_mode"], "chat")
            self.assertTrue(str(at.session_state["pending_prompt"]).strip())
        finally:
            eng.dispose()

    def test_goi2_visual_cleanliness_and_minimal_chat_banners(self) -> None:
        import pandas as pd
        from unittest.mock import patch
        from src.ui.components import (
            _build_query_scope_summary,
            render_multi_agent_pipeline_ribbon,
            render_veraxus_loading_html,
        )

        # 1. Loading indicator must be minimalist 3 orbiting dots with calm jargon-free copy
        loading_html_vi = render_veraxus_loading_html(
            "⚡ [Agent 2/5 • Data Engineer] Kích hoạt In-Context Learning & Sinh truy vấn SQL..."
        )
        self.assertIn("vx-loading-bar", loading_html_vi)
        self.assertIn("vx-orbit-dots", loading_html_vi)
        self.assertIn("Đang tính toán số liệu...", loading_html_vi)

        loading_html_en = render_veraxus_loading_html("Calculating revenue metrics via SQL...")
        self.assertIn("vx-loading-bar", loading_html_en)
        self.assertIn("vx-orbit-dots", loading_html_en)
        self.assertIn("Calculating metrics...", loading_html_en)

        for combined_html in (loading_html_vi, loading_html_en):
            for forbidden_load in (
                "Bước 2/5",
                "Agent",
                "SQL",
                "In-Context Learning",
                "Maker-Checker",
                "VERAXUS LIVE MATRIX",
                "#00F0FF",
                "COMPILING",
                "SUPERVISING",
                "STANDBY AUDIT",
            ):
                self.assertNotIn(forbidden_load, combined_html)

        # 2. Multi-agent ribbon must stay silent on 100/100 PASS and show calm notice when degraded
        captured_md: list[str] = []
        sample_result_pass = {
            "agent_trace": {
                "plan": {"complexity": "DIRECT_SQL", "subtasks": ["t1", "t2"]},
                "schema_linking": {"selected_tables": ["hoa_don_ban", "phieu_nhap_thuoc"]},
            },
            "evaluator": {"score": 100, "verdict": "PASS"},
            "anomalies_info": {"findings": [{"title": "Outlier"}]},
            "attempts": 1,
            "execution_time_ms": 240.0,
        }
        with patch("src.ui.components.st.markdown", side_effect=lambda body, **kw: captured_md.append(str(body))):
            render_multi_agent_pipeline_ribbon(sample_result_pass, is_en=False)
        self.assertEqual(captured_md, [])

        degraded_result = {
            "evaluator": {"score": 78, "verdict": "NEEDS_IMPROVEMENT"},
        }
        with patch("src.ui.components.st.markdown", side_effect=lambda body, **kw: captured_md.append(str(body))):
            render_multi_agent_pipeline_ribbon(degraded_result, is_en=False)
        self.assertEqual(len(captured_md), 1)
        ribbon_warn_html = captured_md[0]
        self.assertIn("78/100", ribbon_warn_html)
        for forbidden_ribbon in (
            "Hội đồng 5 Agent",
            "100% minh bạch",
            "MULTI-AGENT MATRIX",
            "100% MINH BẠCH TƯ DUY",
            "#00F0FF",
        ):
            self.assertNotIn(forbidden_ribbon, ribbon_warn_html)

        # 2b. Scope summary helper accurately extracts base tables (ignoring CTE aliases), filters, rows & timing
        sample_df = pd.DataFrame([{"ten_thuoc": "Panadol Extra", "doanh_thu": 540000}])
        cte_sql = (
            "WITH agg AS ("
            "SELECT h.ten_thuoc, SUM(h.doanh_thu) AS doanh_thu "
            "FROM hoa_don_ban h "
            "JOIN danh_muc_thuoc d ON h.ten_thuoc = d.ten_thuoc "
            "WHERE h.trang_thai != 'Đã hủy' AND h.ngay_ban >= '2026-10-01' "
            "GROUP BY h.ten_thuoc"
            ") SELECT ten_thuoc, doanh_thu FROM agg;"
        )
        scope = _build_query_scope_summary(
            {"execution_time_ms": 1840.0, "evaluator": {"score": 100, "verdict": "PASS"}},
            sample_df,
            cte_sql,
            is_en=False,
        )
        self.assertEqual(scope["tables"], ["hoa_don_ban", "danh_muc_thuoc"])
        self.assertNotIn("agg", scope["tables"])
        self.assertIn("Đã loại đơn hủy/trả", scope["filters"])
        self.assertIn("Có lọc khoảng thời gian", scope["filters"])
        self.assertEqual(scope["row_count"], 1)
        self.assertEqual(scope["time_str"], "1.8s")
        self.assertEqual(scope["audit_warning"], "")

        # Grouping by month without WHERE date filter must not claim a date filter
        no_where_date_scope = _build_query_scope_summary(
            {},
            sample_df,
            "SELECT STRFTIME('%Y-%m', ngay_ban) AS thang, SUM(doanh_thu) FROM hoa_don_ban WHERE trang_thai = 'Hoàn tất' GROUP BY thang;",
            is_en=False,
        )
        self.assertNotIn("Có lọc khoảng thời gian", no_where_date_scope["filters"])
        self.assertNotIn("Đã loại đơn hủy/trả", no_where_date_scope["filters"])

        # 2c. Multi-turn chat render_result must have 3 business tabs, zero 5-Agent tab/badges, and zero exceptions
        def _render_multi_turn_chat_fn():
            import pandas as pd
            import streamlit as st
            from src.ui.components import render_result

            for idx, r in enumerate(st.session_state["chat_results"]):
                with st.chat_message("assistant"):
                    render_result(r, turn_id=f"t{idx}")

        at_chat = AppTest.from_function(_render_multi_turn_chat_fn)
        turn_df = pd.DataFrame(
            [
                {"ten_thuoc": "Panadol Extra", "doanh_thu": 540000.0},
                {"ten_thuoc": "Vitamin C 500mg", "doanh_thu": 475000.0},
            ]
        )
        at_chat.session_state["chat_results"] = [
            {
                "query": "Top 2 loại thuốc theo doanh thu",
                "sql": "SELECT ten_thuoc, SUM(doanh_thu) AS doanh_thu FROM hoa_don_ban WHERE trang_thai != 'Đã hủy' GROUP BY ten_thuoc;",
                "df": turn_df,
                "evaluator": {"score": 100, "verdict": "PASS"},
                "execution_time_ms": 420.0,
                "lang": "vi",
                "insights": "",
                "followups": ["So sánh doanh thu theo kênh bán?"],
            },
            {
                "query": "Doanh thu theo kênh bán",
                "sql": "SELECT kenh_ban, SUM(doanh_thu) AS doanh_thu FROM hoa_don_ban WHERE trang_thai != 'Đã hủy' GROUP BY kenh_ban;",
                "df": pd.DataFrame(
                    [
                        {"kenh_ban": "Tại quầy", "doanh_thu": 1290000.0},
                        {"kenh_ban": "Zalo", "doanh_thu": 490000.0},
                    ]
                ),
                "evaluator": {"score": 100, "verdict": "PASS"},
                "execution_time_ms": 310.0,
                "lang": "vi",
                "insights": "",
                "followups": ["So sánh doanh thu theo ngày?"],
            },
        ]
        at_chat.run(timeout=20)
        self.assertFalse(at_chat.exception)
        # 2 turns x 3 main business tabs (excluding the 2 inner Share-Report sub-tabs per turn)
        tab_labels = [t.label for t in at_chat.tabs]
        main_tab_labels = [
            lbl for lbl in tab_labels
            if lbl not in ("🚀 Telegram Bot", "📧 Gửi Email (Gmail / SMTP)", "📧 Email (Gmail / SMTP)")
        ]
        self.assertEqual(len(main_tab_labels), 6)
        for forbidden_tab in ("Hội đồng 5 Agent", "5-Agent Matrix"):
            self.assertFalse(any(forbidden_tab in lbl for lbl in tab_labels))

        chat_all_text = " ".join(
            [getattr(m, "value", "") for m in at_chat.markdown]
            + [getattr(e, "label", "") for e in at_chat.expander]
            + [getattr(c, "value", "") for c in at_chat.caption]
        )
        for forbidden_chat in (
            "Độ tin cậy 100%",
            "100% minh bạch",
            "Fine-Tune Memory",
            "Hội đồng 5 Agent",
            "Ngân hàng Tri thức Động",
            "Dynamic Few-Shot Bank",
        ):
            self.assertNotIn(forbidden_chat, chat_all_text)

        # 3. Dashboard rendered HTML must have zero #00F0FF neon glows, no decorative chart badge pills, and no vibe-coding buzzwords
        nt_dir = ROOT_DIR / "data" / "demo_businesses" / "nha_thuoc_an_tam"
        eng, _ = build_datamate_workspace_engine(nt_dir)
        try:
            at = AppTest.from_function(_render_dashboard_fn)
            at.session_state["test_dash_engine"] = eng
            at.session_state["test_dash_domain"] = "generic"
            at.session_state["generic_dashboard_layer"] = "overview"
            at.run(timeout=20)
            self.assertFalse(at.exception)
            rendered_html = " ".join(getattr(m, "value", "") for m in at.markdown)
            self.assertNotIn("#00F0FF", rendered_html.upper())
            self.assertNotIn(">Daily Series<", rendered_html)
            self.assertNotIn(">Top Ranking<", rendered_html)
            for forbidden_buzzword in (
                "CSDL TỰ ĐỘNG THÍCH ỨNG",
                "ADAPTIVE SCHEMA • LIVE SQL",
                "kpi-top-row",
                ">TỔNG HỢP<",
                ">XÁC THỰC<",
                ">ĐỒNG BỘ<",
            ):
                self.assertNotIn(forbidden_buzzword, rendered_html)
        finally:
            eng.dispose()

    def test_chart_zoom_modal_domain_aware_explanations_and_recommendations(self) -> None:
        import pandas as pd
        from src.visualization.chart_modal import (
            generate_chart_smart_explanation,
            generate_contextual_action_recommendations,
        )
        from src.visualization.crm_dashboard_charts import (
            build_horizontal_bar_chart,
            build_tickets_by_type_donut,
        )

        # 1. Sales Channel Donut (Tại quầy vs Zalo) — works both with humanized zoom df AND raw status_df
        raw_status_df = pd.DataFrame(
            [
                {"Category": "Tại quầy", "Count": 5, "MetricSum": 1290000.0},
                {"Category": "Zalo", "Count": 2, "MetricSum": 490000.0},
            ]
        )
        fig_donut = build_tickets_by_type_donut(raw_status_df, label_col="Category", val_col="MetricSum")
        exp_ch, anom_ch, stats_ch = generate_chart_smart_explanation(
            title="Cơ cấu theo Kênh bán",
            df=raw_status_df,
            fig=fig_donut,
            custom_explanation="Tỷ trọng đóng góp theo Kênh bán.",
            user_query="Cơ cấu theo Kênh bán",
        )
        recs_ch = generate_contextual_action_recommendations(
            title="Cơ cấu theo Kênh bán",
            user_query="Cơ cấu theo Kênh bán",
            df=raw_status_df,
            anomalies=anom_ch,
            stats_summary=stats_ch,
            fig=fig_donut,
        )
        combined_ch = " ".join([exp_ch] + [a.get("text", "") + " " + a.get("badge", "") for a in anom_ch] + [r.get("title", "") + " " + r.get("action", "") for r in recs_ch])

        # Must analyze Revenue (1,780,000 đ / 1,290,000 đ / 490,000 đ / 72.5%) and identify 'kênh bán'
        self.assertIn("1,780,000 đ", exp_ch)
        self.assertIn("1,290,000 đ", exp_ch)
        self.assertIn("490,000 đ", exp_ch)
        self.assertIn("72.5%", exp_ch)
        self.assertIn("2 kênh bán", exp_ch)
        self.assertIn("kênh", combined_ch.lower())

        # Must NEVER output the old absurd phrases
        for forbidden_phrase in (
            "2 team",
            "chỉ số Count",
            "3.50",
            "Thông Điệp Điều Hành Cốt Lõi",
            "Chuyên Gia BI",
            "Ngôi đầu thuộc về",
            "Á quân",
            "Đầu Tàu Dẫn Dắt",
            "dòng sản phẩm chủ lực dẫn đầu Tại quầy",
            "mã sản phẩm chậm luân chuyển (Zalo)",
            "COGS Optimization",
        ):
            self.assertNotIn(forbidden_phrase, combined_ch)

        # 2. Medicine Ranking Chart (Xếp hạng Tên thuốc theo Doanh thu)
        cat_zoom_df = pd.DataFrame(
            [
                {"Tên thuốc": "Panadol Extra", "Doanh thu (đ)": 540000.0, "Số giao dịch": 2},
                {"Tên thuốc": "Men tiêu hóa Enterogermina", "Doanh thu (đ)": 480000.0, "Số giao dịch": 1},
                {"Tên thuốc": "Vitamin C 500mg", "Doanh thu (đ)": 475000.0, "Số giao dịch": 2},
                {"Tên thuốc": "Si rô ho Bảo Thanh", "Doanh thu (đ)": 165000.0, "Số giao dịch": 1},
                {"Tên thuốc": "Nước muối sinh lý", "Doanh thu (đ)": 120000.0, "Số giao dịch": 1},
            ]
        )
        fig_bar = build_horizontal_bar_chart(cat_zoom_df, y_col="Tên thuốc", x_col="Doanh thu (đ)", name="Doanh thu")
        exp_med, anom_med, stats_med = generate_chart_smart_explanation(
            title="Xếp hạng Tên thuốc theo Doanh thu",
            df=cat_zoom_df,
            fig=fig_bar,
            user_query="Xếp hạng Tên thuốc theo Doanh thu",
        )
        recs_med = generate_contextual_action_recommendations(
            title="Xếp hạng Tên thuốc theo Doanh thu",
            user_query="Xếp hạng Tên thuốc theo Doanh thu",
            df=cat_zoom_df,
            anomalies=anom_med,
            stats_summary=stats_med,
            fig=fig_bar,
        )
        self.assertIn("5 loại thuốc", exp_med)
        self.assertIn("540,000 đ", exp_med)
        self.assertIn("120,000 đ", exp_med)
        self.assertIn("4.5 lần", exp_med)
        self.assertNotIn("Thông Điệp Điều Hành Cốt Lõi", exp_med)
        self.assertTrue(any("Panadol Extra" in r.get("title", "") for r in recs_med))

        # 3. Payment Method Chart (Cafe Phố Việt: Tiền mặt vs Chuyển khoản)
        pay_df = pd.DataFrame(
            [
                {"Thanh toán": "Chuyển khoản", "Thành tiền (đ)": 740000.0, "Số giao dịch": 3},
                {"Thanh toán": "Tiền mặt", "Thành tiền (đ)": 522000.0, "Số giao dịch": 3},
            ]
        )
        exp_pay, anom_pay, stats_pay = generate_chart_smart_explanation(
            title="Cơ cấu theo Thanh toán",
            df=pay_df,
            user_query="Cơ cấu theo Thanh toán",
        )
        recs_pay = generate_contextual_action_recommendations(
            title="Cơ cấu theo Thanh toán",
            user_query="Cơ cấu theo Thanh toán",
            df=pay_df,
            anomalies=anom_pay,
            stats_summary=stats_pay,
        )
        self.assertIn("2 phương thức thanh toán", exp_pay)
        self.assertIn("740,000 đ", exp_pay)
        self.assertFalse(any("Cross-Selling" in r.get("title", "") or "tồn kho" in r.get("title", "") for r in recs_pay))

    def test_kpi_cards_option1_color_hierarchy_and_zoom_button_layout(self) -> None:
        from unittest.mock import patch
        from src.ui.crm_dashboard import _render_diagnostic_kpi_card

        crm_src = (ROOT_DIR / "src" / "ui" / "crm_dashboard.py").read_text(encoding="utf-8")
        modal_src = (ROOT_DIR / "src" / "visualization" / "chart_modal.py").read_text(encoding="utf-8")

        # 1. Option 1 distinct per-class 3px top accents + zero #00F0FF neon
        for expected_accent in (
            "border-top: 3px solid #38BDF8",
            "border-top: 3px solid #A855F7",
            "border-top: 3px solid #10B981",
            "border-top: 3px solid #F59E0B",
            ".kpi-delta-up",
            ".kpi-delta-down",
            ".kpi-delta-warn",
            ".kpi-accent-dot",
            'st-key-btn_zoom_',
        ):
            self.assertIn(expected_accent, crm_src)
        self.assertNotIn("#00F0FF", crm_src.upper())

        # 2. Zoom button uses non-truncating layout & auto-width pill
        self.assertIn("st.columns([2.7, 1.5], vertical_alignment=\"center\")", modal_src)
        self.assertIn("use_container_width=False", modal_src)

        # 3. _render_diagnostic_kpi_card renders semantic delta & benchmark colors accurately
        captured: list[str] = []
        with patch("src.ui.crm_dashboard.st.markdown", side_effect=lambda body, **kw: captured.append(str(body))):
            _render_diagnostic_kpi_card(
                color_class="kpi-card-cyan",
                title="Tổng Doanh Thu",
                value_html="<span>$22,694,950</span><span class='kpi-delta-tag'>▲ +5.4%</span>",
                bench_label="Mục tiêu $20.8M",
                bench_pct=109.1,
                sub_text="TB $0.95M/tháng",
            )
            _render_diagnostic_kpi_card(
                color_class="kpi-card-purple",
                title="Số Hộp Bán",
                value_html="<span>399,376</span><span class='kpi-delta-tag'>▼ -3.2%</span>",
                bench_label="Định mức 420k",
                bench_pct=81.0,
                sub_text="Dưới chỉ tiêu",
            )
            _render_diagnostic_kpi_card(
                color_class="kpi-card-emerald",
                title="Tổng Lượt Khách",
                val_html="85,371",
                delta_str="100% CORE",
                delta_dir="flat",
                bench_label="Chuẩn 90k",
                bench_pct=94.8,
                status_level="warn",
                sub_text="Sát mục tiêu",
            )
            _render_diagnostic_kpi_card(
                color_class="kpi-card-amber",
                title="Tỷ trọng Top 1",
                val_html="Panadol Extra",
                delta_str="30.3% Share",
                delta_dir="up",
                bench_label="Tỷ trọng đóng góp",
                bench_pct=30.3,
                status_level="good",
                fill_color="linear-gradient(90deg, #F59E0B, #FBBF24)",
                sub_text="540,000 đ",
            )

        self.assertEqual(len(captured), 4)
        # Positive Sales card: accent dot + green delta + green benchmark pct + no kpi-top-row
        self.assertIn("kpi-accent-dot", captured[0])
        self.assertIn("kpi-delta-tag kpi-delta-up", captured[0])
        self.assertIn("color: #34D399;", captured[0])
        self.assertNotIn("kpi-top-row", captured[0])

        # Negative / below-target card: red delta + red benchmark pct
        self.assertIn("kpi-delta-tag kpi-delta-down", captured[1])
        self.assertIn("color: #F87171;", captured[1])

        # Warning card: warn delta + amber benchmark pct
        self.assertIn("kpi-delta-tag kpi-delta-warn", captured[2])
        self.assertIn("color: #FBBF24;", captured[2])

        # Share card with explicit status_level="good" + fill_color: stays amber accent, not falsely red!
        self.assertIn("kpi-delta-tag kpi-delta-up", captured[3])
        self.assertIn("color: #FBBF24;", captured[3])
        self.assertNotIn("#F87171", captured[3])

    def test_loading_stale_guard_and_surface_isolation_prevents_dashboard_ghosts(self) -> None:
        from src.ui.components import render_loading_stale_guard_css

        guard_css = render_loading_stale_guard_css()
        self.assertIn('data-vx-loading-guard="1"', guard_css)
        self.assertIn('[data-testid="stElementContainer"][data-stale="true"]', guard_css)
        self.assertIn('section[data-testid="stMain"]', guard_css)
        self.assertIn('display: none !important;', guard_css)
        # Must strictly scope to main viewport and never hide sidebar elements
        self.assertNotIn('stSidebar', guard_css)

        app_src = (ROOT_DIR / "app.py").read_text(encoding="utf-8")
        # Non-chat surfaces must be isolated inside st.container() at main[1] so chatMessage replaces them atomically
        self.assertIn("if view_mode == \"dashboard\" and not prompt_to_run:\n        with st.container():\n            render_crm_dashboard()", app_src)
        self.assertIn("elif view_mode == \"evolution\" and not prompt_to_run:\n        with st.container():", app_src)
        self.assertIn("if not history and focused_turn_idx is None and not prompt_to_run and view_mode == \"chat\":\n        with st.container():", app_src)
        # Focused turn reset must occur BEFORE routing when prompt_to_run is active
        reset_pos = app_src.index("if prompt_to_run:\n        focused_turn_idx = None")
        route_pos = app_src.index('if view_mode == "dashboard" and not prompt_to_run:')
        self.assertLess(reset_pos, route_pos)
        # Scoped loading guard must be mounted before run_agent and cleaned up in finally
        self.assertIn("loading_guard_placeholder.markdown(render_loading_stale_guard_css(), unsafe_allow_html=True)", app_src)
        self.assertIn("loading_guard_placeholder.empty()", app_src)


if __name__ == "__main__":
    unittest.main()
