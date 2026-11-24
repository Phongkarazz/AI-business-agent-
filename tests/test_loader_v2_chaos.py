"""Comprehensive unit tests for DataMate Loader v2 (Universal Chaos-Proof Ingestion)."""

from __future__ import annotations

import pathlib
import sqlite3
import sys
import tempfile
import unittest

import openpyxl

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from datamate.loader import _parse_vn_number, load_business_workspace
from datamate.temporal import parse_date_value


class TestTemporalAndNumbersV2(unittest.TestCase):
    def test_messy_vietnamese_dates_and_unix_timestamps(self) -> None:
        self.assertEqual(parse_date_value("T1/25", default_year=2025), ("2025-01-25", None))
        self.assertEqual(parse_date_value("T10/1", default_year=2025), ("2025-10-01", None))
        self.assertEqual(parse_date_value("T6 02/01", default_year=2026), ("2026-01-02", None))
        self.assertEqual(parse_date_value("Thứ hai, 02/06/2025"), ("2025-06-02", None))
        self.assertEqual(parse_date_value("12/05/2025 (15/4 âm)"), ("2025-05-12", None))
        # Unix epoch seconds only converted when explicitly allowed (UTC+7 Vietnam)
        self.assertEqual(parse_date_value(1735664400, allow_unix_ts=False), (None, None))
        self.assertEqual(parse_date_value(1735664400, allow_unix_ts=True), ("2025-01-01", None))
        self.assertEqual(parse_date_value("1735689681", allow_unix_ts=True), ("2025-01-01", "07:01:21"))

    def test_scientific_space_slang_mul_and_spoken_numbers(self) -> None:
        self.assertEqual(_parse_vn_number("2.25E+07", True), 22500000)
        self.assertEqual(_parse_vn_number("1E+06", True), 1000000)
        self.assertEqual(_parse_vn_number("17 500 000", True), 17500000)
        self.assertEqual(_parse_vn_number("199.000₫", True), 199000)
        # Slang, multiplication, and spoken numbers require explicit allow_slang_money=True
        self.assertIsNone(_parse_vn_number("5 cành", True, allow_slang_money=False))
        self.assertEqual(_parse_vn_number("30 cành", True, allow_slang_money=True), 30000)
        self.assertEqual(_parse_vn_number("2 củ", True, allow_slang_money=True), 2000000)
        self.assertEqual(_parse_vn_number("5 xị", True, allow_slang_money=True), 500000)
        self.assertEqual(_parse_vn_number("199.200 x 6", True, allow_slang_money=True), 1195200)
        self.assertEqual(_parse_vn_number("264k x 5", True, allow_slang_money=True), 1320000)
        self.assertEqual(_parse_vn_number("hai triệu tám trăm nghìn", True, allow_slang_money=True), 2800000)
        self.assertEqual(_parse_vn_number("mười một triệu hai trăm nghìn", True, allow_slang_money=True), 11200000)


