"""Unit tests for Stage 2: Preflight de-falsing, Semantic Compiler, Probes, Python Sandbox & Hybrid Agent."""

from __future__ import annotations

import pathlib
import tempfile
import unittest

import openpyxl

from datamate.agent import (
    AgentConfig,
    DataMateAgent,
    QuestionAnalysis,
    _check_subquery_column_capture,
    check_preflight_unanswerable,
    classify_expected_type,
    extract_temporal_context,
    format_sql_result,
    resolve_conversational_retraction,
    verify_sql_semantics,
)
from datamate.llm_backend import MockLLMBackend
from datamate.loader import load_business_workspace
from datamate.python_sandbox import execute_python_safe, validate_sandbox_python
from datamate.schema_context import (
    build_focused_schema_prompt,
    build_workspace_knowledge,
    ground_query_entities,
    run_deterministic_probes,
)
from datamate.sql_executor import SQLExecutionResult, adapt_sql_to_sqlite, heal_datetime_comparisons


class TestStage2HybridEngine(unittest.TestCase):
    def test_preflight_defalsing_and_true_positive_preservation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            bdir = root / "sme_stage2"
            bdir.mkdir()

            # Table with cham_cong + nghi_phep, product 'Bia Sài Gòn Xanh 330', lich_thue with short 'khach',
            # and sothutien with zero-padded 'P.09 (lầu 2)'
            wb = openpyxl.Workbook()
            sh_att = wb.active
            sh_att.title = "Chấm công"
            sh_att.append(["BẢNG CHẤM CÔNG | P: nghỉ có phép | K: nghỉ không phép"])
            sh_att.append(["Mã NV", "Họ tên", "Vào/Ra"] + [str(d) for d in range(1, 32)])
            sh_att.append(["NV01", "Nguyễn An", "Vào", "08:00", "P"] + [None] * 29)
            sh_np = wb.create_sheet("Nghỉ phép")
            sh_np.append(["Mã NV", "Loại", "Ngày"])
            sh_np.append(["NV01", "P", "2026-03-02"])
            sh_lt = wb.create_sheet("Lịch thuê")
            sh_lt.append(["Phiếu", "Khách", "Mã đồ", "Ngày lấy"])
            sh_lt.append(["P001", "Lâm Mỹ", "VC22", "2026-03-05"])
            sh_ban = wb.create_sheet("Sổ bán hàng")
            sh_ban.append(["Mã đơn", "Ngày", "Tên hàng", "Thành tiền", "Trạng thái"])
            sh_ban.append(["D01", "15/11/2025", "Bia Sài Gòn Xanh 330", "240k", "Hoàn thành"])
            sh_pt = wb.create_sheet("Sổ thu tiền")
            sh_pt.append(["Phòng", "Tên", "Điện mới", "Ngày thu"])
            sh_pt.append(["P.09 (lầu 2)", "Tuyết Hưng", "7781", "21/10/2025"])
            wb.save(bdir / "Data.xlsx")

            ws = load_business_workspace(bdir, cache_dir=root / "cache", force_rebuild=True)
            know = build_workspace_knowledge(ws)

            self.assertTrue(know.capabilities["has_customers"])
            self.assertTrue(know.capabilities["has_attendance"])

            # All 4 previous false positives must return None (answerable)
            for q_ok, as_of in (
                ("kho còn bao nhiêu tiền vốn nằm ở hàng lấy từ bên Giang Huệ?", "2026-06-06"),
                ("hôm cả cty nhiều người nghỉ phép nhất tháng này, có bao nhiêu người đi làm", "2026-03-10"),
                ("bia sài gòn xanh 330 bán nguyên thùng quý 4/2025 dc bnhiu tiền", "2026-07-31"),
                ("tiệm có giao bộ VC22 cho khách nào ko, tuần rồi?", "2026-03-11"),
            ):
                ana = classify_expected_type(q_ok)
                self.assertIsNone(
                    check_preflight_unanswerable(q_ok, as_of, know, ana),
                    msg=f"False unanswerable on: {q_ok}",
                )

            # Room 9 zero-padded matching
            ent_room = ground_query_entities("phòng 9 tiền điện tháng 10/2025 hết bao nhiêu?", know)
            self.assertTrue(any(v == "P.09 (lầu 2)" for _, _, v in ent_room))

            # Genuine weather & true missing city queries must still block
            self.assertIsNotNone(
                check_preflight_unanswerable("Hà Nội hôm nay có mưa không?", "2026-03-11", know, QuestionAnalysis("boolean"))
            )
            self.assertIsNotNone(
                check_preflight_unanswerable("Doanh thu tại Hà Nội hôm nay là bao nhiêu?", "2026-03-11", know, QuestionAnalysis("number"))
            )

    def test_retraction_temporal_datetime_and_sql_healers(self) -> None:
        raw_q = "nhà mình để dành dc bnhiu tiền trong t5/2024 z\nà nhầm, t6/2024 nha"
        resolved_q, note = resolve_conversational_retraction(raw_q)
        self.assertIsNotNone(note)
        windows, _, bounded, _ = extract_temporal_context(resolved_q, "2026-08-31", None)
        self.assertEqual(bounded, ("2024-06-01", "2024-06-30"))
        self.assertEqual(len(windows), 1)

        sql_raw = "SELECT ROUND_HALF_UP(SUM(CASE WHEN s.status = 'Đã hủy đơn' THEN 1 ELSE 0 END) * 100.0 / COUNT(DISTINCT s.ma_hoa_don) * 100.0, 2) FROM sobanhang s WHERE s.gio BETWEEN '2025-06-01' AND '2025-06-30'"
        adapted = adapt_sql_to_sqlite(sql_raw)
        self.assertNotIn("* 100.0 / COUNT(DISTINCT s.ma_hoa_don) * 100.0", adapted)
        healed = heal_datetime_comparisons(adapted, datetime_columns=("gio",))
        self.assertIn("BETWEEN '2025-06-01' AND '2025-06-30 23:59:59'", healed)

    def test_semantic_verifier_blocks_contradictory_cancel_where_and_wrong_delivery_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            bdir = root / "biz_verify"
            bdir.mkdir()
            (bdir / "sobanhang.csv").write_text(
                "ma_hoa_don,gio,ten_hang,thanh_tien,status\n"
                "HD01,01/06/2025 08:30:00,Cà phê,30000,Đã hủy đơn\n"
                "HD01,01/06/2025 08:30:00,Bánh,20000,Đã hủy đơn\n"
                "HD02,02/06/2025 09:00:00,Trà,25000,đã xong\n",
                encoding="utf-8",
            )
            (bdir / "bang_ke_phieu_giao_hang.csv").write_text(
                "ngay_giao_hang,ma_don_hang,lan_giao,ten_hang_hoa\n"
                "02/06/2025,HD02,1,Trà\n",
                encoding="utf-8",
            )
            ws = load_business_workspace(bdir, cache_dir=root / "cache", force_rebuild=True)
            know = build_workspace_knowledge(ws)

            bad_cancel_sql = "SELECT SUM(CASE WHEN status = 'Đã hủy đơn' THEN 1 ELSE 0 END) * 100.0 / COUNT(DISTINCT ma_hoa_don) FROM sobanhang WHERE status NOT IN ('hủy', 'Đã hủy đơn')"
            ok_c, msg_c, fatal_c = verify_sql_semantics(
                bad_cancel_sql,
                SQLExecutionResult(True, bad_cancel_sql, ["x"], [(0.0,)], 1),
                "tỉ lệ huỷ đơn tháng 6/2025 là nhiêu %",
                know,
                classify_expected_type("tỉ lệ huỷ đơn tháng 6/2025 là nhiêu %"),
            )
            self.assertFalse(ok_c)
            self.assertTrue(fatal_c)
            self.assertIn("NOT IN", msg_c)

            bad_deliv_sql = "SELECT COUNT(DISTINCT ma_hoa_don) FROM sobanhang WHERE status = 'đã xong'"
            ok_d, msg_d, fatal_d = verify_sql_semantics(
                bad_deliv_sql,
                SQLExecutionResult(True, bad_deliv_sql, ["c"], [(1,)], 1),
                "tháng này cửa hàng đã chở giao bao nhiêu đợt hàng cho khách nhỉ",
                know,
                classify_expected_type("tháng này cửa hàng đã chở giao bao nhiêu đợt hàng cho khách nhỉ"),
            )
            self.assertFalse(ok_d)
            self.assertTrue(fatal_d)
            self.assertIn("bang_ke_phieu_giao_hang", msg_d)

            # Even when querying bang_ke_phieu_giao_hang, omitting lan_giao must be caught
            bad_batch_sql = "SELECT COUNT(DISTINCT ma_don_hang) FROM bang_ke_phieu_giao_hang"
            ok_b, msg_b, fatal_b = verify_sql_semantics(
                bad_batch_sql,
                SQLExecutionResult(True, bad_batch_sql, ["c"], [(1,)], 1),
                "tháng này cửa hàng đã chở giao bao nhiêu đợt hàng cho khách nhỉ",
                know,
                classify_expected_type("tháng này cửa hàng đã chở giao bao nhiêu đợt hàng cho khách nhỉ"),
            )
            self.assertFalse(ok_b)
            self.assertTrue(fatal_b)
            self.assertIn("lan_giao", msg_b)

    def test_python_sandbox_safety_and_hybrid_probe_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            bdir = root / "pawn_compound"
            bdir.mkdir()
            (bdir / "socamdo.csv").write_text(
                "so_bn,ngay_cam,mon_cam,tien_cam\nBN0528,23/01/2026,Samsung S21,4200000\n",
                encoding="utf-8",
            )
            (bdir / "sothuchi.csv").write_text(
                "ngay,so_bn,noi_dung,so_tien\n18/05/2026,BN0528,thanh lý,3900000\n",
                encoding="utf-8",
            )
            (bdir / "sochi.csv").write_text(
                "ngay,khoan_chi,so_tien\n01/06/2026,Rau + an trua,527k + 338000\n",
                encoding="utf-8",
            )
            ws = load_business_workspace(bdir, cache_dir=root / "cache", force_rebuild=True)
            know = build_workspace_knowledge(ws)

            # Security checks
            self.assertIsNotNone(validate_sandbox_python("import os\nresult = os.listdir('.')"))
            self.assertIsNotNone(validate_sandbox_python("result = open('/etc/passwd').read()"))
            self.assertIsNotNone(validate_sandbox_python("result = ().__class__.__bases__"))

            # Compound expression parsing in read-only sandbox
            py_res = execute_python_safe(
                ws.open_connection,
                "df = query_df('SELECT so_tien FROM sochi')\nresult = round_half_up(df['so_tien'].apply(sum_compound_vn_nums).sum(), 0)",
                as_of_date="2026-06-30",
                valid_tables=know.valid_tables,
            )
            self.assertTrue(py_res.ok, msg=py_res.error)
            self.assertEqual(py_res.rows, [(865000,)])

            # Cross-table deterministic probe fetches BN0528 from both socamdo & sothuchi
            ents = ground_query_entities("món Samsung S21 cầm 23/01/2026 lúc thanh lý bán được bao nhiêu", know)
            probe_txt = run_deterministic_probes("món Samsung S21 cầm 23/01/2026 lúc thanh lý bán được bao nhiêu", know, ents)
            self.assertIn("socamdo", probe_txt)
            self.assertIn("sothuchi", probe_txt)
            self.assertIn("3900000", probe_txt)

            # End-to-end probe turn + Python Sandbox answer inside DataMateAgent
            seen_prompts = []

            def mock_hybrid(prompt: str, system_prompt: str) -> str:
                seen_prompts.append(prompt)
                if len(seen_prompts) == 1:
                    return '{"status": "probe", "probe_sql": "SELECT noi_dung, so_tien FROM sothuchi WHERE so_bn = \'BN0528\'"}'
                return '{"status": "ok", "python": "df = query_df(\\"SELECT so_tien FROM sothuchi WHERE so_bn=\'BN0528\' AND noi_dung=\'thanh lý\'\\")\\nresult = int(df[\'so_tien\'].iloc[0])"}'

            agent = DataMateAgent(backend=MockLLMBackend(mock_hybrid), config=AgentConfig(max_sql_retries=2, max_probe_steps=1))
            ans = agent.answer_question(
                {"id": "q_pawn", "question": "món Samsung S21 cầm 23/01/2026 lúc thanh lý bán được bao nhiêu", "as_of_date": "2026-09-30"},
                know,
            )
            self.assertEqual(ans.prediction, {"id": "q_pawn", "type": "number", "answer": 3900000})
            self.assertEqual(ans.sql_attempts, 1)  # probe step did not consume retry attempts

            # 1-row 3-column 'lan luot' list formatting
            tuple_res = format_sql_result(
                SQLExecutionResult(True, "SELECT ...", ["hoa", "sl", "t_tien"], [("Hoa lan hồ điệp", 3, 162000)], 1),
                classify_expected_type("hôm 30/11/2025 loại nào mua nhiều cành nhất? cho em lần lượt tên hoa, số cành mua rồi tiền đã trả"),
                "hôm 30/11/2025 loại nào mua nhiều cành nhất? cho em lần lượt tên hoa, số cành mua rồi tiền đã trả",
            )
            self.assertEqual(tuple_res, {"type": "list", "answer": ["Hoa lan hồ điệp", 3, 162000]})

    def test_focused_schema_truncates_large_workspace_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            bdir = root / "big_ws"
            bdir.mkdir()
            for idx in range(12):
                name = "nv_banhang" if idx == 0 else f"tbl_extra_{idx}"
                (bdir / f"{name}.csv").write_text(f"id,col_{idx},gia\n1,val_{idx},1000\n", encoding="utf-8")
            ws = load_business_workspace(bdir, cache_dir=root / "cache", force_rebuild=True)
            know = build_workspace_knowledge(ws)
            focused = build_focused_schema_prompt("doanh thu ban hang", know, max_full_tables=5)
            self.assertIn("trọng tâm", focused)
            self.assertIn("tóm tắt", focused)

    def test_value_overlap_fk_subquery_capture_subjective_and_stopwords(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            bdir = root / "fk_overlap"
            bdir.mkdir()
            (bdir / "don_hang.csv").write_text(
                "ma_chung_tu,ngay,customer_id,tinh_trang\n"
                "ORD-001,2025-03-05,CUST-1,completed\n"
                "ORD-002,2025-03-06,CUST-2,completed\n",
                encoding="utf-8",
            )
            (bdir / "chi_tiet_don.csv").write_text(
                "ma_don_hang,ma_mat_hang,amount\n"
                "ORD-001,ITEM-A,200000\n"
                "ORD-002,ITEM-B,300000\n",
                encoding="utf-8",
            )
            (bdir / "khach_hang.csv").write_text(
                "ma_kh,khach_hang_ten\n"
                "CUST-1,La Huy Anh\n"
                "CUST-2,Đàm Tùng Nhi\n",
                encoding="utf-8",
            )
            ws = load_business_workspace(bdir, cache_dir=root / "cache", force_rebuild=True)
            know = build_workspace_knowledge(ws)

            # Value-overlap FK discovery across differently named keys
            join_str = " | ".join(know.join_graph)
            self.assertIn("chi_tiet_don.ma_don_hang = don_hang.ma_chung_tu", join_str)
            self.assertIn("don_hang.customer_id = khach_hang.ma_kh", join_str)

            # Subquery outer-column capture blocker
            bad_subq = "SELECT SUM(amount) FROM chi_tiet_don WHERE ma_don_hang IN (SELECT ma_don_hang FROM don_hang)"
            cap_err = _check_subquery_column_capture(bad_subq, know)
            self.assertIsNotNone(cap_err)
            self.assertIn("ma_chung_tu", cap_err)

            # Entity noise stopword prevents 'tỉ lệ huỷ ... là nhiêu' matching 'La Huy Anh', while real names match
            noise_ents = ground_query_entities("tỉ lệ huỷ đơn tháng 6/2025 là nhiêu %", know)
            self.assertFalse(any(v == "La Huy Anh" for _, _, v in noise_ents))
            real_ents = ground_query_entities("đơn của khách tên Nhi họ Đàm là bao nhiêu", know)
            self.assertTrue(any(v == "Đàm Tùng Nhi" for _, _, v in real_ents))

            # Subjective attribute 'tận tâm' must trigger preflight unanswerable
            subj_q = "Nhân viên Đàm Tùng Nhi làm việc có tận tâm với khách không?"
            self.assertIsNotNone(
                check_preflight_unanswerable(subj_q, "2026-06-28", know, classify_expected_type(subj_q))
            )


if __name__ == "__main__":
    unittest.main()
