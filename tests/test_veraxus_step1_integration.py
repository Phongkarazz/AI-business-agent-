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


if __name__ == "__main__":
    unittest.main()
