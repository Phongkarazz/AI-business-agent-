"""Regression tests for schema-capability guards and HR/qualifier unanswerable handling."""

from __future__ import annotations

import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

import pandas as pd

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from datamate.agent import check_preflight_unanswerable, classify_expected_type
from datamate.loader import BusinessWorkspace, ColumnProfile, TableProfile
from datamate.schema_context import WorkspaceKnowledge
from src.database.demo_data import build_demo_engine
from src.database.schema import auto_extract_schema
from src.llm.agent import (
    auto_fix_chocolates_sales_crm_tickets_query,
    auto_fix_sales_headcount_query,
    run_agent,
)
from src.llm.datamate_bridge import (
    detect_legacy_schema_gap,
    has_headcount_qualifier_conflict,
)
from src.llm.evaluator import evaluate_execution
from src.llm.few_shot_selector import select_dynamic_few_shots
from src.llm.prompts import get_db_specific_rules, get_targeted_hint


class _QueuedOpenAIClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("LLM was called unexpectedly when preflight/evaluator guard should block.")
        content = self._responses.pop(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


class TestUnanswerableGuardrails(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.demo_engine = build_demo_engine()
        cls.demo_schema = auto_extract_schema(cls.demo_engine)
        cls.employees_schema = (
            "Cơ sở dữ liệu nhân sự:\n"
            "- Bảng `employees`: emp_no, birth_date, first_name, last_name, gender, hire_date\n"
            "- Bảng `departments`: dept_no, dept_name\n"
            "- Bảng `dept_emp`: emp_no, dept_no, from_date, to_date\n"
            "- Bảng `salaries`: emp_no, salary, from_date, to_date\n"
            "- Bảng `titles`: emp_no, title, from_date, to_date"
        )
        cls.yen_sao_schema = (
            "Cơ sở dữ liệu bán hàng:\n"
            "- Bảng `san_pham`: id, ten_sp, loai, gia_ban, gia_von, ton_kho\n"
            "- Bảng `khach_hang`: id, ten_kh, so_dien_thoai, khu_vuc\n"
            "- Bảng `don_hang`: id, khach_hang_id, ngay_dat, kenh_ban, tong_tien, con_no, trang_thai"
        )
        cls.sakila_schema = (
            "Cơ sở dữ liệu thuê phim:\n"
            "- Bảng `film`: film_id, title, rental_rate, rating\n"
            "- Bảng `rental`: rental_id, rental_date, return_date, customer_id\n"
            "- Bảng `payment`: payment_id, amount, payment_date"
        )

    @classmethod
    def tearDownClass(cls) -> None:
        # build_demo_engine() is @st.cache_resource shared across tests; do not dispose its StaticPool in-memory DB.
        pass

    def test_attrition_query_blocked_across_all_layers_on_awesome_chocolates(self) -> None:
        query = "có bao nhiêu nhân viên nghỉ việc"

        # Layer 1: Schema capability guard catches missing HR termination/status columns (ignoring crm_tickets.Status)
        gap = detect_legacy_schema_gap(
            query,
            engine=self.demo_engine,
            schema_context=self.demo_schema,
            lang="vi",
        )
        self.assertIsNotNone(gap)

        # Layer 2: Prompt hint & headcount auto-fix must NOT hijack to GROUP BY pe.Team
        self.assertTrue(has_headcount_qualifier_conflict(query))
        self.assertEqual(get_targeted_hint(query, self.demo_schema, dialect="SQLite"), "")
        raw_sql = "SELECT COUNT(*) AS ResignedCount FROM people"
        self.assertEqual(auto_fix_sales_headcount_query(raw_sql, query, dialect="SQLite"), raw_sql)

        # Layer 3: End-to-end run_agent blocks BEFORE calling LLM
        client = _QueuedOpenAIClient([])
        res = run_agent(
            user_query=query,
            client=client,
            provider="Ollama (Local AI Offline)",
            model_name="qwen2.5-coder:3b",
            engine=self.demo_engine,
            schema_context=self.demo_schema,
            dialect="SQLite",
            lang="vi",
        )
        self.assertEqual(len(client.calls), 0)
        self.assertIsNone(res.get("sql"))
        self.assertIsNone(res.get("df"))
        self.assertIn("🛡️", res.get("explanation", ""))
        self.assertEqual((res.get("evaluator") or {}).get("verdict"), "UNANSWERABLE_BLOCKED")
        self.assertTrue(res.get("followups"))

        # Layer 4: Evaluator directly blocks hallucinated GROUP BY pe.Team result
        fake_df = pd.DataFrame({"Team": ["Delish", "Yummies", "Jucies"], "EmployeeCount": [9, 5, 3]})
        ev = evaluate_execution(
            user_query=query,
            sql_query="SELECT pe.Team, COUNT(DISTINCT pe.SPID) AS EmployeeCount FROM people pe GROUP BY pe.Team",
            df=fake_df,
            schema_context=self.demo_schema,
            lang="vi",
        )
        self.assertEqual(ev.get("verdict"), "UNANSWERABLE_BLOCKED")
        self.assertEqual(ev.get("score"), 0)

    def test_other_missing_concepts_blocked_on_awesome_chocolates(self) -> None:
        unanswerable_queries = [
            "nhân viên có hoa hồng cao nhất",
            "mức lương trung bình của nhân viên",
            "có bao nhiêu nhân viên vào làm năm 2021",
            "số lượng nhân viên nghỉ phép trong tháng",
            "có bao nhiêu nhân viên đang thử việc",
            "thời gian giao hàng trung bình theo từng khu vực",
            "danh sách số điện thoại khách hàng",
            "chi phí marketing và tỷ lệ ROAS theo từng tháng",
            "tổng tiền thuế VAT phải nộp theo quốc gia",
            "tỷ lệ khách hàng rời bỏ (churn rate) theo năm",
            "trình độ học vấn của đội ngũ bán hàng",
        ]
        for q in unanswerable_queries:
            with self.subTest(query=q):
                gap = detect_legacy_schema_gap(
                    q,
                    engine=self.demo_engine,
                    schema_context=self.demo_schema,
                    lang="vi",
                )
                self.assertIsNotNone(gap, f"Expected schema gap block for: {q}")
                self.assertEqual(
                    get_targeted_hint(q, self.demo_schema, dialect="SQLite"),
                    "",
                    f"Expected empty targeted hint for unanswerable query: {q}",
                )

    def test_evaluator_short_circuit_and_multiline_unanswerable_extraction(self) -> None:
        # 1. If preflight detect_legacy_schema_gap were bypassed in run_agent, Evaluator must catch & short-circuit to UNANSWERABLE_BLOCKED
        client_fake_sql = _QueuedOpenAIClient(
            [
                "SELECT pe.Team, COUNT(DISTINCT pe.SPID) AS EmployeeCount FROM people pe WHERE pe.Team != '' GROUP BY pe.Team",
            ]
        )
        with mock.patch("src.llm.datamate_bridge.detect_legacy_schema_gap", return_value=None):
            res = run_agent(
                user_query="có bao nhiêu nhân viên nghỉ việc",
                client=client_fake_sql,
                provider="Ollama (Local AI Offline)",
                model_name="qwen2.5-coder:3b",
                engine=self.demo_engine,
                schema_context=self.demo_schema,
                dialect="SQLite",
                lang="vi",
            )
        self.assertIsNone(res.get("df"))
        self.assertIsNone(res.get("sql"))
        self.assertEqual((res.get("evaluator") or {}).get("verdict"), "UNANSWERABLE_BLOCKED")
        self.assertIn("🛡️", res.get("explanation", ""))
        self.assertLessEqual(len(client_fake_sql.calls), 1)

        # 2. Multi-line UNANSWERABLE response on unseen missing concept extracts cleanly
        client_multiline = _QueuedOpenAIClient(
            [
                "Dữ liệu không có cột phù hợp.\nUNANSWERABLE: Bảng sales không lưu mã bưu chính (ZipCode).",
            ]
        )
        res_ml = run_agent(
            user_query="Thống kê doanh thu theo mã bưu chính ZipCode của khách hàng?",
            client=client_multiline,
            provider="Ollama (Local AI Offline)",
            model_name="qwen2.5-coder:3b",
            engine=self.demo_engine,
            schema_context=self.demo_schema,
            dialect="SQLite",
            lang="vi",
        )
        self.assertIsNone(res_ml.get("df"))
        self.assertIsNone(res_ml.get("sql"))
        self.assertEqual((res_ml.get("evaluator") or {}).get("verdict"), "UNANSWERABLE_BLOCKED")
        self.assertIn("ZipCode", res_ml.get("explanation", ""))

        # 3. Employees DB WITH to_date must FAIL if generated SQL drops to_date filter on attrition query
        ev_emp_drop = evaluate_execution(
            user_query="Có bao nhiêu nhân viên nghỉ việc?",
            sql_query="SELECT COUNT(*) AS Cnt FROM employees",
            df=pd.DataFrame({"Cnt": [300024]}),
            schema_context=self.employees_schema,
            lang="vi",
        )
        self.assertEqual(ev_emp_drop.get("verdict"), "FAIL")
        self.assertFalse(ev_emp_drop["criteria"]["semantic_alignment"]["passed"])

        # 4. Arbitrary ungrounded staff attribute ('sở hữu xe công ty') must NOT get hijacked & MUST be blocked
        car_q = "tỷ lệ nhân viên sở hữu xe công ty là bao nhiêu"
        self.assertTrue(has_headcount_qualifier_conflict(car_q))
        self.assertEqual(get_targeted_hint(car_q, self.demo_schema, dialect="SQLite"), "")
        car_raw_sql = "SELECT COUNT(*) FROM people"
        self.assertEqual(auto_fix_sales_headcount_query(car_raw_sql, car_q, dialect="SQLite"), car_raw_sql)
        cli_car = _QueuedOpenAIClient(
            ["SELECT pe.Team, COUNT(DISTINCT pe.SPID) AS Cnt FROM people pe WHERE pe.Team != '' GROUP BY pe.Team"]
        )
        res_car = run_agent(
            user_query=car_q,
            client=cli_car,
            provider="Ollama (Local AI Offline)",
            model_name="qwen2.5-coder:3b",
            engine=self.demo_engine,
            schema_context=self.demo_schema,
            dialect="SQLite",
            lang="vi",
        )
        self.assertIsNone(res_car.get("df"))
        self.assertIsNone(res_car.get("sql"))
        self.assertEqual((res_car.get("evaluator") or {}).get("verdict"), "UNANSWERABLE_BLOCKED")
        self.assertIn("🛡️", res_car.get("explanation", ""))

    def test_zero_false_positives_on_valid_schemas(self) -> None:
        # 1. Valid Awesome Chocolates queries MUST pass schema guard
        valid_choco_queries = [
            "Mỗi đội ngũ (Team) có bao nhiêu nhân viên, đóng góp tổng doanh thu và số hộp là bao nhiêu?",
            "Số lượng nhân viên theo từng Đội ngũ (Team) là bao nhiêu?",
            "Thống kê số lượng ticket theo Kênh hỗ trợ (Email, Phone) và thời gian phản hồi đầu tiên",
            "Tính doanh thu và lợi nhuận ước tính (Amount - Boxes * Cost_per_box) theo từng Category",
            "Đơn hàng có sản lượng và số lượng hộp cao nhất ở từng quốc gia",
        ]
        for q in valid_choco_queries:
            with self.subTest(choco_query=q):
                self.assertIsNone(
                    detect_legacy_schema_gap(
                        q,
                        engine=self.demo_engine,
                        schema_context=self.demo_schema,
                        lang="vi",
                    )
                )

        # Headcount by Team still keeps targeted hint & auto-fix on pure team headcount questions
        pure_team_q = "Mỗi đội ngũ (Team) có bao nhiêu nhân viên?"
        self.assertFalse(has_headcount_qualifier_conflict(pure_team_q))
        self.assertIn("pe.team", get_targeted_hint(pure_team_q, self.demo_schema, dialect="SQLite").lower())

        # 2. Employees DB (supports to_date, hire_date, salary, gender, birth_date) MUST pass
        valid_emp_queries = [
            "Có bao nhiêu nhân viên nghỉ việc?",
            "Tỷ lệ nhân sự nghỉ việc theo từng phòng ban?",
            "Thống kê nhân viên vào làm từ năm 1995 và mức lương trung bình theo giới tính",
        ]
        for q in valid_emp_queries:
            with self.subTest(emp_query=q):
                self.assertIsNone(
                    detect_legacy_schema_gap(q, schema_context=self.employees_schema, lang="vi")
                )

        # 3. Yen Sao DB supports ton_kho and so_dien_thoai, while don_hang.trang_thai must NOT pass HR attrition!
        self.assertIsNone(
            detect_legacy_schema_gap(
                "Thống kê sản phẩm sắp hết tồn kho", schema_context=self.yen_sao_schema, lang="vi"
            )
        )
        self.assertIsNone(
            detect_legacy_schema_gap(
                "Danh sách số điện thoại khách hàng còn công nợ", schema_context=self.yen_sao_schema, lang="vi"
            )
        )
        self.assertIsNotNone(
            detect_legacy_schema_gap(
                "Có bao nhiêu nhân viên nghỉ việc", schema_context=self.yen_sao_schema, lang="vi"
            )
        )

        # 4. Sakila film rental ('thuê') must NOT collide with tax ('thuế')
        self.assertIsNone(
            detect_legacy_schema_gap(
                "Top 10 bộ phim được thuê nhiều nhất và tiền thuê cao nhất",
                schema_context=self.sakila_schema,
                lang="vi",
            )
        )

    def test_datamate_workspace_preflight_attrition(self) -> None:
        def _make_know(table_cols: dict[str, list[str]]) -> WorkspaceKnowledge:
            tables = {}
            for tname, cols in table_cols.items():
                tables[tname] = TableProfile(
                    table_name=tname,
                    raw_name=tname,
                    source_files=[f"{tname}.csv"],
                    row_count=5,
                    columns=[
                        ColumnProfile(raw_name=c, sql_name=c, inferred_type="text", null_count=0, distinct_count=2)
                        for c in cols
                    ],
                    raw_to_sql={c: c for c in cols},
                )
            ws = BusinessWorkspace(
                business_id="test_ws",
                business_dir=pathlib.Path("."),
                db_path=pathlib.Path("test_ws.sqlite"),
                readme_text="",
                tables=tables,
                source_kind="tabular_files",
            )
            return WorkspaceKnowledge(
                workspace=ws,
                schema_prompt="",
                table_date_ranges={},
                data_min_date=None,
                data_max_date=None,
                capabilities={},
                categorical_values={},
                valid_tables=list(table_cols.keys()),
            )

        q_hr_ws = "có bao nhiêu nhân viên nghỉ việc"
        a_hr_ws = classify_expected_type(q_hr_ws)

        wk_choco = _make_know(
            {
                "people": ["SPID", "Salesperson", "Team", "Location"],
                "sales": ["SPID", "GeoID", "PID", "SaleDate", "Amount", "Boxes"],
                "crm_tickets": ["TicketID", "Status", "CreatedAt"],
            }
        )
        blocked_msg = check_preflight_unanswerable(q_hr_ws, "2026-10-05", wk_choco, a_hr_ws)
        self.assertIsNotNone(blocked_msg)

        wk_hr = _make_know(
            {
                "employees": ["emp_no", "hire_date", "gender"],
                "dept_emp": ["emp_no", "dept_no", "from_date", "to_date"],
            }
        )
        self.assertIsNone(check_preflight_unanswerable(q_hr_ws, "2026-10-05", wk_hr, a_hr_ws))

    def test_cross_domain_sales_crm_and_fail_closed_auditor_gate(self) -> None:
        cross_q = (
            "Trong năm 2023, quốc gia (Geo) nào có doanh thu cao nhất "
            "nhưng đồng thời ghi nhận bao nhiêu ticket loại Bug?"
        )

        # 1. Cross-domain rules, targeted hint & few-shot selection must prioritize 2-CTE CRM+Sales
        rules = get_db_specific_rules(self.demo_schema, user_query=cross_q)
        self.assertLess(len(rules), 2500)
        self.assertIn("SalesAgg", rules)
        self.assertIn("TicketAgg", rules)

        hint = get_targeted_hint(cross_q, self.demo_schema, dialect="SQLite")
        self.assertIn("SalesAgg", hint)
        self.assertIn("TicketAgg", hint)
        self.assertIn("2023", hint)
        self.assertIn("Bug", hint)
        self.assertIn("LIMIT 1", hint)

        shots = select_dynamic_few_shots(
            cross_q, schema_context=self.demo_schema, dialect="SQLite", top_k=2
        )
        self.assertTrue(shots)
        self.assertEqual(shots[0]["id"], "choco_country_revenue_and_bug_tickets_2023")

        # 2. Evaluator must reject drifted Top-5 2021 Products SQL, raw Cartesian joins, and missing Bug filter
        drifted_sql = (
            "SELECT pr.Product, SUM(s.Amount) AS TotalSales "
            "FROM sales s JOIN products pr ON s.PID = pr.PID "
            "WHERE strftime('%Y', s.SaleDate) = '2021' "
            "GROUP BY pr.Product ORDER BY TotalSales DESC LIMIT 5"
        )
        drifted_df = pd.DataFrame({"Product": ["70% Dark Bites", "Eclairs"], "TotalSales": [587379, 580000]})
        ev_drift = evaluate_execution(cross_q, drifted_sql, drifted_df, self.demo_schema, lang="vi")
        self.assertEqual(ev_drift.get("verdict"), "FAIL")
        self.assertFalse(ev_drift["criteria"]["semantic_alignment"]["passed"])
        self.assertFalse(ev_drift["criteria"]["temporal_validity"]["passed"])
        self.assertFalse(ev_drift["criteria"]["comparative_sufficiency"]["passed"])

        cartesian_sql = (
            "SELECT g.Geo, SUM(s.Amount) AS TotalSales, COUNT(DISTINCT t.TicketID) AS BugTickets "
            "FROM sales s JOIN geo g ON s.GeoID = g.GeoID "
            "JOIN crm_tickets t ON g.GeoID = t.GeoID "
            "WHERE t.Type = 'Bug' AND strftime('%Y', s.SaleDate) = '2023' "
            "GROUP BY g.Geo ORDER BY TotalSales DESC LIMIT 1"
        )
        ev_cart = evaluate_execution(
            cross_q,
            cartesian_sql,
            pd.DataFrame({"Geo": ["Australia"], "TotalSales": [1854356], "BugTickets": [55]}),
            self.demo_schema,
            lang="vi",
        )
        self.assertFalse(ev_cart["criteria"]["semantic_alignment"]["passed"])

        no_bug_sql = (
            "WITH SalesAgg AS (SELECT GeoID, SUM(Amount) AS TotalSales FROM sales WHERE strftime('%Y', SaleDate) = '2023' GROUP BY GeoID), "
            "TicketAgg AS (SELECT GeoID, COUNT(DISTINCT TicketID) AS BugTickets FROM crm_tickets WHERE strftime('%Y', CreatedAt) = '2023' GROUP BY GeoID) "
            "SELECT g.Geo, sa.TotalSales, ta.BugTickets FROM geo g JOIN SalesAgg sa ON g.GeoID = sa.GeoID LEFT JOIN TicketAgg ta ON g.GeoID = ta.GeoID "
            "ORDER BY sa.TotalSales DESC LIMIT 1"
        )
        ev_nobug = evaluate_execution(
            cross_q,
            no_bug_sql,
            pd.DataFrame({"Geo": ["Australia"], "TotalSales": [1854356], "BugTickets": [200]}),
            self.demo_schema,
            lang="vi",
        )
        self.assertFalse(ev_nobug["criteria"]["semantic_alignment"]["passed"])

        valid_sql = (
            "WITH SalesAgg AS ("
            "SELECT s.GeoID, SUM(s.Amount) AS TotalSales FROM sales s "
            "WHERE strftime('%Y', s.SaleDate) = '2023' GROUP BY s.GeoID), "
            "TicketAgg AS ("
            "SELECT t.GeoID, COUNT(DISTINCT t.TicketID) AS BugTickets FROM crm_tickets t "
            "WHERE t.Type = 'Bug' AND strftime('%Y', t.CreatedAt) = '2023' GROUP BY t.GeoID) "
            "SELECT g.Geo AS Country, sa.TotalSales, ta.BugTickets "
            "FROM geo g JOIN SalesAgg sa ON g.GeoID = sa.GeoID "
            "LEFT JOIN TicketAgg ta ON g.GeoID = ta.GeoID "
            "ORDER BY sa.TotalSales DESC LIMIT 1"
        )
        df_valid = pd.read_sql_query(valid_sql, self.demo_engine)
        self.assertEqual(len(df_valid), 1)
        self.assertEqual(df_valid.iloc[0]["Country"], "Australia")
        self.assertEqual(int(df_valid.iloc[0]["TotalSales"]), 1854356)
        self.assertEqual(int(df_valid.iloc[0]["BugTickets"]), 55)
        ev_valid = evaluate_execution(cross_q, valid_sql, df_valid, self.demo_schema, lang="vi")
        self.assertEqual(ev_valid.get("verdict"), "PASS")
        self.assertEqual(ev_valid.get("score"), 100)

        # 3. Domain auto-fix must preserve CustomerID CRM+sales queries and repair drifted cross-domain SQL
        cust_sql = "SELECT s.CustomerID, SUM(s.Amount) AS Rev FROM sales s LEFT JOIN crm_tickets t ON s.CustomerID = t.CustomerID GROUP BY s.CustomerID"
        self.assertEqual(
            auto_fix_chocolates_sales_crm_tickets_query(
                cust_sql, "Top 5 khách hàng CustomerID từng gửi ticket?", self.demo_schema, dialect="SQLite"
            ),
            cust_sql,
        )
        repaired_sql = auto_fix_chocolates_sales_crm_tickets_query(
            drifted_sql, cross_q, self.demo_schema, dialect="SQLite"
        )
        df_repaired = pd.read_sql_query(repaired_sql, self.demo_engine)
        self.assertEqual(df_repaired.iloc[0]["Country"], "Australia")
        self.assertEqual(int(df_repaired.iloc[0]["BugTickets"]), 55)

        # 4. Fail-Closed Auditor Gate: persistent semantic+temporal drift across all 3 attempts must NOT leak wrong df
        wrong_prod_2021_sql = (
            "SELECT pr.Product, SUM(s.Amount) AS TotalSales "
            "FROM sales s JOIN products pr ON s.PID = pr.PID "
            "WHERE strftime('%Y', s.SaleDate) = '2021' GROUP BY pr.Product"
        )
        client_stubborn_drift = _QueuedOpenAIClient([wrong_prod_2021_sql] * 6)
        with mock.patch("src.llm.datamate_bridge.detect_legacy_schema_gap", return_value=None):
            res_fail_closed = run_agent(
                user_query="Trong năm 2023, doanh thu theo từng Quốc gia (Geo) là bao nhiêu?",
                client=client_stubborn_drift,
                provider="Ollama (Local AI Offline)",
                model_name="qwen2.5-coder:3b",
                engine=self.demo_engine,
                schema_context=self.demo_schema,
                dialect="SQLite",
                lang="vi",
            )
        self.assertIsNone(res_fail_closed.get("df"))
        self.assertEqual((res_fail_closed.get("evaluator") or {}).get("verdict"), "FAIL")
        self.assertIn("🛡️", res_fail_closed.get("explanation", ""))
        self.assertTrue(res_fail_closed.get("followups"))

    def test_vietnamese_homographs_and_classic_northwind_schema_handling(self) -> None:
        from sqlalchemy import create_engine, text as sa_text
        from src.llm.prompts import extract_tables_from_schema

        nw_eng = create_engine("sqlite:///:memory:")
        try:
            with nw_eng.begin() as conn:
                conn.execute(sa_text('CREATE TABLE Categories (CategoryID INT, CategoryName TEXT, Description TEXT)'))
                conn.execute(sa_text('CREATE TABLE Customers (CustomerID TEXT, CompanyName TEXT, ContactName TEXT, Country TEXT)'))
                conn.execute(sa_text('CREATE TABLE Orders (OrderID INT, CustomerID TEXT, EmployeeID INT, OrderDate TEXT)'))
                conn.execute(sa_text('CREATE TABLE "Order Details" (OrderID INT, ProductID INT, UnitPrice REAL, Quantity INT, Discount REAL)'))
                conn.execute(sa_text('CREATE TABLE Products (ProductID INT, ProductName TEXT, CategoryID INT, UnitPrice REAL)'))
                conn.execute(sa_text('CREATE TABLE Employees (EmployeeID INT, FirstName TEXT, LastName TEXT)'))
                conn.execute(sa_text('CREATE TABLE Suppliers (SupplierID INT, CompanyName TEXT)'))
            nw_schema = auto_extract_schema(nw_eng)

            # 1. Vietnamese "các" and "vật" must NOT false-trigger CAC marketing or VAT invoice blocks
            self.assertIsNone(
                detect_legacy_schema_gap(
                    "Thống kê tổng quan các chỉ số chính của bảng Categories",
                    engine=nw_eng,
                    schema_context=nw_schema,
                    lang="vi",
                )
            )
            self.assertIsNone(
                detect_legacy_schema_gap(
                    "Tổng tiền vật liệu theo từng khách hàng là bao nhiêu?",
                    engine=nw_eng,
                    schema_context=nw_schema,
                    lang="vi",
                )
            )

            # 2. Classic Northwind tables with spaces must be parsed and receive Classic SQLite rules
            extracted = extract_tables_from_schema(nw_schema)
            self.assertIn("order details", extracted)
            self.assertIn("categories", extracted)
            rules = get_db_specific_rules(nw_schema, user_query="Thống kê bảng Categories")
            self.assertIn('"Order Details"', rules)
            self.assertNotIn("p.category,", rules.lower())
        finally:
            nw_eng.dispose()

    def test_geo_city_blocked_on_cafe_pho_viet_but_allowed_on_chocolates(self) -> None:
        from datamate.agent import check_preflight_unanswerable, classify_expected_type
        from src.database.business_upload import build_datamate_workspace_engine, compose_connection_schema

        cafe_dir = PROJECT_ROOT / "data" / "demo_businesses" / "cafe_pho_viet"
        eng, know = build_datamate_workspace_engine(cafe_dir)
        try:
            schema = compose_connection_schema(auto_extract_schema(eng, force_refresh=True), "", know)
            q = "Tỷ lệ đóng góp đơn giá của từng thành phố vào tổng số"
            gap = detect_legacy_schema_gap(q, engine=eng, schema_context=schema, lang="vi")
            self.assertIsNotNone(gap)
            self.assertIn("địa bàn", gap)

            pre = check_preflight_unanswerable(q, know.data_max_date or "2026-10-06", know, classify_expected_type(q))
            self.assertIsNotNone(pre)
            self.assertIn("thành phố", pre)

            # Demo DB with geo/Location must still allow geographic breakdown queries
            self.assertIsNone(
                detect_legacy_schema_gap(
                    "Doanh thu theo từng thành phố hoặc quốc gia?",
                    engine=self.demo_engine,
                    schema_context=self.demo_schema,
                    lang="vi",
                )
            )

            # Weather / general non-business / named city queries must be blocked across all layers
            from src.analytics.heuristics import is_non_data_conversational
            for oos_q in (
                "Hà Nội hôm nay có mưa không",
                "ha noi hom nay co mua khong",
                "Thời tiết Hà Nội hôm nay có mưa không?",
                "Hnay nhiệt độ cao nhất là bao nhiêu?",
                "Giá vàng hôm nay bao nhiêu?",
            ):
                self.assertTrue(is_non_data_conversational(oos_q, schema_context=schema), msg=oos_q)
                self.assertIsNotNone(
                    check_preflight_unanswerable(oos_q, know.data_max_date or "2026-10-06", know, classify_expected_type(oos_q)),
                    msg=oos_q,
                )
                self.assertIsNotNone(
                    detect_legacy_schema_gap(oos_q, engine=eng, schema_context=schema, lang="vi"),
                    msg=oos_q,
                )
                res_dm = run_agent(
                    user_query=oos_q,
                    client=_QueuedOpenAIClient(['{"status": "ok", "sql": "SELECT COUNT(*) FROM donhang"}']),
                    provider="Ollama (Local AI Offline)",
                    model_name="qwen2.5-coder:3b",
                    engine=eng,
                    schema_context=schema,
                    dialect="SQLite",
                    lang="vi",
                    datamate_knowledge=know,
                )
                self.assertIsNone(res_dm.get("sql"), msg=oos_q)
                self.assertIsNone(res_dm.get("df"), msg=oos_q)
                self.assertEqual((res_dm.get("evaluator") or {}).get("verdict"), "UNANSWERABLE_BLOCKED", msg=oos_q)

            # Named city business query on cafe_pho_viet (no geo/city column) must also be blocked
            city_biz_q = "Doanh thu tại Hà Nội hôm nay là bao nhiêu?"
            self.assertIsNotNone(
                check_preflight_unanswerable(city_biz_q, know.data_max_date or "2026-10-06", know, classify_expected_type(city_biz_q))
            )

            # Valid 'mua' (buy) business query on cafe_pho_viet must NOT be misclassified as weather 'mưa'
            buy_q = "Hôm nay có đơn hàng nào mua cà phê không?"
            self.assertFalse(is_non_data_conversational(buy_q, schema_context=schema))
            self.assertIsNone(
                check_preflight_unanswerable(buy_q, know.data_max_date or "2026-10-06", know, classify_expected_type(buy_q))
            )
        finally:
            eng.dispose()

    def test_scalar_multi_kpi_insight_does_not_treat_number_as_entity(self) -> None:
        import pandas as pd
        from src.analytics.heuristics import (
            extract_selectable_units,
            generate_hypothesis_tree,
            generate_persona_action_plan,
            select_primary_insight_columns,
            split_insight_sections,
        )
        from src.visualization.charts import format_col_title

        df = pd.DataFrame([{"tong_doanh_thu": 1262000, "so_don_ho_le": 9}])
        q = "Tổng Doanh Thu và số đơn hợp lệ trong tháng 10/2026 là bao nhiêu?"

        val_col, name_col = select_primary_insight_columns(df, q)
        self.assertEqual(val_col, "tong_doanh_thu")
        self.assertIsNone(name_col)

        self.assertEqual(format_col_title("so_don_ho_le"), "Số Đơn Hợp Lệ")
        self.assertEqual(format_col_title("so_don_hop_le"), "Số Đơn Hợp Lệ")

        sections = split_insight_sections("", df, user_query=q, is_en=False)
        for sec in (sections["anomaly"], sections["hypothesis"], sections["action_plan"]):
            self.assertNotIn("Thực thể Trọng tâm: **1262000**", sec)
            self.assertNotIn("Thực thể Trọng tâm: 1262000", sec)
        self.assertIn("Tổng Doanh Thu", sections["anomaly"])
        self.assertIn("Số Đơn Hợp Lệ", sections["anomaly"])
        self.assertIn("140,222 đ/đơn", sections["anomaly"])
        self.assertNotIn(r"\$", sections["anomaly"])

        ht = generate_hypothesis_tree(df, user_query=q, is_en=False)
        self.assertEqual(ht["top_entity"], "Tổng Doanh Thu")
        self.assertNotIn("'1262000'", ht["problem_statement"])
        self.assertNotIn("'1262000'", ht["conclusion"])
        self.assertIn("Tổng Doanh Thu", ht["problem_statement"])

        units_info = extract_selectable_units(df, user_query=q, is_en=False)
        self.assertFalse(units_info["has_units"])
        self.assertEqual(units_info["unit_options"], [])
        self.assertIsNone(units_info["unit_col"])

        plan = generate_persona_action_plan(
            df,
            persona="ceo",
            user_query=q,
            is_en=False,
        )
        plan_str = str(plan)
        self.assertNotIn("Tỷ trọng dẫn đầu (1262000)", plan_str)
        self.assertNotIn("Mũi nhọn: 1262000", plan_str)
        self.assertNotIn("Vùng cần nâng: 1262000", plan_str)
        self.assertIn("Tổng Doanh Thu", plan_str)
        self.assertIn("Số Đơn Hợp Lệ", plan_str)

    def test_ordinal_rank_third_product_with_revenue_on_cafe_pho_viet(self) -> None:
        from unittest.mock import patch
        from datamate.agent import classify_expected_type, extract_ordinal_rank, rewrite_ranked_entity_sql
        from src.database.business_upload import build_datamate_workspace_engine
        from src.llm.datamate_bridge import run_datamate_enhanced_turn
        from src.visualization.charts import format_col_title

        q = "Sản phẩm có doanh thu cao thứ 3 là sản phẩm nào"
        self.assertEqual(extract_ordinal_rank(q), (3, "DESC"))
        self.assertEqual(extract_ordinal_rank("Món bán chạy thứ 2 là món nào"), (2, "DESC"))
        self.assertEqual(extract_ordinal_rank("Sản phẩm có doanh thu thấp thứ 2"), (2, "ASC"))
        self.assertIsNone(extract_ordinal_rank("Doanh thu ngày thứ 3 tuần trước là bao nhiêu"))
        self.assertIsNone(extract_ordinal_rank("Top 3 sản phẩm có doanh thu cao nhất"))

        self.assertEqual(classify_expected_type(q).expected_type, "string")
        self.assertEqual(format_col_title("ten_mon"), "Tên Món")
        self.assertEqual(format_col_title("tong_doanh_thu"), "Tổng Doanh Thu ($)")

        raw_bad_sql = (
            "SELECT ten_mon FROM donhang WHERE trang_thai = 'Hoàn thành' "
            "GROUP BY ten_mon ORDER BY SUM(thanh_tien) DESC LIMIT 3"
        )
        rewritten = rewrite_ranked_entity_sql(raw_bad_sql, q, use_round_half_up=True)
        self.assertIn("ROUND_HALF_UP(SUM(thanh_tien), 0) AS tong_doanh_thu", rewritten)
        self.assertIn("LIMIT 1 OFFSET 2", rewritten)

        eng, know = build_datamate_workspace_engine(PROJECT_ROOT / "data" / "demo_businesses" / "cafe_pho_viet")
        try:
            with patch(
                "src.llm.datamate_bridge.VeraxusClientLLMBackend.generate",
                return_value='{"status": "ok", "sql": "' + raw_bad_sql + '"}',
            ):
                res = run_datamate_enhanced_turn(
                    user_query=q,
                    client=object(),
                    provider="Ollama (Local AI Offline)",
                    model_name="qwen2.5-coder:3b",
                    knowledge=know,
                    lang="vi",
                )
            df = res.get("df")
            self.assertIsNotNone(df)
            self.assertEqual(len(df), 1)
            self.assertEqual(list(df.columns), ["ten_mon", "tong_doanh_thu"])
            self.assertEqual(df.iloc[0]["ten_mon"], "Bạc xỉu")
            self.assertEqual(int(df.iloc[0]["tong_doanh_thu"]), 195000)
            self.assertIn("Bạc xỉu", res.get("explanation", ""))
            self.assertIn("195.000 VNĐ", res.get("explanation", ""))
        finally:
            eng.dispose()

    def test_missing_staff_and_gender_blocked_on_pos_databases(self) -> None:
        from datamate.agent import check_preflight_unanswerable, classify_expected_type, verify_sql_semantics
        from datamate.sql_executor import SQLExecutionResult
        from src.database.business_upload import build_datamate_workspace_engine, compose_connection_schema

        eng, know = build_datamate_workspace_engine(PROJECT_ROOT / "data" / "demo_businesses" / "cafe_pho_viet")
        try:
            self.assertFalse(know.capabilities["has_staff"])
            self.assertFalse(know.capabilities["has_customer_gender"])
            schema = compose_connection_schema(auto_extract_schema(eng, force_refresh=True), "", know)

            for q in (
                "Có bao nhiêu nhân viên nữ?",
                "Có bao nhiêu nhân viên?",
                "Nhân viên nào bán chạy nhất?",
                "Mức lương trung bình của nhân viên là bao nhiêu?",
                "Khách hàng nữ mua cà phê nhiều nhất?",
            ):
                with self.subTest(blocked_query=q):
                    pre = check_preflight_unanswerable(q, know.data_max_date or "2026-10-06", know, classify_expected_type(q))
                    self.assertIsNotNone(pre)

                    # Even if preflight were skipped, verify_sql_semantics rejects substituted COUNT(*) FROM donhang!
                    dummy = SQLExecutionResult(ok=True, sql="", columns=["COUNT(*)"], rows=[(9,)], row_count=1)
                    sem_ok, sem_msg, sem_fatal = verify_sql_semantics(
                        "SELECT COUNT(*) FROM donhang WHERE trang_thai = 'Hoàn thành'",
                        dummy,
                        q,
                        know,
                        classify_expected_type(q),
                    )
                    self.assertFalse(sem_ok)
                    self.assertTrue(sem_fatal)
                    self.assertTrue(sem_msg)

                    # Legacy gap detector must also catch it
                    self.assertIsNotNone(detect_legacy_schema_gap(q, engine=eng, schema_context=schema, lang="vi"))

                    # End-to-end DataMate run_agent must block cleanly without invoking SQL
                    res_dm = run_agent(
                        user_query=q,
                        client=_QueuedOpenAIClient(['{"status": "ok", "sql": "SELECT COUNT(*) FROM donhang"}']),
                        provider="Ollama (Local AI Offline)",
                        model_name="qwen2.5-coder:3b",
                        engine=eng,
                        schema_context=schema,
                        dialect="SQLite",
                        lang="vi",
                        datamate_knowledge=know,
                    )
                    self.assertIsNone(res_dm.get("df"))
                    self.assertIsNone(res_dm.get("sql"))
                    self.assertEqual((res_dm.get("evaluator") or {}).get("verdict"), "UNANSWERABLE_BLOCKED")

            # Valid cafe revenue query mentioning 'năm' or 'số lượng' must NOT false-trigger staff/gender/salary
            for valid_q in (
                "Doanh thu và số lượng bán năm 2026 là bao nhiêu?",
                "Sản phẩm có doanh thu cao thứ 3 là sản phẩm nào",
            ):
                self.assertIsNone(
                    check_preflight_unanswerable(
                        valid_q,
                        know.data_max_date or "2026-10-06",
                        know,
                        classify_expected_type(valid_q),
                    ),
                    msg=valid_q,
                )
        finally:
            eng.dispose()

        # On Employees DB (has gender column), asking about female employees MUST pass legacy gap check
        self.assertIsNone(
            detect_legacy_schema_gap("Có bao nhiêu nhân viên nữ?", schema_context=self.employees_schema, lang="vi")
        )
        # On Awesome Chocolates (has people/Salesperson but NO gender column), asking female employees MUST block
        self.assertIsNotNone(
            detect_legacy_schema_gap(
                "Có bao nhiêu nhân viên nữ?",
                engine=self.demo_engine,
                schema_context=self.demo_schema,
                lang="vi",
            )
        )

    def test_datamate_followups_contextual_and_db_grounded_across_businesses(self) -> None:
        from datamate.agent import (
            check_out_of_scope_or_irrelevant,
            check_preflight_unanswerable,
            classify_expected_type,
        )
        from src.database.business_upload import build_datamate_workspace_engine
        from src.llm.datamate_bridge import build_datamate_suggested_questions

        legacy_static = {
            "Tổng Doanh Thu và số đơn hợp lệ trong tháng 10/2026 là bao nhiêu?",
            "Ngày nào có Doanh Thu cao nhất trong tháng 10/2026?",
        }

        # 1. Pharmacy DB (nha_thuoc_an_tam): follow-ups after top medicine revenue query
        eng_nt, know_nt = build_datamate_workspace_engine(PROJECT_ROOT / "data" / "demo_businesses" / "nha_thuoc_an_tam")
        try:
            df_nt = pd.DataFrame(
                [
                    {"ten_thuoc": "Panadol Extra", "doanh_thu": 540000},
                    {"ten_thuoc": "Vitamin C 500mg", "doanh_thu": 475000},
                    {"ten_thuoc": "Nước muối sinh lý", "doanh_thu": 120000},
                ]
            )
            q_nt = "Top 10 loại thuốc có tổng doanh thu cao nhất"
            f_nt = build_datamate_suggested_questions(know_nt, lang="vi", user_query=q_nt, df=df_nt)
            self.assertGreaterEqual(len(f_nt), 2)
            self.assertLessEqual(len(f_nt), 3)
            self.assertFalse(any(q in legacy_static for q in f_nt), msg=f"Legacy static leak: {f_nt}")
            nt_joined = " | ".join(f_nt).lower()
            self.assertTrue(
                any(tok in nt_joined for tok in ("panadol extra", "kênh bán", "nhà cung cấp", "nhập thuốc")),
                msg=f"Expected contextual pharmacy follow-up, got: {f_nt}",
            )
            for cross_tok in ("nhóm món", "món", "vật liệu", "công nợ"):
                self.assertNotIn(cross_tok, nt_joined, msg=f"Cross-DB leakage ({cross_tok}) in: {f_nt}")
            for cand in f_nt:
                self.assertIsNone(check_out_of_scope_or_irrelevant(cand, know_nt), msg=cand)
                self.assertIsNone(
                    check_preflight_unanswerable(cand, know_nt.data_max_date or "2026-10-05", know_nt, classify_expected_type(cand)),
                    msg=cand,
                )
        finally:
            eng_nt.dispose()

        # 2. Cafe DB (cafe_pho_viet): follow-ups after top drink/dish revenue query
        eng_cf, know_cf = build_datamate_workspace_engine(PROJECT_ROOT / "data" / "demo_businesses" / "cafe_pho_viet")
        try:
            df_cf = pd.DataFrame(
                [
                    {"ten_mon": "Trà đào cam sả", "doanh_thu": 495000},
                    {"ten_mon": "Cà phê sữa đá", "doanh_thu": 315000},
                ]
            )
            q_cf = "Top 5 món có doanh thu cao nhất"
            f_cf = build_datamate_suggested_questions(know_cf, lang="vi", user_query=q_cf, df=df_cf)
            self.assertGreaterEqual(len(f_cf), 2)
            self.assertLessEqual(len(f_cf), 3)
            cf_joined = " | ".join(f_cf).lower()
            for cross_tok in ("thuốc", "nhà cung cấp", "vật liệu", "công nợ"):
                self.assertNotIn(cross_tok, cf_joined, msg=f"Cross-DB leakage ({cross_tok}) in: {f_cf}")
            for cand in f_cf:
                self.assertIsNone(check_out_of_scope_or_irrelevant(cand, know_cf), msg=cand)
                self.assertIsNone(
                    check_preflight_unanswerable(cand, know_cf.data_max_date or "2026-10-06", know_cf, classify_expected_type(cand)),
                    msg=cand,
                )
        finally:
            eng_cf.dispose()

        # 3. Building materials DB (vlxd_minh_phat): blocked/starter follow-ups (df=None)
        eng_vl, know_vl = build_datamate_workspace_engine(PROJECT_ROOT / "data" / "demo_businesses" / "vlxd_minh_phat")
        try:
            f_vl = build_datamate_suggested_questions(know_vl, lang="vi", user_query="Hôm nay có mưa không?", df=None)
            self.assertGreaterEqual(len(f_vl), 2)
            self.assertLessEqual(len(f_vl), 3)
            vl_joined = " | ".join(f_vl).lower()
            self.assertTrue(
                "vật liệu" in vl_joined or "công nợ" in vl_joined,
                msg=f"Expected VLXD concepts in follow-ups, got: {f_vl}",
            )
            for cross_tok in ("thuốc", "món"):
                self.assertNotIn(cross_tok, vl_joined, msg=f"Cross-DB leakage ({cross_tok}) in: {f_vl}")
            for cand in f_vl:
                self.assertIsNone(check_out_of_scope_or_irrelevant(cand, know_vl), msg=cand)
                self.assertIsNone(
                    check_preflight_unanswerable(cand, know_vl.data_max_date or "2026-10-05", know_vl, classify_expected_type(cand)),
                    msg=cand,
                )
        finally:
            eng_vl.dispose()

    def test_insight_and_action_plan_no_decorative_emojis_and_vnd_currency(self) -> None:
        import re
        from src.analytics.heuristics import (
            extract_selectable_units,
            generate_hypothesis_tree,
            generate_persona_action_plan,
            split_insight_sections,
        )

        df = pd.DataFrame(
            [
                {"ten_thuoc": "Panadol Extra", "doanh_thu": 540000},
                {"ten_thuoc": "Vitamin C 500mg", "doanh_thu": 475000},
                {"ten_thuoc": "Efferalgan 500mg", "doanh_thu": 320000},
                {"ten_thuoc": "Berberin", "doanh_thu": 210000},
                {"ten_thuoc": "Nước muối sinh lý", "doanh_thu": 120000},
            ]
        )
        q = "Top 10 loại thuốc có tổng doanh thu cao nhất"

        sections = split_insight_sections("", df, user_query=q, is_en=False)
        ht = generate_hypothesis_tree(df, user_query=q, is_en=False)
        units = extract_selectable_units(df, user_query=q, is_en=False)
        ceo_plan = generate_persona_action_plan(df, persona="ceo", user_query=q, is_en=False)
        lead_plan = generate_persona_action_plan(
            df,
            persona="lead",
            user_query=q,
            is_en=False,
            target_unit="Nước muối sinh lý",
        )

        combined = "\n".join([repr(sections), repr(ht), repr(units), repr(ceo_plan), repr(lead_plan)])
        self.assertIsNone(
            re.search(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", combined),
            msg=f"Unexpected decorative emojis found in insight/action outputs",
        )
        self.assertIn("540,000 đ", combined)
        self.assertIn("120,000 đ", combined)
        self.assertNotIn("$540,000", combined)
        self.assertNotIn("$120,000", combined)
        self.assertNotIn("ĐỒNG TAC ĐỘNG", combined)

    def test_phase2_vietnamese_sme_language_and_product_entity_detection(self) -> None:
        import re
        from src.analytics.heuristics import (
            detect_analysis_entity_type,
            extract_selectable_units,
            generate_hypothesis_tree,
            generate_persona_action_plan,
        )

        # Product entity detection across Vietnamese SME schemas vs time_series protection on 'month'
        self.assertEqual(
            detect_analysis_entity_type(pd.DataFrame([{"ten_thuoc": "Panadol Extra", "doanh_thu": 540000}])),
            "product",
        )
        self.assertEqual(
            detect_analysis_entity_type(pd.DataFrame([{"ten_mon": "Trà đào cam sả", "doanh_thu": 495000}])),
            "product",
        )
        self.assertEqual(
            detect_analysis_entity_type(pd.DataFrame([{"nhom_mon": "Trà", "doanh_thu": 495000}])),
            "product",
        )
        self.assertEqual(
            detect_analysis_entity_type(pd.DataFrame([{"ten_vl": "Xi măng Hà Tiên", "doanh_thu": 1200000}])),
            "product",
        )
        self.assertEqual(
            detect_analysis_entity_type(pd.DataFrame([{"month": "2026-10", "doanh_thu": 100000}])),
            "time_series",
        )

        df = pd.DataFrame(
            [
                {"ten_thuoc": "Panadol Extra", "doanh_thu": 540000},
                {"ten_thuoc": "Vitamin C 500mg", "doanh_thu": 475000},
                {"ten_thuoc": "Efferalgan 500mg", "doanh_thu": 320000},
                {"ten_thuoc": "Berberin", "doanh_thu": 210000},
                {"ten_thuoc": "Nước muối sinh lý", "doanh_thu": 120000},
            ]
        )
        q = "Top 10 loại thuốc có tổng doanh thu cao nhất"

        ht = generate_hypothesis_tree(df, user_query=q, is_en=False)
        self.assertEqual(ht.get("entity_type"), "product")
        self.assertTrue(ht.get("summary_takeaway"))

        units = extract_selectable_units(df, user_query=q, is_en=False)
        ceo_plan = generate_persona_action_plan(df, persona="ceo", user_query=q, is_en=False)
        lead_plan = generate_persona_action_plan(
            df,
            persona="lead",
            user_query=q,
            is_en=False,
            target_unit="Nước muối sinh lý",
        )

        combined = "\n".join([repr(ht), repr(units), repr(ceo_plan), repr(lead_plan)])
        self.assertIsNone(
            re.search(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", combined),
            msg="Phase 2 Vietnamese outputs must remain free of decorative emojis.",
        )

        jargon_tokens = [
            "Macro P&L", "KAM", "Planogram", "Portfolio De-risking", "Category Manager",
            "Trade Marketing", "Trade Activation", "Safety Stock", "Fill-rate",
            "Weekly Pacing", "Hero SKU", "Playbook", "Pipeline", "ESG", "Meritocracy",
            "SOP", "SKU", "AOV", "ROI", "B2B", "CEO / CFO",
        ]
        for tok in jargon_tokens:
            self.assertNotIn(tok, combined, msg=f"Corporate jargon '{tok}' leaked into SME Vietnamese output")

    def test_phase2_progressive_disclosure_render_insight_cards(self) -> None:
        from streamlit.testing.v1 import AppTest

        def _render_pharmacy_insights():
            import pandas as pd
            from src.ui.components import render_insight_cards

            df_ph = pd.DataFrame(
                [
                    {"ten_thuoc": "Panadol Extra", "doanh_thu": 540000},
                    {"ten_thuoc": "Vitamin C 500mg", "doanh_thu": 475000},
                    {"ten_thuoc": "Efferalgan 500mg", "doanh_thu": 320000},
                    {"ten_thuoc": "Berberin", "doanh_thu": 210000},
                    {"ten_thuoc": "Nước muối sinh lý", "doanh_thu": 120000},
                ]
            )
            render_insight_cards(
                "",
                df=df_ph,
                is_en=False,
                user_query="Top 10 loại thuốc có tổng doanh thu cao nhất",
                turn_id="phase2_test",
            )

        at = AppTest.from_function(_render_pharmacy_insights)
        at.run(timeout=15)
        self.assertFalse(at.exception, msg=f"AppTest raised exception: {at.exception}")

        # Tier 2: Both deep-dive expanders exist and default to collapsed (expanded=False)
        self.assertEqual(len(at.expander), 2)
        for exp in at.expander:
            self.assertFalse(exp.proto.expanded)

        # Tier 1 controls: 2 selectboxes, friendly Vietnamese labels, no Macro P&L
        self.assertGreaterEqual(len(at.selectbox), 2)
        self.assertIn("Chủ cửa hàng / Quản lý chung", at.selectbox[0].options)
        all_opts_str = " | ".join(str(o) for sb in at.selectbox for o in sb.options)
        self.assertNotIn("Macro P&L", all_opts_str)

        # Pick 'Nước muối sinh lý' directly in Dropdown 2 without switching Dropdown 1
        unit_sb = at.selectbox[1]
        target_opt = next((opt for opt in unit_sb.options if "Nước muối sinh lý" in opt), None)
        self.assertIsNotNone(target_opt, msg=f"Expected 'Nước muối sinh lý' in unit options: {unit_sb.options}")
        unit_sb.select(target_opt).run(timeout=15)
        self.assertFalse(at.exception, msg=f"AppTest raised exception after selecting unit: {at.exception}")

        rendered_md = "\n".join(getattr(m, "value", "") for m in at.markdown)
        self.assertIn("Nước muối sinh lý", rendered_md)

    def test_vnd_context_english_alias_and_ui_polish(self) -> None:
        from streamlit.testing.v1 import AppTest
        from src.analytics.heuristics import (
            extract_selectable_units,
            generate_hypothesis_tree,
            generate_persona_action_plan,
            is_vnd_context_dataframe,
            split_insight_sections,
        )

        df_ph_small = pd.DataFrame(
            [
                {"ten_thuoc": "Panadol Extra", "total_revenue": 540000},
                {"ten_thuoc": "Nước muối sinh lý", "total_revenue": 120000},
            ]
        )
        self.assertTrue(is_vnd_context_dataframe(df_ph_small, col_name="total_revenue"))
        self.assertTrue(
            is_vnd_context_dataframe(
                pd.DataFrame([{"total_revenue": 1780000}]),
                col_name="total_revenue",
                sql="SELECT SUM(doanh_thu) AS total_revenue FROM hoa_don_ban",
            )
        )
        self.assertFalse(
            is_vnd_context_dataframe(
                pd.DataFrame([{"Geo": "USA", "total_revenue": 540000}]),
                col_name="total_revenue",
            )
        )
        self.assertFalse(
            is_vnd_context_dataframe(
                pd.DataFrame([{"City": "São Paulo", "Sales": 50000}]),
                col_name="Sales",
            )
        )

        df_ph_5 = pd.DataFrame(
            [
                {"ten_thuoc": "Panadol Extra", "total_revenue": 540000},
                {"ten_thuoc": "Men tiêu hóa Enterogermina", "total_revenue": 480000},
                {"ten_thuoc": "Vitamin C 500mg", "total_revenue": 475000},
                {"ten_thuoc": "Si rô ho Bảo Thanh", "total_revenue": 165000},
                {"ten_thuoc": "Nước muối sinh lý", "total_revenue": 120000},
            ]
        )
        q = "Top 10 loại thuốc có tổng doanh thu cao nhất"

        sections = split_insight_sections("", df_ph_5, user_query=q, is_en=False)
        ht = generate_hypothesis_tree(df_ph_5, user_query=q, is_en=False)
        units = extract_selectable_units(df_ph_5, user_query=q, is_en=False)
        lead_plan = generate_persona_action_plan(
            df_ph_5,
            persona="lead",
            user_query=q,
            is_en=False,
            target_unit="Nước muối sinh lý",
        )

        for name, obj in (
            ("sections", sections),
            ("hypothesis_tree", ht),
            ("selectable_units", units),
            ("lead_plan", lead_plan),
        ):
            txt = repr(obj)
            self.assertIn("540,000 đ", txt, msg=f"{name} missing 540,000 đ")
            self.assertIn("120,000 đ", txt, msg=f"{name} missing 120,000 đ")
            self.assertNotIn("$540,000", txt, msg=f"{name} leaked $540,000")
            self.assertNotIn("$120,000", txt, msg=f"{name} leaked $120,000")

        micro_actions = lead_plan.get("micro_actions", [])
        self.assertEqual(len(micro_actions), 3)
        self.assertIn("Ghép gói", micro_actions[0].get("lever_pill", ""))
        self.assertIn("trưng bày", micro_actions[0].get("lever_pill", ""))
        self.assertIn("giá bán", micro_actions[1].get("lever_pill", ""))
        self.assertNotIn("tồn kho", micro_actions[1].get("lever_pill", "").lower())
        self.assertIn("tồn kho", micro_actions[2].get("lever_pill", ""))
        self.assertNotIn("khuyến mãi", micro_actions[2].get("lever_pill", "").lower())

        df_usd = pd.DataFrame(
            [
                {"Geo": "USA", "total_revenue": 540000},
                {"Geo": "India", "total_revenue": 120000},
            ]
        )
        usd_ht_str = repr(generate_hypothesis_tree(df_usd, user_query="Top regions", is_en=False))
        self.assertIn("$540,000", usd_ht_str)
        self.assertIn("$120,000", usd_ht_str)

        def _render_pharmacy_full_result():
            import pandas as pd
            import streamlit as st
            from src.ui.components import render_result

            st.session_state["lang"] = "vi"
            df_ph = pd.DataFrame(
                [
                    {"ten_thuoc": "Panadol Extra", "total_revenue": 540000},
                    {"ten_thuoc": "Men tiêu hóa Enterogermina", "total_revenue": 480000},
                    {"ten_thuoc": "Vitamin C 500mg", "total_revenue": 475000},
                    {"ten_thuoc": "Si rô ho Bảo Thanh", "total_revenue": 165000},
                    {"ten_thuoc": "Nước muối sinh lý", "total_revenue": 120000},
                ]
            )
            render_result(
                {
                    "query": "Top 10 loại thuốc có tổng doanh thu cao nhất",
                    "sql": (
                        "SELECT ten_thuoc, SUM(doanh_thu) AS total_revenue FROM hoa_don_ban "
                        "WHERE trang_thai = 'Hoàn tất' GROUP BY ten_thuoc ORDER BY total_revenue DESC LIMIT 10"
                    ),
                    "df": df_ph,
                    "insights": "",
                    "lang": "vi",
                    "evaluator": {"score": 100, "verdict": "PASS"},
                    "followups": [
                        "Doanh Thu và số lượng bán của Panadol Extra theo từng kênh bán là bao nhiêu?"
                    ],
                },
                turn_id="vnd_alias_ui_test",
            )

        at = AppTest.from_function(_render_pharmacy_full_result)
        at.run(timeout=20)
        self.assertFalse(at.exception, msg=f"AppTest raised exception: {at.exception}")

        metric_blob = " | ".join(
            f"{getattr(m, 'label', '')} :: {getattr(m, 'value', '')} :: {getattr(m, 'delta', '')}"
            for m in at.metric
        )
        for expected_val in ("356,000 đ", "540,000 đ", "120,000 đ", "1.78 Tr đ"):
            self.assertIn(expected_val, metric_blob, msg=f"Missing {expected_val} in metrics: {metric_blob}")
        self.assertNotIn("$540,000", metric_blob)
        self.assertNotIn("$1.78", metric_blob)

        rendered_md = "\n".join(getattr(m, "value", "") for m in at.markdown)
        self.assertNotIn("$540,000", rendered_md)
        self.assertNotIn("$1.78", rendered_md)
        self.assertNotIn("▸ ", rendered_md)

    def test_extreme_comparison_prints_highest_lowest_and_difference(self) -> None:
        from unittest.mock import patch
        from streamlit.testing.v1 import AppTest
        from datamate.agent import (
            classify_expected_type,
            extract_extreme_comparison_intent,
            verify_sql_semantics,
        )
        from datamate.sql_executor import SQLExecutionResult
        from src.analytics.heuristics import select_primary_insight_columns
        from src.database.business_upload import build_datamate_workspace_engine
        from src.llm.datamate_bridge import run_datamate_enhanced_turn

        q_main = "Phân tích sự chênh lệch doanh thu giữa nhóm cao nhất và nhóm thấp nhất"
        q_list = "Tôi muốn in ra danh sách cao nhất và thấp nhất rồi tính độ chênh lệch"
        q_top2 = "In ra 2 thuốc doanh thu cao nhất và 2 thuốc thấp nhất kèm chênh lệch"
        q_scalar_diff = "Doanh thu tháng 3/2026 chênh lệch bao nhiêu so với tháng 2/2026?"

        for q_ext in (q_main, q_list):
            an = classify_expected_type(q_ext)
            self.assertEqual(an.expected_type, "table")
            self.assertEqual(an.extreme_comparison, (1, 1, True))
            self.assertEqual(extract_extreme_comparison_intent(q_ext), (1, 1, True))

        an_top2 = classify_expected_type(q_top2)
        self.assertEqual(an_top2.expected_type, "table")
        self.assertEqual(an_top2.extreme_comparison, (2, 2, True))

        an_scalar = classify_expected_type(q_scalar_diff)
        self.assertEqual(an_scalar.expected_type, "number")
        self.assertIsNone(an_scalar.extreme_comparison)

        eng_ph, know_ph = build_datamate_workspace_engine(
            PROJECT_ROOT / "data" / "demo_businesses" / "nha_thuoc_an_tam"
        )
        try:
            bad_scalar_res = SQLExecutionResult(
                ok=True, sql="SELECT 300 AS chenh_lech", columns=["chenh_lech"], rows=[(300,)], row_count=1
            )
            sem_ok, sem_msg, sem_fatal = verify_sql_semantics(
                "SELECT 300 AS chenh_lech",
                bad_scalar_res,
                q_main,
                know_ph,
                classify_expected_type(q_main),
            )
            self.assertFalse(sem_ok)
            self.assertTrue(sem_fatal)
            self.assertIn("WITH grouped AS", sem_msg)

            # 1) Mocked LLM stubbornly emits scalar diff -> Guard #15 blocks & fallback produces full table
            with patch(
                "src.llm.datamate_bridge.VeraxusClientLLMBackend.generate",
                return_value='{"status": "ok", "sql": "SELECT 300 AS chenh_lech"}',
            ):
                res = run_datamate_enhanced_turn(
                    user_query=q_main,
                    client=object(),
                    provider="Ollama (Local AI Offline)",
                    model_name="qwen2.5-coder:3b",
                    knowledge=know_ph,
                    lang="vi",
                )
            df_ph = res.get("df")
            self.assertIsNotNone(df_ph)
            self.assertEqual(len(df_ph), 2)
            self.assertEqual(df_ph.iloc[0]["ten_thuoc"], "Panadol Extra")
            self.assertEqual(df_ph.iloc[0]["nhom_xep_hang"], "Cao nhất")
            self.assertEqual(int(df_ph.iloc[0]["tong_doanh_thu"]), 540000)
            self.assertEqual(int(df_ph.iloc[0]["chenh_lech_cao_thap"]), 420000)
            self.assertEqual(df_ph.iloc[1]["ten_thuoc"], "Nước muối sinh lý")
            self.assertEqual(df_ph.iloc[1]["nhom_xep_hang"], "Thấp nhất")
            self.assertEqual(int(df_ph.iloc[1]["tong_doanh_thu"]), 120000)
            self.assertEqual(int(df_ph.iloc[1]["chenh_lech_cao_thap"]), 420000)

            exp = res.get("explanation", "")
            for tok in ("Panadol Extra", "540.000 VNĐ", "Nước muối sinh lý", "120.000 VNĐ", "420.000 VNĐ"):
                self.assertIn(tok, exp, msg=f"Missing '{tok}' in banner: {exp}")

            val_col, _ = select_primary_insight_columns(df_ph, q_main)
            self.assertEqual(val_col, "tong_doanh_thu")

            # 2) Sales-channel extreme comparison on nha_thuoc_an_tam
            q_ch = "Phân tích chênh lệch doanh thu giữa kênh cao nhất và kênh thấp nhất"
            with patch(
                "src.llm.datamate_bridge.VeraxusClientLLMBackend.generate",
                return_value='{"status": "ok", "sql": "SELECT 300 AS chenh_lech"}',
            ):
                res_ch = run_datamate_enhanced_turn(
                    user_query=q_ch,
                    client=object(),
                    provider="Ollama (Local AI Offline)",
                    model_name="qwen2.5-coder:3b",
                    knowledge=know_ph,
                    lang="vi",
                )
            df_ch = res_ch.get("df")
            self.assertIsNotNone(df_ch)
            self.assertEqual(len(df_ch), 2)
            self.assertEqual(df_ch.iloc[0]["kenh_ban"], "Tại quầy")
            self.assertEqual(int(df_ch.iloc[0]["tong_doanh_thu"]), 1290000)
            self.assertEqual(df_ch.iloc[1]["kenh_ban"], "Zalo")
            self.assertEqual(int(df_ch.iloc[1]["tong_doanh_thu"]), 490000)
            self.assertEqual(int(df_ch.iloc[0]["chenh_lech_cao_thap"]), 800000)
        finally:
            eng_ph.dispose()

        # 3) On cafe_pho_viet, generic 'nhóm' automatically JOINs danhmucmon.nhom_mon
        eng_cf, know_cf = build_datamate_workspace_engine(
            PROJECT_ROOT / "data" / "demo_businesses" / "cafe_pho_viet"
        )
        try:
            with patch(
                "src.llm.datamate_bridge.VeraxusClientLLMBackend.generate",
                return_value='{"status": "ok", "sql": "SELECT 1 AS diff"}',
            ):
                res_cf = run_datamate_enhanced_turn(
                    user_query=q_main,
                    client=object(),
                    provider="Ollama (Local AI Offline)",
                    model_name="qwen2.5-coder:3b",
                    knowledge=know_cf,
                    lang="vi",
                )
            df_cf = res_cf.get("df")
            self.assertIsNotNone(df_cf)
            self.assertEqual(len(df_cf), 2)
            self.assertEqual(df_cf.iloc[0]["nhom_mon"], "Cà phê")
            self.assertEqual(int(df_cf.iloc[0]["tong_doanh_thu"]), 845000)
            self.assertEqual(df_cf.iloc[1]["nhom_mon"], "Trà trái cây")
            self.assertEqual(int(df_cf.iloc[1]["tong_doanh_thu"]), 417000)
            self.assertEqual(int(df_cf.iloc[0]["chenh_lech_cao_thap"]), 428000)
        finally:
            eng_cf.dispose()

        # 4) UI rendering via Streamlit AppTest (KPI cards, table, chart, Tab 2)
        def _render_extreme_cmp():
            import pandas as pd
            import streamlit as st
            from src.ui.components import render_result

            st.session_state["lang"] = "vi"
            df_ext = pd.DataFrame(
                [
                    {
                        "ten_thuoc": "Panadol Extra",
                        "nhom_xep_hang": "Cao nhất",
                        "tong_doanh_thu": 540000,
                        "chenh_lech_cao_thap": 420000,
                    },
                    {
                        "ten_thuoc": "Nước muối sinh lý",
                        "nhom_xep_hang": "Thấp nhất",
                        "tong_doanh_thu": 120000,
                        "chenh_lech_cao_thap": 420000,
                    },
                ]
            )
            render_result(
                {
                    "query": "Phân tích sự chênh lệch doanh thu giữa nhóm cao nhất và nhóm thấp nhất",
                    "sql": "SELECT ten_thuoc, nhom_xep_hang, tong_doanh_thu, chenh_lech_cao_thap FROM hoa_don_ban",
                    "df": df_ext,
                    "insights": "",
                    "lang": "vi",
                    "evaluator": {"score": 100, "verdict": "PASS"},
                    "followups": [
                        "So sánh Doanh Thu bán thuốc theo từng kênh bán (Tại quầy, Zalo)?"
                    ],
                },
                turn_id="ext_cmp_ui_test",
            )

        at = AppTest.from_function(_render_extreme_cmp)
        at.run(timeout=20)
        self.assertFalse(at.exception, msg=f"AppTest raised exception: {at.exception}")

        metric_blob = " | ".join(
            f"{getattr(m, 'label', '')} :: {getattr(m, 'value', '')} :: {getattr(m, 'delta', '')}"
            for m in at.metric
        )
        for tok in ("Panadol Extra", "Nước muối sinh lý", "540,000 đ", "120,000 đ", "420,000 đ", "4.5x"):
            self.assertIn(tok, metric_blob, msg=f"Missing '{tok}' in KPI metrics: {metric_blob}")
        self.assertNotIn("$540,000", metric_blob)
        self.assertNotIn("$420,000", metric_blob)

    def test_benchmark_average_entity_query_prints_revenue_with_entity_name(self) -> None:
        from unittest.mock import patch
        from datamate.agent import (
            classify_expected_type,
            extract_benchmark_average_entity_intent,
            rewrite_ranked_entity_sql,
            verify_sql_semantics,
        )
        from datamate.sql_executor import SQLExecutionResult
        from src.database.business_upload import build_datamate_workspace_engine
        from src.llm.datamate_bridge import run_datamate_enhanced_turn

        q_above = "Những tên thuốc nào có doanh thu vượt trên mức trung bình?"
        q_below = "Những tên thuốc nào có doanh thu dưới mức trung bình?"

        self.assertEqual(extract_benchmark_average_entity_intent(q_above), ">")
        self.assertEqual(extract_benchmark_average_entity_intent(q_below), "<")
        an_above = classify_expected_type(q_above)
        self.assertEqual(an_above.expected_type, "list")
        self.assertTrue(an_above.money_like)

        # 1) rewrite_ranked_entity_sql enriches both HAVING and CTE 1-column outer SELECTs
        rewritten_hav = rewrite_ranked_entity_sql(
            "SELECT ten_thuoc FROM hoa_don_ban WHERE trang_thai NOT IN ('Đã hủy', 'Trả lại') GROUP BY ten_thuoc HAVING SUM(doanh_thu) > 350000",
            q_above,
        )
        self.assertIn("ROUND_HALF_UP(SUM(doanh_thu), 0) AS tong_doanh_thu", rewritten_hav)

        rewritten_cte = rewrite_ranked_entity_sql(
            "WITH grouped AS (SELECT ten_thuoc, ROUND_HALF_UP(SUM(doanh_thu), 0) AS tong_doanh_thu FROM hoa_don_ban WHERE trang_thai NOT IN ('Đã hủy', 'Trả lại') GROUP BY ten_thuoc) SELECT ten_thuoc FROM grouped WHERE tong_doanh_thu > (SELECT AVG(tong_doanh_thu) FROM grouped) ORDER BY tong_doanh_thu DESC",
            q_above,
        )
        self.assertIn("SELECT ten_thuoc, tong_doanh_thu FROM grouped", rewritten_cte)

        eng_ph, know_ph = build_datamate_workspace_engine(
            PROJECT_ROOT / "data" / "demo_businesses" / "nha_thuoc_an_tam"
        )
        try:
            # 2) verify_sql_semantics rejects ungrouped 1-column query with duplicate Panadol Extra rows
            bad_ungrouped_sql = (
                "SELECT ten_thuoc FROM hoa_don_ban WHERE trang_thai = 'Hoàn tất' "
                "AND doanh_thu > (SELECT AVG(doanh_thu) FROM hoa_don_ban WHERE trang_thai = 'Hoàn tất')"
            )
            bad_ungrouped_res = SQLExecutionResult(
                ok=True,
                sql=bad_ungrouped_sql,
                columns=["ten_thuoc"],
                rows=[("Panadol Extra",), ("Men tiêu hóa Enterogermina",), ("Panadol Extra",), ("Vitamin C 500mg",)],
                row_count=4,
            )
            sem_ok, sem_msg, sem_fatal = verify_sql_semantics(
                bad_ungrouped_sql,
                bad_ungrouped_res,
                q_above,
                know_ph,
                an_above,
            )
            self.assertFalse(sem_ok)
            self.assertTrue(sem_fatal)
            self.assertIn("WITH grouped AS", sem_msg)
            self.assertIn("tong_doanh_thu", sem_msg)

            # 3) End-to-end turn even when LLM emits broken ungrouped 1-col SQL: repairs/falls back to 2-col grouped CTE
            with patch(
                "src.llm.datamate_bridge.VeraxusClientLLMBackend.generate",
                return_value=f'{{"status": "ok", "sql": "{bad_ungrouped_sql}"}}',
            ):
                res_above = run_datamate_enhanced_turn(
                    user_query=q_above,
                    client=object(),
                    provider="Ollama (Local AI Offline)",
                    model_name="qwen2.5-coder:3b",
                    knowledge=know_ph,
                    lang="vi",
                )
            df_above = res_above.get("df")
            self.assertIsNotNone(df_above)
            self.assertEqual(list(df_above.columns), ["ten_thuoc", "tong_doanh_thu"])
            self.assertEqual(len(df_above), 3)
            self.assertEqual(df_above.iloc[0]["ten_thuoc"], "Panadol Extra")
            self.assertEqual(int(df_above.iloc[0]["tong_doanh_thu"]), 540000)
            self.assertEqual(df_above.iloc[1]["ten_thuoc"], "Men tiêu hóa Enterogermina")
            self.assertEqual(int(df_above.iloc[1]["tong_doanh_thu"]), 480000)
            self.assertEqual(df_above.iloc[2]["ten_thuoc"], "Vitamin C 500mg")
            self.assertEqual(int(df_above.iloc[2]["tong_doanh_thu"]), 475000)

            exp_above = res_above.get("explanation", "")
            for tok in (
                "Panadol Extra",
                "540.000 VNĐ",
                "Men tiêu hóa Enterogermina",
                "480.000 VNĐ",
                "Vitamin C 500mg",
                "475.000 VNĐ",
            ):
                self.assertIn(tok, exp_above, msg=f"Missing '{tok}' in banner: {exp_above}")

            # 4) Below-average query returns the 2 medicines < 356,000 VND with their revenues
            with patch(
                "src.llm.datamate_bridge.VeraxusClientLLMBackend.generate",
                return_value=f'{{"status": "ok", "sql": "{bad_ungrouped_sql}"}}',
            ):
                res_below = run_datamate_enhanced_turn(
                    user_query=q_below,
                    client=object(),
                    provider="Ollama (Local AI Offline)",
                    model_name="qwen2.5-coder:3b",
                    knowledge=know_ph,
                    lang="vi",
                )
            df_below = res_below.get("df")
            self.assertIsNotNone(df_below)
            self.assertEqual(list(df_below.columns), ["ten_thuoc", "tong_doanh_thu"])
            self.assertEqual(len(df_below), 2)
            self.assertEqual(df_below.iloc[0]["ten_thuoc"], "Nước muối sinh lý")
            self.assertEqual(int(df_below.iloc[0]["tong_doanh_thu"]), 120000)
            self.assertEqual(df_below.iloc[1]["ten_thuoc"], "Si rô ho Bảo Thanh")
            self.assertEqual(int(df_below.iloc[1]["tong_doanh_thu"]), 165000)

            # 5) Verify Action Plan & Hypothesis Tree wording on both 2-col revenue df and 1-col fallback df
            from src.analytics.heuristics import generate_persona_action_plan

            plan_above = generate_persona_action_plan(df_above, persona="ceo", user_query=q_above, is_en=False)
            blob_above = " ".join(plan_above.get("kpis", [])) + " " + " ".join(
                f"{m.get('headline', '')} {m.get('brief_action', '')} {m.get('target_pill', '')} {m.get('detail_note', '')}"
                for m in plan_above.get("micro_actions", [])
            )
            for banned in (
                "Thực thể dẫn đầu",
                "thực thể dẫn đầu",
                "Nhóm dẫn đầu chiếm 100.0%",
                "xoay quanh mốc chuẩn trung bình",
                "chênh lệch tuyệt đối 1",
                "Đường cơ sở toàn hệ thống neo tại mốc",
                "theo chuẩn H1 & H2",
                "cắt giảm mặt hàng không hiệu quả",
            ):
                self.assertNotIn(banned, blob_above, msg=f"Found banned robotic phrase '{banned}' in: {blob_above}")
            for expected_tok in ("540,000 đ", "475,000 đ", "498,333 đ", "Mặt hàng đứng đầu"):
                self.assertIn(expected_tok, blob_above, msg=f"Missing '{expected_tok}' in: {blob_above}")

            # 6) Verify scalar import KPI summary has zero backslash '\$' and full Vietnamese diacritics ('Tổng Tiền Nhập', '840,000 đ')
            import pandas as pd
            from src.analytics.heuristics import escape_markdown_currency_symbols, split_insight_sections

            df_imp = pd.DataFrame([{"tong_tien_nhap": 840000, "tong_so_luong_nhap": 20}])
            sec_imp = split_insight_sections("", df=df_imp, user_query="Tổng tiền nhập thuốc và số lượng nhập", is_en=False)
            full_imp_text = f"{sec_imp.get('anomaly', '')}\n{sec_imp.get('hypothesis', '')}\n{sec_imp.get('action_plan', '')}"
            self.assertNotIn(r"\$", full_imp_text)
            self.assertNotIn("$840,000", full_imp_text)
            self.assertNotIn("Tổng Tiền Nhap", full_imp_text)
            self.assertIn("Tổng Tiền Nhập", full_imp_text)
            self.assertIn("Tổng Số Lượng Nhập", full_imp_text)
            self.assertIn("840,000 đ", full_imp_text)
            self.assertIn("42,000 đ/đơn vị", full_imp_text)
            self.assertEqual(escape_markdown_currency_symbols(r"Doanh thu \$840,000 và \_test\*"), "Doanh thu $840,000 và _test*")
        finally:
            eng_ph.dispose()

    def test_cafe_pho_viet_catalog_listing_and_spurious_date_guard(self) -> None:
        from unittest.mock import patch
        from datamate.agent import (
            _match_requested_dimension_col,
            build_catalog_listing_sql_spec,
            classify_expected_type,
            extract_temporal_context,
            normalize_vn_question,
            strip_spurious_single_day_filter,
        )
        from datamate.schema_context import ground_query_entities
        from datamate.sql_executor import execute_sql_safe
        from src.database.business_upload import build_datamate_workspace_engine
        from src.llm.datamate_bridge import run_datamate_enhanced_turn

        # 1) Classification distinguishes catalog listing ('list') vs scalar total/count ('number')
        self.assertEqual(classify_expected_type("Danh sách những món thuộc nhóm Cà Phê").expected_type, "list")
        self.assertEqual(classify_expected_type("Các món thuộc nhóm món Cà phê").expected_type, "list")
        self.assertEqual(
            classify_expected_type("Tổng doanh thu của các món thuộc nhóm Cà phê là bao nhiêu?").expected_type,
            "number",
        )
        self.assertEqual(classify_expected_type("Có bao nhiêu món thuộc nhóm Cà phê?").expected_type, "number")

        eng_cf, know_cf = build_datamate_workspace_engine(
            PROJECT_ROOT / "data" / "demo_businesses" / "cafe_pho_viet"
        )
        try:
            # 2) semantic_summary includes pure catalog tables (danhmucmon)
            self.assertIn("danhmucmon", know_cf.semantic_summary)

            # 3) Membership filter ('thuộc nhóm món Cà phê') must NOT force GROUP BY nhom_mon,
            #    while true grouping breakdowns ('Nhóm món nào...', 'theo từng nhóm món') still match
            self.assertIsNone(
                _match_requested_dimension_col(
                    normalize_vn_question("Các món thuộc nhóm món Cà phê"),
                    know_cf,
                )
            )
            self.assertIsNotNone(
                _match_requested_dimension_col(
                    normalize_vn_question("Nhóm món nào mang lại doanh thu cao nhất?"),
                    know_cf,
                )
            )
            self.assertIsNotNone(
                _match_requested_dimension_col(
                    normalize_vn_question("Tỷ lệ đóng góp thành tiền của từng nhóm món vào tổng số"),
                    know_cf,
                )
            )

            # 4) strip_spurious_single_day_filter removes unrequested equality date filters safely
            q_open = "Danh sách những món thuộc nhóm Cà Phê"
            an_open = classify_expected_type(q_open)
            w_open, ts_open, bd_open, _ = extract_temporal_context(q_open, "2026-10-06", None)
            an_open.temporal_windows = w_open
            an_open.temporal_summary = ts_open
            an_open.bounded_period = bd_open

            stripped_and = strip_spurious_single_day_filter(
                "SELECT dm.ten_mon, dm.don_gia FROM danhmucmon dm JOIN donhang dh ON dm.ten_mon = dh.ten_mon "
                "WHERE dm.nhom_mon = 'Cà phê' AND dh.ngay_ban = '2026-10-06';",
                q_open,
                an_open,
            )
            self.assertNotIn("2026-10-06", stripped_and)
            self.assertIn("dm.nhom_mon = 'Cà phê'", stripped_and)

            stripped_lone = strip_spurious_single_day_filter(
                "SELECT ten_mon, thanh_tien FROM donhang WHERE ngay_ban = '2026-10-06' ORDER BY ten_mon;",
                q_open,
                an_open,
            )
            self.assertNotIn("WHERE", stripped_lone.upper())
            self.assertNotIn("2026-10-06", stripped_lone)

            or_sql = "SELECT * FROM donhang WHERE trang_thai = 'Hoàn thành' OR ngay_ban = '2026-10-06';"
            self.assertEqual(strip_spurious_single_day_filter(or_sql, q_open, an_open), or_sql)

            q_today = "Hôm nay bán được những món nào?"
            an_today = classify_expected_type(q_today)
            w_t, ts_t, bd_t, _ = extract_temporal_context(q_today, "2026-10-06", None)
            an_today.temporal_windows = w_t
            an_today.temporal_summary = ts_t
            an_today.bounded_period = bd_t
            today_sql = "SELECT ten_mon, SUM(thanh_tien) FROM donhang WHERE ngay_ban = '2026-10-06' GROUP BY ten_mon;"
            self.assertEqual(strip_spurious_single_day_filter(today_sql, q_today, an_today), today_sql)

            # 5) build_catalog_listing_sql_spec queries danhmucmon directly with NORM_VN matching all 3 coffee items
            ents_cf = ground_query_entities(q_open, know_cf, max_matches=12)
            spec = build_catalog_listing_sql_spec(q_open, know_cf, an_open, ents_cf)
            self.assertIsNotNone(spec)
            self.assertEqual(spec["table"], "danhmucmon")
            self.assertIn("NORM_VN(", spec["suggested_sql"])
            res_spec = execute_sql_safe(know_cf.workspace.open_connection, spec["suggested_sql"], know_cf.valid_tables)
            self.assertTrue(res_spec.ok)
            self.assertEqual(
                sorted(r[0] for r in res_spec.rows),
                ["Bạc xỉu", "Cà phê muối", "Cà phê sữa đá"],
            )

            # Transactional ranking prompt must NOT trigger catalog-only spec
            q_tx = "Top 5 món có Doanh Thu cao nhất trong tháng 10/2026?"
            an_tx = classify_expected_type(q_tx)
            self.assertIsNone(build_catalog_listing_sql_spec(q_tx, know_cf, an_tx, ents_cf))

            # 6) End-to-end turn never blocks even if LLM emits wrong-case category + spurious date filter
            bad_cat_sql = (
                "SELECT dm.ten_mon, dm.don_gia FROM danhmucmon dm "
                "JOIN donhang dh ON dm.ten_mon = dh.ten_mon "
                "WHERE dm.nhom_mon = 'Cà Phê' AND dh.ngay_ban = '2026-10-06'"
            )
            with patch(
                "src.llm.datamate_bridge.VeraxusClientLLMBackend.generate",
                return_value=f'{{"status": "ok", "sql": "{bad_cat_sql}"}}',
            ):
                res_cat = run_datamate_enhanced_turn(
                    user_query=q_open,
                    client=object(),
                    provider="Ollama (Local AI Offline)",
                    model_name="qwen2.5-coder:3b",
                    knowledge=know_cf,
                    lang="vi",
                )
            df_cat = res_cat.get("df")
            self.assertIsNotNone(df_cat)
            self.assertFalse(df_cat.empty)
            self.assertEqual(
                sorted(df_cat["ten_mon"].tolist()),
                ["Bạc xỉu", "Cà phê muối", "Cà phê sữa đá"],
            )
            exp_cat = res_cat.get("explanation", "")
            self.assertNotIn("từ chối", exp_cat.lower())
            self.assertNotIn("LỖI LỌC NGÀY THỪA", exp_cat)
            for item_tok in ("Bạc xỉu", "39.000 VNĐ", "Cà phê muối", "40.000 VNĐ", "Cà phê sữa đá", "35.000 VNĐ"):
                self.assertIn(item_tok, exp_cat, msg=f"Missing '{item_tok}' in banner: {exp_cat}")

            # 7) Single-item catalog category ('Đá xay' -> Matcha đá xay, 55,000 VNĐ) prints item + unit price cleanly
            q_ice = "Danh sách những món thuộc nhóm Đá xay"
            with patch(
                "src.llm.datamate_bridge.VeraxusClientLLMBackend.generate",
                return_value='{"status": "ok", "sql": "SELECT ten_mon, nhom_mon, don_gia FROM danhmucmon WHERE NORM_VN(nhom_mon) = NORM_VN(\'Đá xay\');"}',
            ):
                res_ice = run_datamate_enhanced_turn(
                    user_query=q_ice,
                    client=object(),
                    provider="Ollama (Local AI Offline)",
                    model_name="qwen2.5-coder:3b",
                    knowledge=know_cf,
                    lang="vi",
                )
            df_ice = res_ice.get("df")
            self.assertIsNotNone(df_ice)
            self.assertEqual(df_ice["ten_mon"].tolist(), ["Matcha đá xay"])
            exp_ice = res_ice.get("explanation", "")
            self.assertIn("Matcha đá xay", exp_ice)
            self.assertIn("55.000 VNĐ", exp_ice)
        finally:
            eng_cf.dispose()

    def test_two_part_entity_plus_metric_sanofi_and_other_dbs(self) -> None:
        from unittest.mock import patch

        from datamate.agent import (
            classify_expected_type,
            verify_sql_semantics,
        )
        from datamate.schema_context import ground_query_entities
        from datamate.sql_executor import execute_sql_safe
        from src.database.business_upload import build_datamate_workspace_engine
        from src.llm.datamate_bridge import run_datamate_enhanced_turn

        eng_nt, know_nt = build_datamate_workspace_engine(
            PROJECT_ROOT / "data" / "demo_businesses" / "nha_thuoc_an_tam"
        )
        try:
            q_sanofi = "Nhà cung cấp Sanofi VN đã nhập những loại thuốc nào và tổng tiền nhập là bao nhiêu?"
            an = classify_expected_type(q_sanofi)
            self.assertEqual(an.expected_type, "table")
            self.assertTrue(an.money_like)

            ents = ground_query_entities(q_sanofi, know_nt, max_matches=12)

            # 1) Semantic guard MUST reject scalar-only SQL that omits medicine name
            scalar_sql = (
                "SELECT ROUND_HALF_UP(SUM(so_luong_nhap * gia_nhap), 0) AS tong_tien_nhap "
                "FROM phieu_nhap_thuoc WHERE NORM_VN(nha_cung_cap) = NORM_VN('Sanofi VN');"
            )
            res_scalar = execute_sql_safe(know_nt.workspace.open_connection, scalar_sql, know_nt.valid_tables)
            self.assertTrue(res_scalar.ok)
            sem_ok, sem_msg, sem_fatal = verify_sql_semantics(
                scalar_sql, res_scalar, q_sanofi, know_nt, an, entity_matches=ents
            )
            self.assertFalse(sem_ok)
            self.assertTrue(sem_fatal)
            self.assertIn("ten_thuoc", sem_msg)

            # 2) Semantic guard MUST also reject 2-numeric-col SQL still dropping ten_thuoc
            two_num_sql = (
                "SELECT SUM(so_luong_nhap) AS tong_sl, ROUND_HALF_UP(SUM(so_luong_nhap * gia_nhap), 0) AS tong_tien_nhap "
                "FROM phieu_nhap_thuoc WHERE NORM_VN(nha_cung_cap) = NORM_VN('Sanofi VN');"
            )
            res_2num = execute_sql_safe(know_nt.workspace.open_connection, two_num_sql, know_nt.valid_tables)
            sem_ok2, _, sem_fatal2 = verify_sql_semantics(
                two_num_sql, res_2num, q_sanofi, know_nt, an, entity_matches=ents
            )
            self.assertFalse(sem_ok2)
            self.assertTrue(sem_fatal2)

            # 3) Full turn with mock LLM outputting scalar-only SQL recovers via deterministic fallback
            with patch(
                "src.llm.datamate_bridge.VeraxusClientLLMBackend.generate",
                return_value=f'{{"status": "ok", "sql": "{scalar_sql}"}}',
            ):
                turn = run_datamate_enhanced_turn(
                    user_query=q_sanofi,
                    client=object(),
                    provider="Ollama (Local AI Offline)",
                    model_name="qwen2.5-coder:3b",
                    knowledge=know_nt,
                    lang="vi",
                )
            df_out = turn.get("df")
            self.assertIsNotNone(df_out)
            self.assertFalse(df_out.empty)
            self.assertIn("ten_thuoc", df_out.columns)
            self.assertIn("tong_tien_nhap", df_out.columns)
            self.assertEqual(df_out["ten_thuoc"].tolist(), ["Men tiêu hóa Enterogermina"])
            self.assertEqual(int(round(float(df_out["tong_tien_nhap"].iloc[0]))), 1150000)
            exp = turn.get("explanation", "")
            self.assertIn("Men tiêu hóa Enterogermina", exp)
            self.assertIn("1.150.000 VNĐ", exp)
        finally:
            eng_nt.dispose()

    def test_no_unprovable_hypothesis_scores_or_h3_rejection(self) -> None:
        from src.analytics.heuristics import generate_hypothesis_tree, generate_persona_action_plan

        dfs = [
            (
                pd.DataFrame(
                    [
                        {"ten_thuoc": "Panadol Extra", "doanh_thu": 540000},
                        {"ten_thuoc": "Vitamin C 500mg", "doanh_thu": 475000},
                        {"ten_thuoc": "Enterogermina", "doanh_thu": 120000},
                    ]
                ),
                "Top 5 loại thuốc có Doanh Thu bán ra cao nhất trong tháng 10/2026?",
            ),
            (
                pd.DataFrame(
                    [
                        {"ngay": "2026-10-01", "doanh_thu": 420000},
                        {"ngay": "2026-10-02", "doanh_thu": 680000},
                        {"ngay": "2026-10-03", "doanh_thu": 510000},
                    ]
                ),
                "Xu hướng doanh thu theo từng ngày",
            ),
            (
                pd.DataFrame([{"tong_doanh_thu": 1610000}]),
                "Tổng doanh thu là bao nhiêu?",
            ),
        ]

        banned_tokens = (
            "bác bỏ qua data",
            "rejected by data",
            "độ chính xác",
            "điểm ưu tiên",
            "điểm tác động",
            "/100",
            "4/100",
            "giả thuyết 3",
            "hypothesis 3",
            "h3",
        )

        for df_sample, q_sample in dfs:
            for lang_flag in (False, True):
                tree = generate_hypothesis_tree(df_sample, user_query=q_sample, is_en=lang_flag)
                branches = tree.get("branches", [])
                self.assertTrue(len(branches) >= 1)
                for b in branches:
                    self.assertNotEqual(b.get("status"), "REJECTED")
                    self.assertNotEqual(b.get("id"), "H3")
                    self.assertNotIn("confidence", b)
                    self.assertNotIn("priority_score", b)
                    self.assertNotIn("impact", b)
                blob_tree = f"{tree}".lower()
                for tok in banned_tokens:
                    self.assertNotIn(tok, blob_tree, msg=f"Forbidden '{tok}' leaked in tree ({q_sample})")

                for role in ("ceo", "lead"):
                    plan = generate_persona_action_plan(df_sample, persona=role, user_query=q_sample, is_en=lang_flag)
                    blob_plan = f"{plan}".lower()
                    for tok in banned_tokens:
                        self.assertNotIn(tok, blob_plan, msg=f"Forbidden '{tok}' leaked in {role} plan ({q_sample})")

        comp_src = (PROJECT_ROOT / "src" / "ui" / "components.py").read_text(encoding="utf-8")
        self.assertNotIn("Loại trừ", comp_src)
        self.assertNotIn("Ưu tiên: {prio_score}/100", comp_src)
        self.assertNotIn("Độ chính xác", comp_src)
        self.assertNotIn("3 giả thuyết đối chứng", comp_src)

    def test_sidebar_and_saved_templates_ui_hygiene(self) -> None:
        sidebar_src = (PROJECT_ROOT / "src" / "ui" / "sidebar.py").read_text(encoding="utf-8")
        onboarding_src = (PROJECT_ROOT / "src" / "ui" / "onboarding.py").read_text(encoding="utf-8")
        evo_src = (PROJECT_ROOT / "src" / "ui" / "evolution_dashboard.py").read_text(encoding="utf-8")
        i18n_src = (PROJECT_ROOT / "src" / "i18n.py").read_text(encoding="utf-8")

        # 1) Sidebar must NOT show Vòng Lặp Tiến Hóa button
        self.assertNotIn("sidebar_btn_toggle_evo", sidebar_src)
        self.assertNotIn("sidebar_btn_evolution", sidebar_src)

        # 2) Settings must expose Mẫu truy vấn đã lưu button
        self.assertIn("btn_onboarding_open_templates", onboarding_src)
        self.assertIn("Mẫu truy vấn đã lưu", onboarding_src)

        # 3) No internal dev/ML jargon in saved templates UI & i18n
        for jargon in (
            "Tier 2 Online Learning",
            "Two-Tier Feedback Loop",
            "Dynamic Few-Shot",
            "APIGen",
            "SELF-EVOLVING ACTIVE",
            "Vòng Lặp Tiến Hóa",
            "SELF-EVOLUTION LOOP",
        ):
            self.assertNotIn(jargon, evo_src, msg=f"Jargon '{jargon}' still in evolution_dashboard.py")
            self.assertNotIn(jargon, i18n_src, msg=f"Jargon '{jargon}' still in i18n.py")

    def test_multiturn_followup_anti_repeat_and_diversity(self) -> None:
        from datamate.agent import (
            check_out_of_scope_or_irrelevant,
            check_preflight_unanswerable,
            classify_expected_type,
        )
        from datamate.sql_executor import norm_vn
        from src.database.business_upload import build_datamate_workspace_engine
        from src.llm.datamate_bridge import build_datamate_suggested_questions

        for db_dir, starter_q, init_df in (
            (
                "nha_thuoc_an_tam",
                "Top 5 loại thuốc có Doanh Thu bán ra cao nhất trong tháng 10/2026?",
                pd.DataFrame(
                    [
                        {"ten_thuoc": "Panadol Extra", "doanh_thu": 540000},
                        {"ten_thuoc": "Vitamin C 500mg", "doanh_thu": 475000},
                        {"ten_thuoc": "Men tiêu hóa Enterogermina", "doanh_thu": 115000},
                    ]
                ),
            ),
            (
                "cafe_pho_viet",
                "Top 5 món có Doanh Thu cao nhất trong tháng 10/2026?",
                pd.DataFrame(
                    [
                        {"ten_mon": "Trà đào cam sả", "doanh_thu": 495000},
                        {"ten_mon": "Cà phê sữa đá", "doanh_thu": 315000},
                        {"ten_mon": "Bạc xỉu", "doanh_thu": 195000},
                    ]
                ),
            ),
        ):
            eng, know = build_datamate_workspace_engine(PROJECT_ROOT / "data" / "demo_businesses" / db_dir)
            try:
                asked = [starter_q]
                seen_fup_norms = {norm_vn(starter_q)}
                all_generated: list[str] = []
                cur_q = starter_q
                cur_df = init_df
                for turn_idx in range(6):
                    fups = build_datamate_suggested_questions(
                        know,
                        lang="vi",
                        user_query=cur_q,
                        df=cur_df if turn_idx == 0 else None,
                        asked_queries=asked,
                    )
                    self.assertGreaterEqual(len(fups), 2, msg=f"{db_dir} turn {turn_idx}: {fups}")
                    self.assertLessEqual(len(fups), 3)
                    for q_s in fups:
                        self.assertIsNone(check_out_of_scope_or_irrelevant(q_s, know), msg=q_s)
                        self.assertIsNone(
                            check_preflight_unanswerable(
                                q_s,
                                know.data_max_date or "2026-10-06",
                                know,
                                classify_expected_type(q_s),
                            ),
                            msg=q_s,
                        )
                        self.assertNotIn(
                            norm_vn(q_s),
                            {norm_vn(a) for a in asked},
                            msg=f"{db_dir} turn {turn_idx} repeated already-asked question: {q_s}",
                        )
                    all_generated.extend(fups)
                    # Simulate user clicking the first suggestion next turn
                    next_pick = fups[0]
                    self.assertNotIn(norm_vn(next_pick), seen_fup_norms)
                    seen_fup_norms.add(norm_vn(next_pick))
                    asked.append(next_pick)
                    cur_q = next_pick

                # Across 6 turns, suggestions must span multiple distinct business angles (not repetitive)
                unique_norm_count = len({norm_vn(x) for x in all_generated})
                self.assertGreaterEqual(
                    unique_norm_count,
                    8,
                    msg=f"Expected high question diversity across 6 turns on {db_dir}, got {unique_norm_count}: {all_generated}",
                )
            finally:
                eng.dispose()

    def test_daily_trend_zero_fill_kpi_label_and_vnd_line_chart(self) -> None:
        from unittest.mock import patch

        from src.analytics.heuristics import ensure_continuous_daily_series
        from src.database.business_upload import build_datamate_workspace_engine
        from src.llm.datamate_bridge import run_datamate_enhanced_turn
        from src.visualization.charts import render_smart_chart

        eng_cf, know_cf = build_datamate_workspace_engine(
            PROJECT_ROOT / "data" / "demo_businesses" / "cafe_pho_viet"
        )
        try:
            q_daily = "Xu hướng Doanh Thu của Cà phê sữa đá theo từng ngày trong tháng 10/2026?"
            sql_daily = (
                "SELECT ngay_ban, ROUND_HALF_UP(SUM(thanh_tien), 0) AS doanh_thu "
                "FROM donhang "
                "WHERE NORM_VN(ten_mon) = NORM_VN('Cà phê sữa đá') "
                "AND trang_thai = 'Hoàn thành' "
                "AND ngay_ban BETWEEN '2026-10-01' AND '2026-10-31' "
                "GROUP BY ngay_ban ORDER BY ngay_ban ASC;"
            )
            with patch(
                "src.llm.datamate_bridge.VeraxusClientLLMBackend.generate",
                return_value=f'{{"status": "ok", "sql": "{sql_daily}"}}',
            ):
                res_daily = run_datamate_enhanced_turn(
                    user_query=q_daily,
                    client=object(),
                    provider="Ollama (Local AI Offline)",
                    model_name="qwen2.5-coder:3b",
                    knowledge=know_cf,
                    lang="vi",
                )

            df_daily = res_daily.get("df")
            self.assertIsNotNone(df_daily)
            # All 6 continuous days in active operating window (2026-10-01..2026-10-06), NOT just 3 rows or 31 future days
            self.assertEqual(
                df_daily["ngay_ban"].tolist(),
                [
                    "2026-10-01",
                    "2026-10-02",
                    "2026-10-03",
                    "2026-10-04",
                    "2026-10-05",
                    "2026-10-06",
                ],
            )
            self.assertEqual(
                [int(round(v)) for v in df_daily["doanh_thu"].tolist()],
                [105000, 0, 175000, 0, 0, 210000],
            )
            exp = res_daily.get("explanation", "")
            for zero_day in ("2026-10-02", "2026-10-04", "2026-10-05"):
                self.assertIn(zero_day, exp)

            # Peak-day query must NOT be padded with 0-revenue days
            df_peak = pd.DataFrame([{"ngay_ban": "2026-10-06", "doanh_thu": 210000}])
            self.assertEqual(
                len(
                    ensure_continuous_daily_series(
                        df_peak,
                        user_query="Ngày nào có Doanh Thu cao nhất trong tháng 10/2026?",
                        min_date="2026-10-01",
                        max_date="2026-10-06",
                    )
                ),
                1,
            )

            # UI KPI label check: must NOT default time-series dimension to "Department" / "Số phòng ban"
            comp_src = (PROJECT_ROOT / "src" / "ui" / "components.py").read_text(encoding="utf-8")
            self.assertNotIn('_dim_col = label_cols[0] if label_cols else "Department"', comp_src)
            self.assertIn('"Số ngày"', comp_src)

            # Line chart currency check: must format VND ("đ"), NOT "$", and avoid inf% on 0->positive jump
            captured_figs = []
            with patch("src.visualization.charts.st.plotly_chart", side_effect=lambda fig, **kw: captured_figs.append(fig)), \
                 patch("src.visualization.charts.st.caption"):
                render_smart_chart(df_daily, "Tự động", "test_daily_vnd", user_query=q_daily)
            self.assertTrue(captured_figs, "Expected render_smart_chart to produce a Plotly figure")
            fig = captured_figs[0]
            yaxis_prefix = getattr(fig.layout.yaxis, "tickprefix", "") or ""
            yaxis_suffix = getattr(fig.layout.yaxis, "ticksuffix", "") or ""
            self.assertNotEqual(yaxis_prefix, "$")
            self.assertIn("đ", yaxis_suffix)
            hover_blob = " ".join(str(x) for x in (getattr(fig.data[0], "text", None) or []))
            self.assertNotIn("$", hover_blob)
            self.assertNotIn("inf%", hover_blob.lower())
            self.assertIn("đ", hover_blob)
        finally:
            eng_cf.dispose()


if __name__ == "__main__":
    unittest.main()
