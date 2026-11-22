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
from src.database.crm_queries import detect_dashboard_domain


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
            self.assertIn("1,427,000 đ", rendered_html)
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
            self.assertIn("54,700,000 đ", rendered_html)
            self.assertIn("20,200,000 đ", rendered_html)
            self.assertGreaterEqual(len(at.get("plotly_chart")), 3)
        finally:
            eng.dispose()


if __name__ == "__main__":
    unittest.main()
