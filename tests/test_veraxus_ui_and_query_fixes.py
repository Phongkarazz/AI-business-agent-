"""Regression tests for Streamlit deploy unpack compat and all 8 Veraxus query/UI/insight fixes."""

import pathlib
import sqlite3
import tempfile
import unittest

import pandas as pd

from datamate.agent import (
    AgentConfig,
    DataMateAgent,
    _select_rulebook_prompt,
    build_catalog_listing_sql_spec,
    build_entity_and_metric_listing_sql_spec,
    classify_expected_type,
    extract_temporal_context,
    is_false_llm_unanswerable,
    verify_sql_semantics,
)
from datamate.llm_backend import MockLLMBackend
from datamate.loader import _parse_raw_sheet, _parse_raw_sheet_v2, load_business_workspace
from datamate.schema_context import build_workspace_knowledge, ground_query_entities
from datamate.sql_executor import SQLExecutionResult, execute_sql_safe
from src.analytics.heuristics import (
    detect_analysis_entity_type,
    generate_hypothesis_tree,
    generate_persona_action_plan,
    is_id_like,
    is_vnd_context_dataframe,
    normalize_diagnostic_dataframe,
    split_insight_sections,
)
from src.llm.datamate_bridge import build_datamate_suggested_questions, run_datamate_enhanced_turn