class TestLoaderV2Chaos(unittest.TestCase):
    def test_hybrid_sqlite_and_xlsx_ingestion_plus_code_preservation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            bdir = root / "hybrid_biz"
            bdir.mkdir()

            db_p = bdir / "pos.sqlite"
            con = sqlite3.connect(db_p)
            con.execute("CREATE TABLE nv_banhang (so_hd TEXT, ngay_ban INTEGER, thoi_gian_ban TEXT, tong_tien INTEGER)")
            con.executemany(
                "INSERT INTO nv_banhang VALUES (?, ?, ?, ?)",
                [
                    ("HD001", 1735664400, "1735689681", 150000),
                    ("HD002", 1735750800, "1735786200", 240000),
                ],
            )
            con.commit()
            con.close()

            wb = openpyxl.Workbook()
            sh = wb.active
            sh.title = "T01.2025"
            sh.append(["BẢNG KÊ HÓA ĐƠN ĐIỆN TỬ BÁN RA"])
            sh.append([])
            sh.append(["KY HIEU", "SO HOA DON", "NGAY LAP", "TONG TIEN"])
            sh.append(["1C25MAA", "0000001", "01/01/2025", "150.000₫"])
            sh.append(["1C25MAA", "0000002", "02/01/2025", "240k"])
            wb.save(bdir / "BangKeHoaDon.xlsx")

            ws = load_business_workspace(bdir, cache_dir=root / "cache", force_rebuild=True)
            self.assertEqual(ws.source_kind, "hybrid_sqlite_tabular")
            self.assertIn("nv_banhang", ws.tables)
            self.assertIn("bangkehoadon", ws.tables)

            bk_cols = {c.sql_name: c.inferred_type for c in ws.tables["bangkehoadon"].columns}
            self.assertEqual(bk_cols["ky_hieu"], "text")
            self.assertEqual(bk_cols["ngay_lap"], "date")
            self.assertEqual(bk_cols["tong_tien"], "integer")

            nv_cols = {c.sql_name: c.inferred_type for c in ws.tables["nv_banhang"].columns}
            self.assertEqual(nv_cols["ngay_ban"], "date")
            self.assertEqual(nv_cols["thoi_gian_ban"], "datetime")

            ro = ws.open_connection()
            try:
                self.assertEqual(
                    ro.execute("SELECT ky_hieu, so_hoa_don, ngay_lap, tong_tien FROM bangkehoadon ORDER BY so_hoa_don").fetchall(),
                    [("1C25MAA", "0000001", "2025-01-01", 150000), ("1C25MAA", "0000002", "2025-01-02", 240000)],
                )
                self.assertEqual(
                    ro.execute("SELECT so_hd, ngay_ban, thoi_gian_ban FROM nv_banhang ORDER BY so_hd").fetchone(),
                    ("HD001", "2025-01-01", "2025-01-01 07:01:21"),
                )
            finally:
                ro.close()

            # Warm cache preserves source_kind & table_meta notes
            ws2 = load_business_workspace(bdir, cache_dir=root / "cache", force_rebuild=False)
            self.assertEqual(ws2.source_kind, "hybrid_sqlite_tabular")
            self.assertIn("nv_banhang", ws2.tables)

    def test_wide_attendance_matrix_merged_headers_and_side_by_side_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            bdir = root / "chaos_biz"
            bdir.mkdir()

            # 1) Wide 36-col attendance matrix + legend row + ALL CAPS divider + salary sheet
            wb_hr = openpyxl.Workbook()
            sh_att = wb_hr.active
            sh_att.title = "Chấm công"
            sh_att.append(["BẢNG CHẤM CÔNG"])
            sh_att.append(["Giờ vào, giờ ra", "P: nghỉ có phép", "K: nghỉ không phép", "ô trống: không ca"])
            sh_att.append(["Mã NV", "Họ và tên", "Bộ phận", "Tháng", "Vào/Ra"] + [str(d) for d in range(1, 32)])
            sh_att.append(["PHÒNG KINH DOANH"])
            sh_att.append(["NV001", "Nguyễn An", "Kinh doanh", "2026-01-01", "Vào", None, "07:10", "P"] + [None] * 28)
            sh_att.append([None, None, None, None, "Ra", None, "17:00", None] + [None] * 28)

            sh_sal = wb_hr.create_sheet("Bảng lương")
            sh_sal.append(["BẢNG LƯƠNG"])
            sh_sal.append(["Mã NV", "Họ và tên", "Lương CB", "Giờ OT", "Tiền công"])
            sh_sal.append(["NV001", "Nguyễn An", "2.25E+07", "13h", "199.200 x 2"])
            sh_sal.append(["NV002", "Trần Bình", "17 500 000", "5,5", "500k"])
            wb_hr.save(bdir / "NhanSu.xlsx")

            # 2) Merged 2-row hierarchical headers + repeated voucher ID without duplicating Cọc
            wb_m = openpyxl.Workbook()
            sh_m = wb_m.active
            sh_m.title = "Lịch thuê"
            sh_m.append(["Phiếu", "Khách", "SĐT", "NGÀY", None, None, "TIỀN", None, "Mã đồ"])
            sh_m.append([None, None, None, "Đặt", "Lấy", "Hẹn trả", "Thuê", "Cọc", None])
            for mref in ("A1:A2", "B1:B2", "C1:C2", "D1:F1", "G1:H1", "I1:I2"):
                sh_m.merge_cells(mref)
            sh_m.append(["P0001", "Lâm Mỹ", "0328604752", "01/05/2025", "12/05/2025 (15/4 âm)", "14/05/2025", "4650k", "6tr5", "VC17"])
            sh_m.append(["P0001", None, None, None, None, None, "2000000", None, "AD01"])
            sh_kd = wb_m.create_sheet("Kho đồ")
            sh_kd.append(["Mã đồ", "Tên đồ", "Giá thuê"])
            sh_kd.append(["VC17", "Váy công chúa", "4tr65"])
            wb_m.save(bdir / "AoCuoi.xlsx")

            # 3) Side-by-side dual tables (SỔ CHI | THU) across 2 monthly sheets
            wb_dual = openpyxl.Workbook()
            for idx_s, sname in enumerate(("Tháng 03.2024", "Tháng 04.2024")):
                sh_d = wb_dual.active if idx_s == 0 else wb_dual.create_sheet(sname)
                sh_d.title = sname
                sh_d.append(["SỔ CHI", None, None, None, None, "THU", None, None])
                sh_d.append([])
                sh_d.append(["Ngày", "Khoản chi", "Số tiền", "Ghi chú", None, "Ngày", "Nguồn", "Số tiền"])
                day = f"0{idx_s + 1}/0{idx_s + 3}/2024"
                sh_d.append([day, "Ăn sáng", "50.000đ", None, None, day, "Lương", "20tr"])
                sh_d.append([None, "Cà phê", "35k", None, None, None, None, None])
            wb_dual.save(bdir / "SoChiTieu.xlsx")

            ws = load_business_workspace(bdir, cache_dir=root / "cache", force_rebuild=True)
            self.assertIn("cham_cong", ws.tables)
            self.assertEqual(len(ws.tables["cham_cong"].columns), 36)
            self.assertIn("wide_day_matrix=true", ws.tables["cham_cong"].notes)

            sal_cols = {c.sql_name: c.inferred_type for c in ws.tables["bang_luong"].columns}
            self.assertEqual(sal_cols["luong_cb"], "integer")
            self.assertEqual(sal_cols["gio_ot"], "real")
            self.assertEqual(sal_cols["tien_cong"], "integer")

            self.assertIn("lich_thue", ws.tables)
            self.assertIn("kho_do", ws.tables)
            lt_cols = {c.sql_name: c.inferred_type for c in ws.tables["lich_thue"].columns}
            for col in ("ngay_dat", "ngay_lay", "ngay_hen_tra"):
                self.assertEqual(lt_cols[col], "date")
            self.assertIn("tien_coc", lt_cols)

            self.assertIn("so_chi", ws.tables)
            self.assertIn("thu", ws.tables)

            ro = ws.open_connection()
            try:
                # Day 'P' on col 3 of Vào row must NOT leak into Ra row!
                att_rows = ro.execute("SELECT ma_nv, vao_ra, col_7_2, col_8_3 FROM cham_cong ORDER BY rowid").fetchall()
                self.assertEqual(att_rows, [("NV001", "Vào", "07:10", "P"), ("NV001", "Ra", "17:00", None)])

                # Repeated P0001 continuation inherits Khách + NGÀY - Lấy + NGÀY - Hẹn trả, but MUST NOT copy TIỀN - Cọc!
                lt_rows = ro.execute(
                    "SELECT phieu, khach, ngay_lay, ngay_hen_tra, tien_thue, tien_coc, ma_do FROM lich_thue ORDER BY rowid"
                ).fetchall()
                self.assertEqual(
                    lt_rows,
                    [
                        ("P0001", "Lâm Mỹ", "2025-05-12", "2025-05-14", 4650000, 6500000, "VC17"),
                        ("P0001", "Lâm Mỹ", "2025-05-12", "2025-05-14", 2000000, None, "AD01"),
                    ],
                )

                # Side-by-side SỔ CHI & THU cleanly separated & forward-filled leading date
                self.assertEqual(ro.execute("SELECT COUNT(*), SUM(so_tien) FROM so_chi").fetchone(), (4, 170000))
                self.assertEqual(ro.execute("SELECT COUNT(*), SUM(so_tien) FROM thu").fetchone(), (2, 40000000))
            finally:
                ro.close()

    def test_duplicate_subheaders_schema_drift_overlap_dedup_and_kv_unpacking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            bdir = root / "multi_biz"
            bdir.mkdir()

            # 1) School scorebooks with Lớp pre-header metadata + HỌC KỲ I / II ancestor + '-' sentinels
            for cls in ("7A2", "7A3"):
                wb_s = openpyxl.Workbook()
                sh_ds = wb_s.active
                sh_ds.title = "DS lớp"
                sh_ds.append(["Lớp", cls])
                sh_ds.append(["STT", "MA HS", "HO VA TEN"])
                sh_ds.append([1, f"HS_{cls}_1", f"Em {cls}"])

                sh_m = wb_s.create_sheet("Toán học")
                sh_m.append(["SỔ ĐIỂM"])
                sh_m.append(["Lớp", cls, "Môn", "Toán học"])
                sh_m.append([None, None, "HỌC KỲ I", None, None, "HỌC KỲ II", None, None])
                sh_m.append(["MA HS", "HO VA TEN", "TX1", "GK", "CK", "TX1", "GK", "CK"])
                sh_m.append([f"HS_{cls}_1", f"Em {cls} 1", 8, 8.5, 9, "-", 9.0, 9.5])
                sh_m.append([f"HS_{cls}_2", f"Em {cls} 2", 7, 7.5, 8, 9, 8.5, 9.0])
                wb_s.save(bdir / f"SoDiem_{cls}.xlsx")

            # 2) Schema-drift cross-file dump (50->51 col pattern + reordered case variant + overlapping rows)
            for fname, headers, rows_data in [
                (
                    "Order.all.20251001_20251031.xlsx",
                    ["Mã ĐH", "Tên SP", "SL bán", "Tong GT DH (VND)"],
                    [["ORD1", "Áo A", "5 cành", 100000], ["ORD2", "Quần B", 2, 200000]],
                ),
                (
                    "Order.all.20251015_20251115.xlsx",
                    ["mã đh", "Tên SP", "SL bán", "Phi DV Goi Co Ban", "Tong GT DH (VND)"],
                    [["ORD2", "Quần B", 2, None, 200000], ["ORD3", "Váy C", 1, 5000, 300000]],
                ),
            ]:
                wb_o = openpyxl.Workbook()
                sh_o = wb_o.active
                sh_o.title = "Order.all"
                sh_o.append(["Thời gian xuất: 01/12/2025"])
                sh_o.append(headers)
                for rr in rows_data:
                    sh_o.append(rr)
                wb_o.save(bdir / fname)

            # 3) Due date han_tra MUST NOT forward-fill onto repayment rows when ng is already filled
            wb_cn = openpyxl.Workbook()
            sh_cn = wb_cn.active
            sh_cn.append(["han tra", "H.lấy", "Ng", "Nguoi dat hang", "Khách còn nợ"])
            sh_cn.append(["03.03.2025", "1 bao xi măng", "01.02.2025", "Khách A", "100k"])
            sh_cn.append([None, None, "01.02.2025", "Khách B", "50k"])
            wb_cn.save(bdir / "SoCongNo.xlsx")

            # 4) Mixed tabular + vertical KV block sheet ('2026') + weekly calendar grid
            wb_st = openpyxl.Workbook()
            sh_st1 = wb_st.active
            sh_st1.title = "T12.2025"
            sh_st1.append(["Ngày", "Khách", "Dịch vụ", "Thợ", "Tiền"])
            sh_st1.append(["01/12/2025", "Chị Lan", "Cắt tóc", "Tí", "100k"])
            sh_st2 = wb_st.create_sheet("2026")
            for ln in [
                "Hoá đơn",
                "Ngày: 01/01/2026",
                "Khách: Anh Bình",
                "Dịch vụ: Nhuộm",
                "Thợ: Mít",
                "Tiền: 400.000đ",
                "-----",
                "Ngày: 02/01/2026",
                "Khách: Bé Hoa",
                "Dịch vụ: Gội",
                "Thợ: Tí",
                "Tiền: 80k",
            ]:
                sh_st2.append([ln])
            wb_st.save(bdir / "SoThu.xlsx")

            wb_dd = openpyxl.Workbook()
            sh_d1 = wb_dd.active
            sh_d1.title = "T4.2026"
            sh_d1.append(["STT sổ bán", "Ngày giao", "Kh.", "M.hoa", "sl", "Cọc"])
            sh_d1.append([1, "02/04/2026", "An", "Hoa hồng", "2 cành", "50k"])
            sh_d2 = wb_dd.create_sheet("T5.2026")
            sh_d2.append(["Tuần", "Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5"])
            sh_d2.append([
                "Tuần 1",
                "STT sổ bán: 5 | Ngày giao: 04.05.2026 | Kh.: Bình | M.hoa: Hoa ly | sl: 3 | Cọc: 90k",
                None,
                None,
                None,
            ])
            wb_dd.save(bdir / "DonDat.xlsx")

            ws = load_business_workspace(bdir, cache_dir=root / "cache", force_rebuild=True)
            self.assertIn("ds_lop", ws.tables)
            self.assertIn("lop", {c.sql_name for c in ws.tables["ds_lop"].columns})

            self.assertIn("toan_hoc", ws.tables)
            toan_cols = {c.sql_name: c.inferred_type for c in ws.tables["toan_hoc"].columns}
            self.assertIn("hoc_ky_i_tx1", toan_cols)
            self.assertIn("hoc_ky_ii_tx1", toan_cols)
            self.assertEqual(toan_cols["hoc_ky_ii_tx1"], "integer")

            self.assertIn("order_all", ws.tables)
            ord_cols = {c.sql_name: c.inferred_type for c in ws.tables["order_all"].columns}
            self.assertEqual(ord_cols["sl_ban"], "integer")  # '5 cành' parsed as quantity 5, NOT 5000!

            ro = ws.open_connection()
            try:
                # Overlapping ORD2 in Order.all deduplicated cleanly -> 3 distinct orders remain
                self.assertEqual(
                    ro.execute("SELECT ma_dh, sl_ban, tong_gt_dh_vnd FROM order_all ORDER BY ma_dh").fetchall(),
                    [("ORD1", 5, 100000), ("ORD2", 2, 200000), ("ORD3", 1, 300000)],
                )
                # SoCongNo row 2 han_tra MUST remain NULL
                self.assertIsNone(
                    ro.execute("SELECT han_tra FROM socongno WHERE nguoi_dat_hang='Khách B'").fetchone()[0]
                )
                # SoThu merged tabular T12.2025 + vertical KV receipt block sheet 2026
                self.assertEqual(ro.execute("SELECT COUNT(*), SUM(tien) FROM sothu").fetchone(), (3, 580000))
                # DonDat merged tabular T4.2026 + weekly calendar grid T5.2026
                self.assertEqual(ro.execute("SELECT COUNT(*), SUM(coc) FROM dondat").fetchone(), (2, 140000))
            finally:
                ro.close()


if __name__ == "__main__":
    unittest.main()
