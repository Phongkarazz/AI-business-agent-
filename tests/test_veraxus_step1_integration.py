"""Integration tests for Veraxus Bước 1: DataMate upload/workspace + run_agent bridge."""

from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.database.business_upload import (
    UPLOAD_WORKSPACES_ROOT,
    WORKSPACE_CACHE_ROOT,
    attach_datamate_sqlite_udfs,
    build_datamate_workspace_engine,
    build_knowledge_from_sqlite_path,
    compose_connection_schema,
    resolve_database_connection,
    save_uploaded_business_files,
)
from src.database.query_runner import read_sql_capped
from src.llm.agent import run_agent
from src.llm.datamate_bridge import augment_vietnamese_query_with_temporal


class _FakeUploadFile:
    def __init__(self, name: str, data: bytes) -> None:
        self.name = name
        self._data = data

    def getvalue(self) -> bytes:
        return self._data


class _QueuedOpenAIClient:
    """Minimal mock compatible with VeraxusClientLLMBackend._call_openai."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("No queued LLM responses left")
        content = self._responses.pop(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


class TestVeraxusStep1Integration(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = pathlib.Path(tempfile.mkdtemp(prefix="veraxus_step1_"))
        self._upload_slug = f"test_step1_{self._tmp_dir.name}"
        self._ws_dir = self._tmp_dir / "shop_ws"
        self._ws_dir.mkdir(parents=True, exist_ok=True)
        (self._ws_dir / "orders.csv").write_text(
            "order_id,order_date,customer_name,product_name,qty,total_amount,status\n"
            "1,2026-10-01,Nguyễn Văn An,Yến Sào Tinh Chế,2,3000000,completed\n"
            "2,2026-10-02,Trần Thị Bình,Yến Thô Đảo,1,1800000,completed\n"
            "3,2026-10-03,Lê Minh Châu,Nước Yến Hũ,5,750000,cancelled\n"
            "4,2026-10-04,Phạm Quốc Dũng,Yến Sào Tinh Chế,3,4500000,completed\n"
            "5,2026-10-04,Nguyễn Văn An,Nước Yến Hũ,4,600000,completed\n",
            encoding="utf-8",
        )
        (self._ws_dir / "README.md").write_text(
            "# Cửa hàng Yến Mẫn\n"
            "- Không tính đơn cancelled khi tính doanh thu thực.\n"
            "- Bảng chính: orders.\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp_dir, ignore_errors=True)
        uploaded_dir = UPLOAD_WORKSPACES_ROOT / self._upload_slug
        if uploaded_dir.exists():
            shutil.rmtree(uploaded_dir, ignore_errors=True)
        for cache_stem in (self._upload_slug, "shop_ws", "yen_sao_ws", "multi_tbl_ws"):
            cache_file = WORKSPACE_CACHE_ROOT / f"{cache_stem}.sqlite"
            if cache_file.exists():
                cache_file.unlink()
        if WORKSPACE_CACHE_ROOT.exists() and not any(WORKSPACE_CACHE_ROOT.iterdir()):
            WORKSPACE_CACHE_ROOT.rmdir()
        if UPLOAD_WORKSPACES_ROOT.exists() and not any(UPLOAD_WORKSPACES_ROOT.iterdir()):
            UPLOAD_WORKSPACES_ROOT.rmdir()

    def test_upload_save_build_engine_and_udfs(self) -> None:
        files = [
            _FakeUploadFile("orders.csv", (self._ws_dir / "orders.csv").read_bytes()),
            _FakeUploadFile("README.md", (self._ws_dir / "README.md").read_bytes()),
        ]
        saved_dir = save_uploaded_business_files(files, workspace_name=self._upload_slug)
        self.assertTrue((saved_dir / "orders.csv").exists())

        engine, knowledge = build_datamate_workspace_engine(saved_dir, force_rebuild=True)
        self.assertIsNotNone(knowledge)
        self.assertEqual(knowledge.data_max_date, "2026-10-04")
        self.assertTrue(knowledge.order_status_targets)
        self.assertIn("completed", knowledge.order_status_targets[0]["valid_values"])

        df_norm, is_truncated = read_sql_capped(
            "SELECT SUM(total_amount) AS rev, ROUND_HALF_UP(AVG(total_amount), 0) AS avg_rev "
            "FROM orders WHERE status = 'completed' AND NORM_VN(customer_name) = 'nguyen van an'",
            engine,
        )
        self.assertFalse(is_truncated)
        self.assertEqual(len(df_norm), 1)
        self.assertEqual(int(df_norm.iloc[0]["rev"]), 3600000)
        engine.dispose()

    def test_resolve_demo_engines_and_compose_schema(self) -> None:
        eng_yen, kn_yen, dial_yen, desc_yen, is_demo_yen = resolve_database_connection(
            use_demo=True,
            db_host="",
            db_port="3306",
            db_user="",
            db_pass="",
            db_name="yen_sao_db",
            use_ssl=False,
        )
        self.assertEqual(dial_yen, "SQLite")
        self.assertEqual(desc_yen, "SQLite Yến Sào Demo")
        self.assertTrue(is_demo_yen)
        self.assertIsNotNone(kn_yen)
        df_udf, is_trunc_yen = read_sql_capped("SELECT NORM_VN('Yến Sào') AS norm_val", eng_yen)
        self.assertFalse(is_trunc_yen)
        self.assertEqual(df_udf.iloc[0]["norm_val"], "yen sao")
        eng_yen.dispose()

        eng_choc, kn_choc, dial_choc, desc_choc, is_demo_choc = resolve_database_connection(
            use_demo=True,
            db_host="",
            db_port="3306",
            db_user="",
            db_pass="",
            db_name="demo_sqlite",
            use_ssl=False,
        )
        self.assertEqual(dial_choc, "SQLite")
        self.assertEqual(desc_choc, "SQLite In-Memory Demo")
        self.assertTrue(is_demo_choc)
        self.assertIsNone(kn_choc)
        df_choc, is_trunc_choc = read_sql_capped("SELECT ROUND_HALF_UP(2.5, 0) AS r", eng_choc)
        self.assertFalse(is_trunc_choc)
        self.assertEqual(float(df_choc.iloc[0]["r"]), 3.0)
        eng_choc.dispose()

        composed = compose_connection_schema("CREATE TABLE orders (id INT);", "Ghi chú riêng", kn_yen)
        self.assertIn("GHI CHÚ NGHIỆP VỤ BỔ SUNG", composed)
        self.assertIn("DATAMATE SEMANTIC KNOWLEDGE", composed)

    def test_augment_vietnamese_temporal_helper(self) -> None:
        teencode_q = augment_vietnamese_query_with_temporal("hnay dthu bnhieu")
        self.assertIn("Chuẩn hoá ý định tiếng Việt", teencode_q)
        eng_q = "Show monthly revenue trend"
        self.assertEqual(augment_vietnamese_query_with_temporal(eng_q), eng_q)

    def test_run_agent_preflight_unanswerable_returns_clean_governance_notice(self) -> None:
        engine, knowledge, *_ = resolve_database_connection(
            use_demo=False,
            db_host="",
            db_port="3306",
            db_user="",
            db_pass="",
            db_name="shop_ws",
            use_ssl=False,
            custom_workspace_dir=str(self._ws_dir),
        )
        client = _QueuedOpenAIClient([])  # Must not be called at all
        res = run_agent(
            user_query="Lãi ròng theo giá vốn hôm nay là bao nhiêu?",
            client=client,
            provider="Ollama (Local AI Offline)",
            model_name="qwen2.5-coder:3b",
            engine=engine,
            schema_context="",
            dialect="SQLite",
            datamate_knowledge=knowledge,
        )
        self.assertEqual(len(client.calls), 0)
        self.assertTrue(res.get("is_datamate_turn"))
        self.assertIsNone(res.get("error"))
        self.assertIsNone(res.get("df"))
        self.assertIn("🛡️", res.get("explanation", ""))
        self.assertEqual(res.get("evaluator", {}).get("verdict"), "UNANSWERABLE_BLOCKED")
        engine.dispose()

    def test_run_agent_repairs_flawed_sql_and_returns_bi_result(self) -> None:
        engine, knowledge, *_ = resolve_database_connection(
            use_demo=False,
            db_host="",
            db_port="3306",
            db_user="",
            db_pass="",
            db_name="shop_ws",
            use_ssl=False,
            custom_workspace_dir=str(self._ws_dir),
        )
        bad_json = json.dumps(
            {
                "answerable": True,
                "sql": "SELECT SUM(total_amount) AS rev FROM orders",  # Missing status filter on revenue!
            }
        )
        good_json = json.dumps(
            {
                "answerable": True,
                "sql": (
                    "SELECT product_name, SUM(total_amount) AS doanh_thu, COUNT(*) AS so_don "
                    "FROM orders WHERE status = 'completed' "
                    "GROUP BY product_name ORDER BY doanh_thu DESC"
                ),
            }
        )
        client = _QueuedOpenAIClient([bad_json, good_json])
        res = run_agent(
            user_query="dthu theo tung san pham ban dc hnay va trong thang",
            client=client,
            provider="Ollama (Local AI Offline)",
            model_name="qwen2.5-coder:3b",
            engine=engine,
            schema_context="",
            dialect="SQLite",
            enable_self_check=True,
            enable_auto_insights=True,
            datamate_knowledge=knowledge,
        )
        self.assertIsNone(res.get("error"))
        self.assertTrue(res.get("is_datamate_turn"))
        self.assertEqual(len(client.calls), 2)
        self.assertIsNotNone(res.get("df"))
        self.assertEqual(len(res["df"]), 3)
        self.assertIn("status = 'completed'", res.get("sql", ""))
        self.assertEqual(res.get("evaluator", {}).get("verdict"), "PASS")
        self.assertTrue(res.get("insights"))
        self.assertTrue(res.get("followups"))
        self.assertIn("planner", res.get("agent_trace", {}))
        self.assertIn("schema_linking", res.get("agent_trace", {}))
        self.assertIn("executor", res.get("agent_trace", {}))
        engine.dispose()

    def test_teencode_queries_not_misclassified_as_conversational(self) -> None:
        from src.analytics.heuristics import is_non_data_conversational

        for q in ("dthu hnay bnhiu", "món nào bán chạy", "công nợ khách"):
            self.assertFalse(is_non_data_conversational(q, schema_context=""))
        self.assertTrue(is_non_data_conversational("Tôi bị ốm rồi", schema_context=""))

    def test_ground_query_entities_ignores_generic_query_nouns(self) -> None:
        from datamate.schema_context import ground_query_entities

        ws_dir = self._tmp_dir / "yen_sao_ws"
        ws_dir.mkdir(parents=True, exist_ok=True)
        (ws_dir / "don_hang.csv").write_text(
            "ma_don,ngay,ten_san_pham,thanh_tien,trang_thai\n"
            "1,2026-10-01,Yến chưng sẵn,500000,Hoàn thành\n"
            "2,2026-10-02,Tổ yến thô,1800000,Hoàn thành\n",
            encoding="utf-8",
        )
        engine, knowledge, *_ = resolve_database_connection(
            use_demo=False,
            db_host="",
            db_port="3306",
            db_user="",
            db_pass="",
            db_name="yen_sao_ws",
            use_ssl=False,
            custom_workspace_dir=str(ws_dir),
        )
        matches = ground_query_entities("Tổng doanh thu các sản phẩm yến sào", knowledge)
        matched_vals = [val for _, _, val in matches]
        self.assertNotIn("Yến chưng sẵn", matched_vals)
        engine.dispose()

    def test_verify_sql_semantics_guards_and_repair_join_hints(self) -> None:
        from datamate.agent import (
            DataMateAgent,
            QuestionAnalysis,
            verify_sql_semantics,
        )
        from datamate.schema_context import ground_query_entities
        from datamate.sql_executor import SQLExecutionResult

        ws_dir = self._tmp_dir / "multi_tbl_ws"
        ws_dir.mkdir(parents=True, exist_ok=True)
        (ws_dir / "orders.csv").write_text(
            "order_id,order_date,customer_name,product_name,total_amount,status\n"
            "1,2026-10-01,An,Trà đào,50000,completed\n"
            "2,2026-10-03,Bình,Cà phê sữa,35000,completed\n"
            "3,2026-10-04,An,Cà phê đen,30000,completed\n",
            encoding="utf-8",
        )
        (ws_dir / "categories.csv").write_text(
            "product_name,category_name\n"
            "Trà đào,Trà trái cây\n"
            "Cà phê sữa,Cà phê\n"
            "Cà phê đen,Cà phê\n",
            encoding="utf-8",
        )
        engine, knowledge, *_ = resolve_database_connection(
            use_demo=False,
            db_host="",
            db_port="3306",
            db_user="",
            db_pass="",
            db_name="multi_tbl_ws",
            use_ssl=False,
            custom_workspace_dir=str(ws_dir),
        )
        dummy_res = SQLExecutionResult(
            ok=True, sql="", columns=["val"], rows=[(100000,)], row_count=1
        )

        # Check 2b: spurious single-day filter on open-ended all-time question
        ok_2b, msg_2b, _ = verify_sql_semantics(
            sql="SELECT product_name, SUM(total_amount) FROM orders WHERE status = 'completed' AND order_date = '2026-10-04' GROUP BY product_name",
            sql_res=dummy_res,
            question="Tổng doanh thu theo sản phẩm?",
            knowledge=knowledge,
            analysis=QuestionAnalysis(expected_type="table", money_like=True),
        )
        self.assertFalse(ok_2b)
        self.assertIn("LỖI LỌC NGÀY THỪA", msg_2b)

        # Check 2: wrong literal day when bounded_period asks yesterday ('2026-10-03')
        ok_day, msg_day, _ = verify_sql_semantics(
            sql="SELECT SUM(total_amount) FROM orders WHERE status = 'completed' AND order_date = '2026-10-04'",
            sql_res=dummy_res,
            question="Doanh thu hôm qua là bao nhiêu?",
            knowledge=knowledge,
            analysis=QuestionAnalysis(
                expected_type="number",
                money_like=True,
                bounded_period=("2026-10-03", "2026-10-03"),
            ),
        )
        self.assertFalse(ok_day)
        self.assertIn("LỖI MỐC NGÀY", msg_day)

        # Check 4b: entity ranking string missing GROUP BY
        ok_4b, msg_4b, _ = verify_sql_semantics(
            sql="SELECT customer_name FROM orders WHERE status = 'completed' ORDER BY total_amount DESC LIMIT 1",
            sql_res=SQLExecutionResult(ok=True, sql="", columns=["customer_name"], rows=[("An",)], row_count=1),
            question="Khách hàng nào tổng chi tiêu cao nhất?",
            knowledge=knowledge,
            analysis=QuestionAnalysis(expected_type="string"),
        )
        self.assertFalse(ok_4b)
        self.assertIn("LỖI THIẾU GROUP BY", msg_4b)

        # Check 6b: dropped grounded cross-table entity filter
        q_cat = "Tổng tiền các món nhóm Trà trái cây?"
        ents = ground_query_entities(q_cat, knowledge)
        ok_6b, msg_6b, _ = verify_sql_semantics(
            sql="SELECT SUM(total_amount) FROM orders WHERE status = 'completed'",
            sql_res=dummy_res,
            question=q_cat,
            knowledge=knowledge,
            analysis=QuestionAnalysis(expected_type="number", money_like=True),
            entity_matches=ents,
        )
        self.assertFalse(ok_6b)
        self.assertIn("LỖI BỎ SÓT BỘ LỌC", msg_6b)

        # Repair prompt emits exact valid table names & dynamic JOIN ... ON ... hints
        agent = DataMateAgent(backend=SimpleNamespace(generate=lambda *a, **kw: "{}"))
        prompt_tbl = agent._build_repair_prompt(
            question="Tổng doanh thu?",
            bad_sql="SELECT SUM(total_amount) FROM fake_orders",
            reason="SQLite execution error: no such table: fake_orders",
            knowledge=knowledge,
        )
        self.assertIn("fake_orders", prompt_tbl)
        self.assertIn("`orders`", prompt_tbl)
        self.assertIn("`categories`", prompt_tbl)

        prompt_join_6b = agent._build_repair_prompt(
            question=q_cat,
            bad_sql="SELECT SUM(total_amount) FROM orders WHERE status = 'completed'",
            reason=msg_6b,
            knowledge=knowledge,
        )
        self.assertIn("JOIN categories ON orders.product_name = categories.product_name", prompt_join_6b)

        prompt_join_col = agent._build_repair_prompt(
            question=q_cat,
            bad_sql="SELECT SUM(total_amount) FROM orders WHERE categories.category_name = 'Trà trái cây'",
            reason="no such column: categories.category_name",
            knowledge=knowledge,
        )
        self.assertIn("JOIN categories ON orders.product_name = categories.product_name", prompt_join_col)
        engine.dispose()

    def test_awesome_chocolates_schema_gap_blocks_hallucination_without_blocking_valid_queries(self) -> None:
        import pandas as pd
        from src.database.schema import auto_extract_schema
        from src.llm.datamate_bridge import detect_legacy_schema_gap
        from src.llm.evaluator import evaluate_execution
        from src.llm.prompts import build_sql_prompt

        engine, knowledge, dialect, *_ = resolve_database_connection(
            use_demo=True,
            db_host="",
            db_port="3306",
            db_user="",
            db_pass="",
            db_name="awesome chocolates",
            use_ssl=False,
        )
        self.assertIsNone(knowledge)
        schema_txt = auto_extract_schema(engine)

        # Prompt must enforce honesty rather than fabricating substitute columns
        prompt_vi = build_sql_prompt(schema_txt, dialect, "Phân tích doanh thu theo độ tuổi", lang="vi")
        self.assertIn("UNANSWERABLE:", prompt_vi)
        self.assertNotIn("SMART ADAPTATION", prompt_vi)

        # Exact two bug-report queries on Awesome Chocolates must stop cleanly at preflight
        for bad_q in (
            "Liệt kê 5 khách hàng (CustomerID) có tỷ lệ hoàn trả đơn hàng (return rate) cao nhất.",
            "Phân tích doanh thu theo độ tuổi và giới tính của khách hàng.",
        ):
            client = _QueuedOpenAIClient([])
            res = run_agent(
                user_query=bad_q,
                client=client,
                provider="Ollama (Local AI Offline)",
                model_name="qwen2.5-coder:3b",
                engine=engine,
                schema_context=schema_txt,
                dialect=dialect,
            )
            self.assertEqual(len(client.calls), 0, f"Preflight should block before LLM call for: {bad_q}")
            self.assertIsNone(res.get("df"))
            self.assertIsNone(res.get("sql"))
            self.assertIn("🛡️", res.get("explanation", ""))
            self.assertEqual((res.get("evaluator") or {}).get("verdict"), "UNANSWERABLE_BLOCKED")
            self.assertTrue(res.get("followups"))

        # Valid queries on Awesome Chocolates & Employees must NOT be blocked
        for valid_q in (
            "Tính doanh thu, ước tính tổng giá vốn (Boxes * Cost_per_box) và biên lợi nhuận gộp theo từng Category.",
            "Thống kê số lượng ticket theo Kênh hỗ trợ (Channel) và Trạng thái (Status).",
            "Tỷ lệ ticket của nhóm khách hàng quay lại (CustomerType = 'Returned') là bao nhiêu?",
            "dthu sp Milk Bars tai India la bnhiu?",
        ):
            self.assertIsNone(
                detect_legacy_schema_gap(valid_q, engine=engine, schema_context=schema_txt, lang="vi"),
                f"Valid query falsely flagged as missing schema: {valid_q}",
            )

        employees_schema = (
            "Cơ sở dữ liệu bao gồm các bảng và cột sau:\n"
            "- Bảng `employees`: emp_no (INT), birth_date (DATE), gender (VARCHAR)\n"
            "- Bảng `salaries`: emp_no (INT), salary (INT), to_date (DATE)"
        )
        self.assertIsNone(
            detect_legacy_schema_gap(
                "So sánh mức lương theo giới tính và độ tuổi của nhân viên",
                engine=None,
                schema_context=employees_schema,
                lang="vi",
            )
        )

        # Unseen missing column handled via LLM returning UNANSWERABLE: ...
        # (route_and_plan -> SQL gen -> UNANSWERABLE)
        client_unans = _QueuedOpenAIClient(
            [
                "UNANSWERABLE: Bảng sales và geo không có cột ZipCode / mã bưu chính.",
                "UNANSWERABLE: Bảng sales và geo không có cột ZipCode / mã bưu chính.",
            ]
        )
        res_unans = run_agent(
            user_query="Thống kê doanh thu theo mã bưu chính ZipCode của khách hàng?",
            client=client_unans,
            provider="Ollama (Local AI Offline)",
            model_name="qwen2.5-coder:3b",
            engine=engine,
            schema_context=schema_txt,
            dialect=dialect,
        )
        self.assertIsNone(res_unans.get("df"))
        self.assertIsNone(res_unans.get("sql"))
        self.assertIn("🛡️", res_unans.get("explanation", ""))
        self.assertEqual((res_unans.get("evaluator") or {}).get("verdict"), "UNANSWERABLE_BLOCKED")

        # Evaluator defense-in-depth must also reject partial/hallucinated SQL on missing schema attrs
        ev = evaluate_execution(
            user_query="Phân tích doanh thu theo độ tuổi và giới tính của khách hàng.",
            sql_query="SELECT Product, SUM(Amount) FROM sales JOIN products ON sales.PID = products.PID GROUP BY Product",
            df=pd.DataFrame({"Product": ["Milk Bars"], "Total": [1000]}),
            schema_context=schema_txt,
            lang="vi",
        )
        self.assertEqual(ev.get("verdict"), "UNANSWERABLE_BLOCKED")
        self.assertEqual(ev.get("score"), 0)
        engine.dispose()

    def test_awesome_chocolates_crm_tickets_and_dimensions_not_hijacked(self) -> None:
        import pandas as pd
        from src.database.schema import auto_extract_schema
        from src.llm.agent import (
            auto_fix_chocolates_monthly_sales_query,
            auto_fix_chocolates_pnl_query,
            auto_fix_chocolates_team_sales_and_boxes_query,
            auto_fix_chocolates_top_rankings_query,
            auto_fix_chocolates_top_transactions_query,
            auto_fix_sales_performance_comparison_query,
            run_agent,
        )
        from src.llm.evaluator import evaluate_execution

        engine, _knowledge, dialect, *_ = resolve_database_connection(
            use_demo=True,
            db_host="",
            db_port="3306",
            db_user="",
            db_pass="",
            db_name="awesome chocolates",
            use_ssl=False,
        )
        schema_txt = auto_extract_schema(engine)

        # 1. End-to-end Q11 CRM tickets must NOT be hijacked by monthly_sales ("thời gian", "số lượng", "rep" in FirstReplyMinutes)
        q11 = (
            "Thống kê số lượng ticket theo Kênh hỗ trợ (Channel) và Trạng thái (Status), "
            "kèm thời gian phản hồi đầu tiên trung bình (FirstReplyMinutes)"
        )
        q11_sql = (
            "SELECT Channel, Status, COUNT(TicketID) AS TicketCount, "
            "ROUND(AVG(FirstReplyMinutes), 2) AS AvgFirstReplyMinutes "
            "FROM crm_tickets GROUP BY Channel, Status ORDER BY TicketCount DESC"
        )
        client_q11 = _QueuedOpenAIClient([
            "DIRECT_SQL: Query crm_tickets grouped by Channel and Status.",
            q11_sql,
        ])
        res_q11 = run_agent(
            user_query=q11,
            client=client_q11,
            provider="Ollama (Local AI Offline)",
            model_name="qwen2.5-coder:3b",
            engine=engine,
            schema_context=schema_txt,
            dialect=dialect,
        )
        self.assertIn("crm_tickets", (res_q11.get("sql") or "").lower())
        self.assertNotIn("salesperson", (res_q11.get("sql") or "").lower())
        df_q11 = res_q11.get("df")
        self.assertIsNotNone(df_q11)
        self.assertFalse(df_q11.empty)
        cols_q11 = {c.lower() for c in df_q11.columns}
        self.assertTrue({"channel", "status", "ticketcount", "avgfirstreplyminutes"}.issubset(cols_q11))

        # 2. Evaluator defense-in-depth rejects CRM ticket query if SQL drifted to sales/people, then repairs cleanly
        ev_drift = evaluate_execution(
            user_query=q11,
            sql_query="SELECT pe.Salesperson, SUM(s.Amount) FROM sales s JOIN people pe ON s.SPID = pe.SPID GROUP BY pe.Salesperson",
            df=pd.DataFrame({"Salesperson": ["A"], "Amount": [100]}),
            schema_context=schema_txt,
            lang="vi",
        )
        self.assertFalse(ev_drift["criteria"]["semantic_alignment"]["passed"])
        self.assertLess(ev_drift.get("score", 100), 100)

        client_drift = _QueuedOpenAIClient([
            "DIRECT_SQL: Ticket summary",
            "SELECT pe.Salesperson, SUM(s.Boxes) AS Boxes FROM sales s JOIN people pe ON s.SPID = pe.SPID GROUP BY pe.Salesperson",
            q11_sql,
        ])
        res_repaired = run_agent(
            user_query=q11,
            client=client_drift,
            provider="Ollama (Local AI Offline)",
            model_name="qwen2.5-coder:3b",
            engine=engine,
            schema_context=schema_txt,
            dialect=dialect,
        )
        self.assertIn("crm_tickets", (res_repaired.get("sql") or "").lower())
        self.assertEqual((res_repaired.get("evaluator") or {}).get("verdict"), "PASS")

        # 3. Direct preservation checks across Q1, Q3, Q5, Q7, Q9, Q10, Q12, Q13
        preservation_cases = [
            (
                "Tổng doanh thu và tổng số hộp (Boxes) theo từng quốc gia",
                "SELECT g.Geo, SUM(s.Amount) AS TotalAmount, SUM(s.Boxes) AS TotalBoxes FROM sales s JOIN geo g ON s.GeoID = g.GeoID GROUP BY g.Geo ORDER BY TotalAmount DESC",
            ),
            (
                "So sánh doanh thu trung bình trên mỗi hộp giữa các kích thước (Size) sản phẩm",
                "SELECT pr.Size, ROUND(CAST(SUM(s.Amount) AS FLOAT) / NULLIF(SUM(s.Boxes), 0), 2) AS AvgRevenuePerBox FROM sales s JOIN products pr ON s.PID = pr.PID GROUP BY pr.Size ORDER BY AvgRevenuePerBox DESC",
            ),
            (
                "Mỗi Team (Yummies, Delish, Jucies) có bao nhiêu nhân viên và tổng doanh thu bao nhiêu?",
                "SELECT pe.Team, COUNT(DISTINCT pe.SPID) AS NumEmployees, SUM(s.Amount) AS TotalRevenue FROM people pe LEFT JOIN sales s ON pe.SPID = s.SPID WHERE pe.Team IN ('Yummies', 'Delish', 'Jucies') GROUP BY pe.Team ORDER BY TotalRevenue DESC",
            ),
            (
                "Phân tích xu hướng doanh thu theo từng tháng từ 2021 đến 2023 và chỉ ra các tháng dị biệt (outliers)",
                "SELECT strftime('%Y-%m', s.SaleDate) AS Month, SUM(s.Amount) AS TotalRevenue FROM sales s GROUP BY Month ORDER BY Month ASC",
            ),
            (
                "Thống kê số lượng hộp bán được theo khu vực APAC và Europe",
                "SELECT g.Region, SUM(s.Boxes) AS TotalBoxes FROM sales s JOIN geo g ON s.GeoID = g.GeoID WHERE g.Region IN ('APAC', 'Europe') GROUP BY g.Region ORDER BY TotalBoxes DESC",
            ),
            (
                "Tính doanh thu, ước tính tổng giá vốn (Boxes * Cost_per_box) và biên lợi nhuận gộp theo từng Category",
                "SELECT pr.Category, SUM(s.Amount) AS TotalRevenue, SUM(s.Boxes * pr.Cost_per_box) AS TotalCOGS, ROUND((SUM(s.Amount) - SUM(s.Boxes * pr.Cost_per_box)) * 100.0 / NULLIF(SUM(s.Amount), 0), 2) AS GrossMarginPct FROM sales s JOIN products pr ON s.PID = pr.PID GROUP BY pr.Category ORDER BY TotalRevenue DESC",
            ),
            (
                "Khách hàng nào thuộc nhóm khách hàng mua lặp lại hoặc từng gửi ticket? Hãy thống kê tổng doanh thu, số giao dịch và số ticket của Top 10 CustomerID",
                "SELECT s.CustomerID, SUM(s.Amount) AS TotalRevenue, COUNT(*) AS NumTransactions, COUNT(DISTINCT t.TicketID) AS NumTickets FROM sales s LEFT JOIN crm_tickets t ON s.CustomerID = t.CustomerID GROUP BY s.CustomerID ORDER BY TotalRevenue DESC LIMIT 10",
            ),
        ]
        for q_text, sql_text in preservation_cases:
            for fn in (
                lambda s, q: auto_fix_chocolates_pnl_query(s, q, dialect="SQLite"),
                lambda s, q: auto_fix_chocolates_monthly_sales_query(s, q, dialect="SQLite"),
                lambda s, q: auto_fix_sales_performance_comparison_query(s, q, dialect="SQLite"),
                lambda s, q: auto_fix_chocolates_team_sales_and_boxes_query(s, q, dialect="SQLite"),
                lambda s, q: auto_fix_chocolates_top_transactions_query(s, q, dialect="SQLite"),
                lambda s, q: auto_fix_chocolates_top_rankings_query(s, q, dialect="SQLite"),
            ):
                self.assertEqual(fn(sql_text, q_text), sql_text, f"Auto-fix unexpectedly altered SQL for: {q_text}")

        # 4. Edge repairs keep ALL requested metrics/ranges/dimensions
        q1_fixed = auto_fix_chocolates_top_rankings_query(
            "SELECT g.Geo, SUM(Amount) AS TotalAmount FROM sales JOIN geo g USING(GeoID) GROUP BY g.Geo",
            "Tổng doanh thu và tổng số hộp (Boxes) theo từng quốc gia",
            dialect="SQLite",
        ).lower()
        self.assertIn("sum(s.amount)", q1_fixed)
        self.assertIn("sum(s.boxes)", q1_fixed)

        q7_fixed = auto_fix_chocolates_monthly_sales_query(
            "SELECT strftime('%m', s.SaleDate) AS Month, SUM(s.Amount) FROM sales s WHERE YEAR(s.SaleDate) = 2021 GROUP BY Month",
            "Phân tích xu hướng doanh thu theo từng tháng từ 2021 đến 2023 và chỉ ra các tháng dị biệt (outliers)",
            dialect="SQLite",
        ).lower()
        self.assertIn("between '2021' and '2023'", q7_fixed)
        self.assertIn("%y-%m", q7_fixed)

        q10_fixed = auto_fix_chocolates_pnl_query(
            "SELECT pr.Category, SUM(s.Amount) FROM sales s JOIN products pr ON s.PID = pr.PID GROUP BY pr.Category",
            "Tính doanh thu, ước tính tổng giá vốn (Boxes * Cost_per_box) và biên lợi nhuận gộp theo từng Category",
            dialect="SQLite",
        ).lower()
        self.assertIn("pr.category", q10_fixed)
        self.assertIn("cost_per_box", q10_fixed)
        engine.dispose()

    def test_q3_q5_q9_q11_q12_unassigned_team_and_evaluator_guards(self) -> None:
        import pandas as pd
        from sqlalchemy import inspect, text
        from src.database.demo_data import build_demo_engine
        from src.llm.agent import auto_fix_chocolates_unassigned_team_filter
        from src.llm.client import call_llm
        from src.llm.evaluator import evaluate_execution
        from src.llm.few_shot_selector import select_dynamic_few_shots
        from src.llm.prompts import get_db_specific_rules, get_targeted_hint
        from src.llm.sql_sanitizer import sanitize_sql_for_live_db

        engine = build_demo_engine()
        insp = inspect(engine)
        schema_lines = ["CSDL: SQLite Demo"]
        for t in insp.get_table_names():
            cols = [c["name"] for c in insp.get_columns(t)]
            schema_lines.append(f"- Bảng `{t}`: {', '.join(cols)}")
        schema_txt = "\n".join(schema_lines)

        # 1. auto_fix_chocolates_unassigned_team_filter must insert WHERE BEFORE \nGROUP BY and execute cleanly
        q5_sql = (
            "SELECT pe.Team, COUNT(DISTINCT pe.SPID) AS Employees, SUM(s.Amount) AS TotalSales, SUM(s.Boxes) AS TotalBoxes\n"
            "FROM people pe\n"
            "JOIN sales s ON pe.SPID = s.SPID\n"
            "GROUP BY pe.Team\n"
            "ORDER BY TotalSales DESC"
        )
        fixed_q5 = auto_fix_chocolates_unassigned_team_filter(q5_sql, "Mỗi Team có bao nhiêu nhân viên và doanh thu?", dialect="SQLite")
        self.assertLess(fixed_q5.lower().index("where"), fixed_q5.lower().index("group by"))
        with engine.connect() as conn:
            df_q5 = pd.read_sql(text(fixed_q5), conn)
        self.assertFalse(df_q5.empty)
        self.assertTrue((df_q5["Team"].astype(str).str.strip() != "").all())

        # Alias p.Team preserved and CTE untouched at outer tail
        q_alias_sql = "SELECT p.Team, SUM(s.Amount) AS TotalSales\nFROM sales s\nJOIN people p ON s.SPID = p.SPID\nGROUP BY p.Team"
        fixed_alias = auto_fix_chocolates_unassigned_team_filter(q_alias_sql, dialect="SQLite")
        self.assertIn("p.Team != ''", fixed_alias)
        self.assertLess(fixed_alias.lower().index("where"), fixed_alias.lower().index("group by"))

        # 2. sql_sanitizer must NOT silently replace unknown table on Chocolates with fake products.Cost_per_box
        fake_tbl_sql = "SELECT r.Region, SUM(s.Amount) FROM sales s JOIN regions r ON s.GeoID = r.GeoID GROUP BY r.Region"
        sanitized = sanitize_sql_for_live_db(fake_tbl_sql, engine, schema_txt, user_query="Doanh thu theo Region", dialect="SQLite")
        self.assertNotIn("Cost_per_box", sanitized)
        self.assertNotIn("AS Nhom", sanitized)

        # 3. Evaluator Critic catches Q5/Q9 products.Category drift, Q3 AVG(Amount) per-box misuse, and TIMESTAMPDIFF on FirstReplyMinutes
        fake_df = pd.DataFrame({"Nhom": ["Bars", "Bites"], "TongGiaTri": [100.0, 80.0], "SoLuong": [10, 12]})
        ev_q5 = evaluate_execution(
            "Mỗi đội ngũ (Team) có bao nhiêu nhân viên, đóng góp tổng doanh thu và số hộp là bao nhiêu?",
            "SELECT Category AS Nhom, ROUND(SUM(Cost_per_box), 2) AS TongGiaTri, COUNT(*) AS SoLuong FROM products GROUP BY Category",
            fake_df, schema_context=schema_txt, lang="vi",
        )
        self.assertNotEqual(ev_q5["verdict"], "PASS")

        ev_q9 = evaluate_execution(
            "Phân bổ doanh thu theo từng Category sản phẩm và theo từng Khu vực (Region IN ('APAC', 'Europe')).",
            "SELECT Category AS Nhom, ROUND(SUM(Cost_per_box), 2) AS TongGiaTri, COUNT(*) AS SoLuong FROM products GROUP BY Category",
            fake_df, schema_context=schema_txt, lang="vi",
        )
        self.assertNotEqual(ev_q9["verdict"], "PASS")

        q3_bad_df = pd.DataFrame({"Size": ["SMALL", "LARGE"], "TotalRevenue": [1000.0, 2000.0], "AverageRevenuePerBox": [200.0, 250.0]})
        ev_q3_bad = evaluate_execution(
            "Phân tích doanh thu theo kích thước sản phẩm (Size) và tính doanh thu trung bình trên mỗi hộp theo từng Size.",
            "SELECT pr.Size, SUM(s.Amount) AS TotalRevenue, AVG(s.Amount) AS AverageRevenuePerBox FROM sales s JOIN products pr ON s.PID = pr.PID GROUP BY pr.Size",
            q3_bad_df, schema_context=schema_txt, lang="vi",
        )
        self.assertNotEqual(ev_q3_bad["verdict"], "PASS")

        ev_q3_ok = evaluate_execution(
            "Phân tích doanh thu theo kích thước sản phẩm (Size) và tính doanh thu trung bình trên mỗi hộp theo từng Size.",
            "SELECT pr.Size, SUM(s.Amount) AS TotalRevenue, ROUND(SUM(s.Amount) * 1.0 / NULLIF(SUM(s.Boxes), 0), 2) AS AvgRevenuePerBox FROM sales s JOIN products pr ON s.PID = pr.PID GROUP BY pr.Size",
            q3_bad_df, schema_context=schema_txt, lang="vi",
        )
        self.assertEqual(ev_q3_ok["verdict"], "PASS")

        ev_q11_ts = evaluate_execution(
            "Thống kê số lượng ticket theo Channel và Status, kèm thời gian phản hồi đầu tiên trung bình (FirstReplyMinutes).",
            "SELECT t.Channel, t.Status, COUNT(*) AS TicketCount, AVG(TIMESTAMPDIFF(MINUTE, t.CreatedAt, t.FirstReplyMinutes)) AS AvgFirstReply FROM crm_tickets t GROUP BY t.Channel, t.Status",
            pd.DataFrame({"Channel": ["Email"], "Status": ["Solved"], "TicketCount": [10], "AvgFirstReply": [None]}),
            schema_context=schema_txt, lang="vi",
        )
        self.assertNotEqual(ev_q11_ts["verdict"], "PASS")

        # 4. Q11/Q12 CRM isolation: no pe.Team hint hijack, concise CRM rules, and CRM-only few-shots
        q11 = "Thống kê số lượng ticket theo Kênh hỗ trợ (Channel) và Trạng thái (Status), kèm thời gian phản hồi đầu tiên trung bình (FirstReplyMinutes)"
        q12 = "So sánh tỷ lệ giải quyết xong (Status = 'Solved') và thời gian xử lý trung bình (FullResolveHours) giữa nhóm khách hàng mới (New) và khách hàng quay lại (Returned)"
        for q_crm in (q11, q12):
            hint_crm = get_targeted_hint(q_crm, schema_txt, dialect="SQLite")
            rules_crm = get_db_specific_rules(schema_txt, user_query=q_crm)
            fs_crm = select_dynamic_few_shots(q_crm, schema_context=schema_txt, dialect="SQLite", top_k=2)
            self.assertIn("crm_tickets", hint_crm.lower())
            self.assertNotIn("pe.team", hint_crm.lower())
            self.assertLess(len(rules_crm), 2000)
            self.assertTrue(fs_crm)
            for ex in fs_crm:
                self.assertIn("crm_tickets", (ex.get("selected_sql") or "").lower())

        # 4b. Q5 with 'đóng góp' + headcount + boxes must NOT be overwritten by auto_fix_contribution_percentage_query, and Q3/Q5/Q9 hints align accurately
        from src.llm.agent import auto_fix_contribution_percentage_query
        q5_txt = "Mỗi đội ngũ (Team) có bao nhiêu nhân viên, đóng góp tổng doanh thu và số hộp là bao nhiêu?"
        self.assertEqual(auto_fix_contribution_percentage_query(q5_sql, q5_txt, dialect="SQLite"), q5_sql)

        h_q3 = get_targeted_hint("Phân tích doanh thu theo kích thước sản phẩm (Size) và tính doanh thu trung bình trên mỗi hộp theo từng Size.", schema_txt, dialect="SQLite").lower()
        h_q5 = get_targeted_hint(q5_txt, schema_txt, dialect="SQLite").lower()
        h_q9 = get_targeted_hint("Phân bổ doanh thu theo từng Category sản phẩm và theo từng Khu vực (Region IN ('APAC', 'Europe')).", schema_txt, dialect="SQLite").lower()
        self.assertIn("pr.size", h_q3)
        self.assertIn("sum(s.boxes)", h_q3)
        self.assertIn("count(distinct pe.spid)", h_q5)
        self.assertIn("sum(s.boxes)", h_q5)
        self.assertIn("g.region", h_q9)
        self.assertIn("pr.category", h_q9)

        # 5. Ollama client sets deterministic temperature & enlarged num_ctx
        q_client = _QueuedOpenAIClient(["SELECT 1"])
        out_txt, err_txt = call_llm(q_client, "Ollama (Local AI Offline)", "qwen2.5-coder:3b", "SELECT 1")
        self.assertIsNone(err_txt)
        self.assertEqual(out_txt, "SELECT 1")
        self.assertEqual(q_client.calls[0].get("temperature"), 0.1)
        self.assertEqual(((q_client.calls[0].get("extra_body") or {}).get("options") or {}).get("num_ctx"), 12288)
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