class VeraxusUiAndQueryFixesTests(unittest.TestCase):
    def test_loader_parse_raw_sheet_backward_compat_and_v2(self) -> None:
        raw_rows = [
            ["Báo cáo tháng 03/2026"],
            ["Phòng", "Điện mới", "Tiền phòng"],
            ["P.01", 1200, 3500000],
            ["Tổng cộng", 1200, 3500000],
        ]
        legacy = _parse_raw_sheet(raw_rows, sheet_year=2026)
        v2 = _parse_raw_sheet_v2(raw_rows, sheet_year=2026)
        self.assertIsNotNone(legacy)
        self.assertIsNotNone(v2)
        self.assertEqual(len(legacy), 5)
        self.assertEqual(len(v2), 7)
        self.assertEqual(legacy[0], ["Phòng", "Điện mới", "Tiền phòng"])
        self.assertEqual(legacy[:5], v2[:5])

    def test_phone_leading_zero_restoration_csv_and_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bdir = pathlib.Path(tmp) / "shop_phone"
            cache = pathlib.Path(tmp) / "cache"
            bdir.mkdir()
            (bdir / "danh_ba.csv").write_text(
                "ho_ten,sdt\nHoàng Minh Châu,368112233\nNguyễn Văn A,0912345678\n",
                encoding="utf-8",
            )
            (bdir / "lich_thue.csv").write_text(
                "ma_do,sdt,ngay_nhan\nGD01,0368112233,2026-03-04\nGD01,0987654321,2026-03-05\n",
                encoding="utf-8",
            )
            ws = load_business_workspace(bdir, cache_dir=cache, force_rebuild=True)
            conn = ws.open_connection()
            try:
                rows = conn.execute(
                    """
                    SELECT lt.ma_do, COALESCE(db.ho_ten, 'Khách: ' || lt.sdt) AS khach
                    FROM lich_thue lt
                    LEFT JOIN danh_ba db ON lt.sdt = db.sdt
                    ORDER BY lt.ngay_nhan
                    """
                ).fetchall()
            finally:
                conn.close()
            self.assertEqual(rows[0][1], "Hoàng Minh Châu")
            self.assertEqual(rows[1][1], "Khách: 0987654321")

            # Also verify SQLite INTEGER phone normalization
            bdir_sql = pathlib.Path(tmp) / "shop_sql"
            bdir_sql.mkdir()
            src_db = bdir_sql / "raw.sqlite"
            sc = sqlite3.connect(src_db)
            sc.execute("CREATE TABLE danhbakhach (ho_ten TEXT, hay_goi TEXT, dien_thoai INTEGER)")
            sc.execute("INSERT INTO danhbakhach VALUES ('Lê Thu Thảo', 'Thảo tiệm hoa', 839112244)")
            sc.execute("INSERT INTO danhbakhach VALUES ('Trần Mai', 'Mai', 912345678)")
            sc.commit()
            sc.close()

            ws_sql = load_business_workspace(bdir_sql, cache_dir=cache / "sql", force_rebuild=True)
            c2 = ws_sql.open_connection()
            try:
                phones = [r[0] for r in c2.execute("SELECT dien_thoai FROM danhbakhach ORDER BY ho_ten").fetchall()]
            finally:
                c2.close()
            self.assertEqual(phones, ["0839112244", "0912345678"])

    def test_nickname_fk_discovery_and_alias_repair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bdir = pathlib.Path(tmp) / "spa_db"
            cache = pathlib.Path(tmp) / "cache"
            bdir.mkdir()
            (bdir / "danhsachtho.csv").write_text(
                "ho_ten,ten_goi\nNguyễn Văn Tí,Tí\nTrần Thị Ý,Ý\nLê Hoàng Bi,Bi\n",
                encoding="utf-8",
            )
            (bdir / "danhbakhach.csv").write_text(
                "ho_ten,hay_goi,dien_thoai\nLê Thu Thảo,Thảo tiệm hoa,839112244\nPhạm Lan,Lan tiệm vàng,912000111\n",
                encoding="utf-8",
            )
            (bdir / "sothu.csv").write_text(
                "ngay,tho,khach,tien\n2026-03-01,Tí,Thảo tiệm hoa,500000\n2026-03-02,Ý,Lan tiệm vàng,300000\n2026-03-03,Tí,Khách vãng lai,200000\n",
                encoding="utf-8",
            )
            ws = load_business_workspace(bdir, cache_dir=cache, force_rebuild=True)
            know = build_workspace_knowledge(ws)
            join_str = " | ".join(know.join_graph)
            self.assertIn("danhsachtho.ten_goi", join_str)
            self.assertIn("sothu.tho", join_str)
            self.assertIn("danhbakhach.hay_goi", join_str)
            self.assertIn("sothu.khach", join_str)
            self.assertIn("LEFT JOIN", join_str)

            dm = DataMateAgent()
            repair = dm._build_repair_prompt(
                question="Top 5 thợ chính đem về tổng tiền dịch vụ cao nhất kèm doanh thu từng người?",
                bad_sql="SELECT t3.ho_ten, SUM(t1.tien) FROM sothu t1 JOIN danhsachtho t3 ON t1.tho = t3.tho GROUP BY t3.ho_ten",
                reason="no such column: t3.tho",
                knowledge=know,
                temporal_summary="",
            )
            self.assertIn("Alias `t3` trỏ tới bảng `danhsachtho`", repair)
            self.assertIn("ten_goi", repair)

            followups = build_datamate_suggested_questions(know, lang="vi")
            for fq in followups:
                self.assertNotIn("ds_phong", fq)
                self.assertNotIn("gia_thue", fq)

    def test_catalog_listing_guard_does_not_misfire_on_customer_purchases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bdir = pathlib.Path(tmp) / "shop_biz"
            cache = pathlib.Path(tmp) / "cache"
            bdir.mkdir()
            (bdir / "khach_hang.csv").write_text(
                "ma_kh,ten_kh\nKH01,Phan Thanh Trúc\nKH02,Đặng Quốc Huy\n",
                encoding="utf-8",
            )
            (bdir / "san_pham.csv").write_text(
                "ma_sp,ten_sp,danh_muc\nSP01,Tôm sú,hải sản\nSP02,Khô mực,đồ khô\n",
                encoding="utf-8",
            )
            (bdir / "don_hang.csv").write_text(
                "ma_chung_tu,ma_kh,ngay_mua,tinh_trang\nDH01,KH01,2026-02-10,completed\nDH02,KH02,2026-02-12,cancelled\n",
                encoding="utf-8",
            )
            (bdir / "chi_tiet_don.csv").write_text(
                "ma_don_hang,ma_mat_hang,so_luong,tien_hang\nDH01,SP01,2,200000\nDH02,SP02,1,150000\n",
                encoding="utf-8",
            )
            ws = load_business_workspace(bdir, cache_dir=cache, force_rebuild=True)
            know = build_workspace_knowledge(ws)
            q_cust = "Chi tiết các sản phẩm mà khách hàng Phan Thanh Trúc đã mua là gì?"
            an = classify_expected_type(q_cust)
            ents = ground_query_entities(q_cust, know)
            self.assertIsNone(build_catalog_listing_sql_spec(q_cust, know, an, ents))

            sys_p = _select_rulebook_prompt(q_cust, "2026-02-28", know, an, ents)
            self.assertIn("tinh_trang NOT IN", sys_p)

            # Check single-category percent rule & entity grounding on 'nhóm hải sản'
            q_pct = "Xem giúp tháng 2/2026 nhóm hải sản chiếm bao nhiêu % doanh thu?"
            an_pct = classify_expected_type(q_pct)
            ents_pct = ground_query_entities(q_pct, know)
            self.assertTrue(any(e[2] == "hải sản" for e in ents_pct))
            sys_pct = _select_rulebook_prompt(q_pct, "2026-02-28", know, an_pct, ents_pct)
            self.assertIn("CASE WHEN NORM_VN", sys_pct)

    def test_multi_period_history_collapse_guard_and_clean_followups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bdir = pathlib.Path(tmp) / "phong_tro"
            cache = pathlib.Path(tmp) / "cache"
            bdir.mkdir()
            (bdir / "ds_phong.csv").write_text(
                "phong,gia_thue,dien_cu,dien_moi\nP.09 (lầu 2),3000000,100,150\nP.10 (lầu 2),3200000,200,260\n",
                encoding="utf-8",
            )
            # Simulate multi-sheet merged table via SQLite with source_sheet
            with sqlite3.connect(bdir / "so_phong.sqlite") as conn:
                conn.execute(
                    "CREATE TABLE dien_nuoc (phong TEXT, dien_moi REAL, nuoc_moi REAL, tien_phong REAL, source_sheet TEXT)"
                )
                conn.execute("INSERT INTO dien_nuoc VALUES ('P.09 (lầu 2)', 150, 20, 3500000, 'T7.2025')")
                conn.execute("INSERT INTO dien_nuoc VALUES ('P.09 (lầu 2)', 190, 25, 3600000, 'T8.2025')")
                conn.commit()

            ws = load_business_workspace(bdir, cache_dir=cache, force_rebuild=True)
            know = build_workspace_knowledge(ws)
            self.assertIn("source_sheet", know.schema_prompt)

            q_hist = "Liệt kê lịch sử chỉ số điện mới, nước mới và tiền đã thu của phòng 9 qua các kỳ"
            an_hist = classify_expected_type(q_hist)
            bad_res = SQLExecutionResult(
                ok=True,
                sql="SELECT phong, SUM(dien_moi), SUM(nuoc_moi), SUM(tien_phong) FROM dien_nuoc WHERE phong LIKE '%09%' GROUP BY phong",
                columns=["phong", "dien_moi", "nuoc_moi", "tien_phong"],
                rows=[("P.09 (lầu 2)", 340.0, 45.0, 7100000.0)],
                row_count=1,
            )
            ok, msg, fatal = verify_sql_semantics(bad_res.sql, bad_res, q_hist, know, an_hist)
            self.assertFalse(ok)
            self.assertTrue(fatal)
            self.assertIn("source_sheet", msg)

            # Followup pills must not expose snake_case identifiers
            followups = build_datamate_suggested_questions(know, lang="vi")
            for fq in followups:
                self.assertNotIn("ds_phong", fq)
                self.assertNotIn("gia_thue", fq)

    def test_debt_column_not_id_like_and_customer_insight_pronouns(self) -> None:
        self.assertFalse(is_id_like("no"))
        self.assertFalse(is_id_like("con_no"))
        self.assertFalse(is_id_like("cong_no"))
        self.assertFalse(is_id_like("tong_no"))
        self.assertTrue(is_id_like("emp_no"))
        self.assertTrue(is_id_like("dept_no"))
        self.assertTrue(is_id_like("order_no"))

        df_debt = pd.DataFrame(
            {
                "khach_hang_ten": [
                    "Phan Thanh Trúc",
                    "Trần Minh Khôi",
                    "Lê Ngọc Hân",
                    "Phạm Quốc Bảo",
                    "Đặng Quốc Huy",
                ],
                "con_no": [1946000, 1250000, 820000, 380250, 116000],
            }
        )
        norm_df = normalize_diagnostic_dataframe(df_debt, user_query="Khách hàng nào còn công nợ chưa thanh toán nhiều nhất?")
        self.assertIn("con_no", norm_df.columns)
        self.assertNotIn("RecordCount", norm_df.columns)
        self.assertEqual(detect_analysis_entity_type(df_debt, "Khách hàng nào còn công nợ?", "khach_hang_ten"), "customer")
        self.assertTrue(is_vnd_context_dataframe(df_debt, "con_no"))
        self.assertFalse(is_vnd_context_dataframe(pd.DataFrame({"phong": ["P.09"], "dien_moi": [150]}), "dien_moi"))

        q = "Khách hàng nào còn công nợ chưa thanh toán nhiều nhất?"
        sections = split_insight_sections("", df=df_debt, user_query=q, is_en=False)
        tree = generate_hypothesis_tree(df_debt, user_query=q, is_en=False)
        ceo_plan = generate_persona_action_plan(df_debt, persona="ceo", user_query=q, is_en=False)
        lead_plan = generate_persona_action_plan(df_debt, persona="lead", user_query=q, is_en=False)

        full_text = "\n".join(
            [
                sections["anomaly"],
                sections["hypothesis"],
                sections["action_plan"],
                tree["summary_takeaway"],
                ceo_plan["role_title"],
                *ceo_plan["kpis"],
                *ceo_plan["actions"],
                lead_plan["role_title"],
                *lead_plan["kpis"],
                *lead_plan["actions"],
            ]
        )
        self.assertIn("Khách hàng **Phan Thanh Trúc**", sections["anomaly"])
        self.assertTrue(any(w in full_text.lower() for w in ("công nợ", "dư nợ")))
        for forbidden in (
            "Nhóm Phan Thanh Trúc",
            "Nhóm Đặng Quốc Huy",
            "1 bản ghi",
            "1.1 bản ghi",
            "gấp 1.00 lần Phan Thanh Trúc",
            "giữ đủ hàng nhóm bán chạy",
        ):
            self.assertNotIn(forbidden, full_text)

    def test_top_k_staff_revenue_join_and_false_unanswerable_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bdir = pathlib.Path(tmp) / "salon_top5"
            cache = pathlib.Path(tmp) / "cache"
            bdir.mkdir()
            (bdir / "banggia.csv").write_text(
                "dich_vu,nhom,gia\nCắt tóc,A,150000\nNhuộm tóc,B,500000\n",
                encoding="utf-8",
            )
            (bdir / "danhsachtho.csv").write_text(
                "ho_ten,ten_goi\n"
                "Nguyễn Văn Tí,Tí\n"
                "Trần Thị Su,Su\n"
                "Lê Minh Mít,Mít\n"
                "Phạm Thu Mi,Mi\n"
                "Hoàng Bảo Cún,Cún\n"
                "Vũ Gia Huy,Huy\n",
                encoding="utf-8",
            )
            (bdir / "danhbakhach.csv").write_text(
                "ho_ten,hay_goi,dien_thoai\n"
                "Lê Thu Thảo,Thảo,0901234567\n",
                encoding="utf-8",
            )
            (bdir / "sothu.csv").write_text(
                "ngay,khach,dich_vu,tho,tho_phu,tien,source_sheet\n"
                "2026-08-01,Thảo,Cắt tóc,Tí,Su,500000,2026\n"
                "2026-08-02,Khách lẻ,Nhuộm tóc,Tí,Mi,400000,2026\n"
                "2026-08-03,Khách lẻ,Nhuộm tóc,Mít,Mi,750000,2026\n"
                "2026-08-04,Thảo,Cắt tóc,Su,Tí,600000,2026\n"
                "2026-08-05,Khách lẻ,Cắt tóc,Mi,Cún,450000,2026\n"
                "2026-08-06,Khách lẻ,Cắt tóc,Cún,Huy,300000,2026\n"
                "2026-08-07,Khách lẻ,Cắt tóc,Huy,Tí,150000,2026\n",
                encoding="utf-8",
            )
            ws = load_business_workspace(bdir, cache_dir=cache, force_rebuild=True)
            know = build_workspace_knowledge(ws)
            q = "Top 5 thợ chính đem về tổng tiền dịch vụ cao nhất kèm doanh thu từng người?"
            an = classify_expected_type(q)

            spec = build_entity_and_metric_listing_sql_spec(q, know, an)
            self.assertIsNotNone(spec)
            sql = spec["suggested_sql"]
            self.assertEqual(spec["dim_table"], "danhsachtho")
            self.assertIn("LEFT JOIN danhsachtho", sql)
            self.assertIn("COALESCE(", sql)
            self.assertIn("LIMIT 5", sql)
            self.assertNotIn("danhbakhach", sql)

            res = execute_sql_safe(ws.open_connection, sql, valid_tables=know.valid_tables)
            self.assertTrue(res.ok, msg=res.error)
            self.assertEqual(res.row_count, 5)
            self.assertEqual(res.rows[0][0], "Nguyễn Văn Tí")
            self.assertEqual(res.rows[0][1], 900000)

            false_hint = is_false_llm_unanswerable(
                q,
                "Câu hỏi yêu cầu tính doanh thu theo người, nhưng bảng sothu không có cột ho_ten.",
                know,
                had_sql_attempt=False,
            )
            self.assertIsNotNone(false_hint)
            self.assertIn("danhsachtho.ho_ten", false_hint)

            # DataMateAgent recovers when mock LLM returns false unanswerable
            dm = DataMateAgent(
                backend=MockLLMBackend(
                    lambda _p, _s: '{"status": "unanswerable", "reason": "Bảng sothu không có cột ho_ten."}'
                ),
                config=AgentConfig(max_sql_retries=2),
            )
            agent_res = dm.answer_question({"id": "q_top5", "question": q, "as_of_date": "2026-08-31"}, know)
            self.assertEqual(agent_res.prediction["type"], "table")
            self.assertEqual(len(agent_res.prediction["answer"]["rows"]), 5)
            self.assertEqual(agent_res.prediction["answer"]["rows"][0][0], "Nguyễn Văn Tí")

            # Bridge also recovers via run_datamate_enhanced_turn even if mock OpenAI client returns false unanswerable
            from types import SimpleNamespace

            class _FakeCompletions:
                def create(self, **_kw):
                    return SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                message=SimpleNamespace(
                                    content='{"status": "unanswerable", "reason": "Bảng sothu không có cột ho_ten."}'
                                )
                            )
                        ]
                    )

            fake_cli = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions()))
            turn_out = run_datamate_enhanced_turn(
                q,
                client=fake_cli,
                provider="Ollama (Local AI Offline)",
                model_name="veraxus-coder:3b",
                knowledge=know,
                enable_self_check=True,
                enable_auto_insights=False,
                lang="vi",
            )
            self.assertIsNone(turn_out.get("error"))
            self.assertIsNotNone(turn_out.get("df"))
            self.assertEqual(len(turn_out["df"]), 5)
            self.assertEqual(turn_out["df"].iloc[0, 0], "Nguyễn Văn Tí")


if __name__ == "__main__":
    unittest.main()
