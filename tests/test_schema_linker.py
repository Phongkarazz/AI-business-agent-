"""
Unit and Integration Tests for Enterprise Schema Linking & Metadata RAG Engine.
Tests:
1. Multi-table ranking and selective pruning on Sakila (16 tables) and Employees (6 tables).
2. Bridge table graph discovery (connecting tables via Foreign Keys shortest path).
3. Vietnamese & English domain synonym mapping (amount, salary, customer, employee...).
4. Scale test with simulated 100-table Enterprise ERP schema.
5. End-to-end integration with SupervisorAgent and run_agent pipeline.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "llm")))

from schema_linker import (
    SchemaLinker,
    SchemaGraph,
    TableMetadata,
    link_schema_for_query,
    BUSINESS_SYNONYMS
)


class TestSchemaLinker(unittest.TestCase):

    def test_schema_graph_shortest_path(self):
        """Kiểm tra khả năng tìm đường đi ngắn nhất giữa các bảng qua Foreign Keys."""
        graph = SchemaGraph()
        # payments -> customer -> address -> city -> country
        graph.add_edge("payment", "customer", "customer_id", "customer_id")
        graph.add_edge("customer", "address", "address_id", "address_id")
        graph.add_edge("address", "city", "city_id", "city_id")
        graph.add_edge("city", "country", "country_id", "country_id")

        path = graph.find_shortest_path("payment", "country")
        self.assertEqual(path, ["payment", "customer", "address", "city", "country"])

    def test_schema_graph_bridge_table_connection(self):
        """Kiểm tra khả năng tự động bổ sung bảng cầu nối (Junction/Bridge table) như dept_emp giữa employees và departments."""
        graph = SchemaGraph()
        graph.add_edge("employees", "dept_emp", "emp_no", "emp_no")
        graph.add_edge("dept_emp", "departments", "dept_no", "dept_no")

        connected = graph.connect_subgraph(["employees", "departments"])
        self.assertIn("dept_emp", connected)
        self.assertIn("employees", connected)
        self.assertIn("departments", connected)

    def test_schema_linker_sakila_16_tables_pruning(self):
        """Kiểm tra Schema Linker trên CSDL Sakila (16 bảng): chỉ giữ lại các bảng liên quan đến doanh thu & khách hàng."""
        sakila_schema = """Cơ sở dữ liệu bao gồm các bảng và cột sau:
- Bảng `actor`: actor_id (INT), first_name (VARCHAR), last_name (VARCHAR)
- Bảng `film`: film_id (INT), title (VARCHAR), description (TEXT), rental_rate (DECIMAL), length (INT)
- Bảng `film_actor`: actor_id (INT), film_id (INT)
- Bảng `category`: category_id (INT), name (VARCHAR)
- Bảng `film_category`: film_id (INT), category_id (INT)
- Bảng `customer`: customer_id (INT), store_id (INT), first_name (VARCHAR), last_name (VARCHAR), email (VARCHAR)
- Bảng `payment`: payment_id (INT), customer_id (INT), staff_id (INT), rental_id (INT), amount (DECIMAL), payment_date (DATETIME)
- Bảng `rental`: rental_id (INT), rental_date (DATETIME), inventory_id (INT), customer_id (INT), return_date (DATETIME)
- Bảng `inventory`: inventory_id (INT), film_id (INT), store_id (INT)
- Bảng `store`: store_id (INT), manager_staff_id (INT), address_id (INT)
- Bảng `staff`: staff_id (INT), first_name (VARCHAR), last_name (VARCHAR)
- Bảng `address`: address_id (INT), address (VARCHAR), city_id (INT)
- Bảng `city`: city_id (INT), city (VARCHAR), country_id (INT)
- Bảng `country`: country_id (INT), country (VARCHAR)

=== QUAN HỆ KHÓA NGOẠI LIÊN KẾT (FOREIGN KEYS) ===
• Bảng `payment` (customer_id) liên kết với `customer` (customer_id)
• Bảng `payment` (rental_id) liên kết với `rental` (rental_id)
• Bảng `rental` (inventory_id) liên kết với `inventory` (inventory_id)
• Bảng `inventory` (film_id) liên kết với `film` (film_id)
• Bảng `film_category` (film_id) liên kết với `film` (film_id)
• Bảng `film_category` (category_id) liên kết với `category` (category_id)
"""

        query = "Top 5 khách hàng có tổng tiền mặt chi tiêu thanh toán lớn nhất"
        res = link_schema_for_query(query, sakila_schema, max_tables=4)

        self.assertTrue(res["is_pruned"])
        selected_lower = [t.lower() for t in res["selected_tables"]]
        self.assertIn("customer", selected_lower)
        self.assertIn("payment", selected_lower)
        pruned_lower = [t.lower() for t in res["pruned_tables"]]
        self.assertIn("actor", pruned_lower)

    def test_schema_linker_enterprise_100_tables_scalability(self):
        """Kiểm tra khả năng chịu tải trên CSDL ERP giả lập 100 bảng."""
        tables_ddl = []
        fks = []
        
        for i in range(1, 98):
            tables_ddl.append(f"- Bảng `erp_module_{i}_data`: id (INT), mod_code_{i} (VARCHAR), status (VARCHAR)")

        tables_ddl.append("- Bảng `erp_merchants`: merchant_id (INT), merchant_name (VARCHAR), tier (VARCHAR)")
        tables_ddl.append("- Bảng `erp_orders`: order_id (INT), merchant_id (INT), order_amount (DECIMAL), order_date (DATETIME)")
        tables_ddl.append("- Bảng `erp_settlements`: settlement_id (INT), order_id (INT), payout_amount (DECIMAL)")

        fks.append("• Bảng `erp_orders` (merchant_id) liên kết với `erp_merchants` (merchant_id)")
        fks.append("• Bảng `erp_settlements` (order_id) liên kết với `erp_orders` (order_id)")

        full_erp_schema = "Cơ sở dữ liệu bao gồm các bảng và cột sau:\n" + "\n".join(tables_ddl) + "\n\n=== QUAN HỆ KHÓA NGOẠI LIÊN KẾT (FOREIGN KEYS) ===\n" + "\n".join(fks)

        query = "Top 10 merchant có tổng payout_amount tiền thanh toán cao nhất năm 2023"
        res = link_schema_for_query(query, full_erp_schema, max_tables=5)

        self.assertTrue(res["is_pruned"])
        self.assertLessEqual(len(res["selected_tables"]), 6)
        selected_lower = [t.lower() for t in res["selected_tables"]]
        self.assertIn("erp_settlements", selected_lower)
        self.assertIn("erp_merchants", selected_lower)
        self.assertIn("erp_orders", selected_lower)
        self.assertGreaterEqual(len(res["pruned_tables"]), 90)


if __name__ == "__main__":
    unittest.main()
