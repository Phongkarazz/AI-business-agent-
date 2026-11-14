"""
Unit tests for DataMate Step 1 modules (`datamate.temporal`, `datamate.evaluator_pa`, `datamate.loader`).
"""

import pathlib
import sys
import tempfile
import unicodedata
import unittest

import openpyxl

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from datamate.evaluator_pa import (
    evaluate_records,
    normalize_datamate_string,
    score_prediction,
)
from datamate.loader import (
    _parse_vn_number,
    load_business_workspace,
)
from datamate.temporal import (
    SolarLunarCalendar,
    TemporalResolver,
    parse_date_value,
)


TRAIN_DIR = pathlib.Path("/Users/phongha/Downloads/train")


class TestTemporal(unittest.TestCase):
    def test_parse_messy_dates(self):
        self.assertEqual(parse_date_value("01/06/2025"), ("2025-06-01", None))
        self.assertEqual(parse_date_value("2025-01-01 00:00:00"), ("2025-01-01", None))
        self.assertEqual(parse_date_value("2025-01-01 14:35:10"), ("2025-01-01", "14:35:10"))
        self.assertEqual(parse_date_value("1 thg 6 2025"), ("2025-06-01", None))
        # Excel serial 45717 -> 2025-03-01 (epoch 1899-12-30 + 45717d)
        self.assertEqual(parse_date_value(45717), ("2025-03-01", None))
        self.assertEqual(parse_date_value("45717"), ("2025-03-01", None))
        # Yearless date with default sheet year (Rulebook §8)
        self.assertEqual(parse_date_value("15/03", default_year=2025), ("2025-03-15", None))
        self.assertEqual(parse_date_value("15/03", default_year=None), (None, None))

    def test_relative_windows_and_mtd_comparison(self):
        # 2026-03-31 vs February (28 days) -> clamp day 31 to Feb 28
        res = TemporalResolver("2026-03-31")
        ctx = res.build_context()
        self.assertEqual(ctx["this_month"], ("2026-03-01", "2026-03-31"))
        self.assertEqual(ctx["last_month_same_days"], ("2026-02-01", "2026-02-28"))
        self.assertEqual(ctx["last_month_full"], ("2026-02-01", "2026-02-28"))

        # 2026-03-04 (Wednesday) -> Monday 2026-03-02, last_week Feb 23..Mar 01
        res2 = TemporalResolver("2026-03-04")
        ctx2 = res2.build_context()
        self.assertEqual(ctx2["this_week"], ("2026-03-02", "2026-03-04"))
        self.assertEqual(ctx2["last_week"], ("2026-02-23", "2026-03-01"))
        self.assertEqual(ctx2["last_month_same_days"], ("2026-02-01", "2026-02-04"))
        self.assertEqual(res2.last_n_days(7), ("2026-02-26", "2026-03-04"))

        # Month / quarter without year rulebook §2
        self.assertEqual(res2.resolve_month(2), ("2026-02-01", "2026-02-28"))
        self.assertEqual(res2.resolve_month(5), ("2025-05-01", "2025-05-31"))
        self.assertEqual(res2.resolve_quarter(1), ("2026-01-01", "2026-03-04"))
        self.assertEqual(res2.resolve_quarter(2), ("2025-04-01", "2025-06-30"))

    def test_tet_solar_lunar_calendar(self):
        cal_path = TRAIN_DIR / "calendar.csv"
        if not cal_path.exists():
            self.skipTest("calendar.csv not found")
        cal = SolarLunarCalendar(cal_path)
        # Tết 2026: 23/12 năm Ất Tỵ (lunar_year=2025) -> mùng 10/1 năm Bính Ngọ (2026)
        self.assertEqual(
            cal.tet_window(2026),
            ("2026-02-10", "2026-02-26", "2026-01-24", "2026-02-09"),
        )
        res = TemporalResolver("2026-03-04", cal=cal)
        tet = res.latest_tet_window()
        self.assertIsNotNone(tet)
        self.assertEqual(tet["lunar_year"], 2026)
        self.assertEqual(tet["tet_start"], "2026-02-10")
        self.assertEqual(tet["tet_end"], "2026-02-26")


class TestEvaluatorPA(unittest.TestCase):
    def test_string_normalization_nfc_and_punctuation(self):
        # Preserves diacritics, lowercases, replaces punctuation with space
        nfd = unicodedata.normalize("NFD", "Cà phê sữa (M)")
        nfc = "Cà phê sữa - M"
        self.assertEqual(normalize_datamate_string(nfd), "cà phê sữa m")
        self.assertEqual(normalize_datamate_string(nfc), "cà phê sữa m")
        self.assertEqual(normalize_datamate_string("sp_0042"), "sp 0042")

    def test_all_types_and_penalties(self):
        refs = [
            {"id": "1", "type": "number", "answer": 4820000, "alias": []},
            {"id": "2", "type": "percent", "answer": -12.45, "alias": []},
            {"id": "3", "type": "string", "answer": "Sting dâu 330ml", "alias": ["SP0042"]},
            {"id": "4", "type": "list", "answer": ["A", "B"], "alias": [["K1"], ["K2"]]},
            {
                "id": "5",
                "type": "table",
                "answer": {"columns": ["khach_hang", "so_tien_no"], "rows": [["Chị Lan", 3200000], ["Anh Tú", 1500000]]},
                "alias": [["KH01"], ["KH02"]],
            },
            {"id": "6", "type": "unanswerable", "answer": None, "alias": []},
            {"id": "7", "type": "boolean", "answer": True, "alias": []},
            {"id": "8", "type": "date", "answer": "2025-12", "alias": []},
        ]
        preds = [
            {"id": "1", "type": "number", "answer": 4820000},
            {"id": "2", "type": "percent", "answer": -12.454},
            {"id": "3", "type": "string", "answer": "sp0042"},
            {"id": "4", "type": "list", "answer": ["k1", "B"]},
            # Shuffled columns AND shuffled row order + alias match on KH02
            {
                "id": "5",
                "type": "table",
                "answer": {"columns": ["so_tien_no", "khach_hang"], "rows": [[1500000, "kh02"], [3200000, "Chị Lan"]]},
            },
            {"id": "6", "type": "unanswerable", "reason": "Thiếu dữ liệu"},
            {"id": "7", "type": "abstain"},
            {"id": "8", "type": "number", "answer": 202512},  # wrong type
        ]
        rep = evaluate_records(refs, preds)
        # 6 correct, 1 abstain, 1 wrong -> (6 - 1) / 8 = 0.625
        self.assertEqual(rep.correct, 6)
        self.assertEqual(rep.abstain, 1)
        self.assertEqual(rep.wrong, 1)
        self.assertAlmostEqual(rep.pa, 0.625)

    def test_strict_format_rejections(self):
        # String number must fail
        pts, out, _ = score_prediction(
            {"id": "x", "type": "number", "answer": "4820000"},
            {"id": "x", "type": "number", "answer": 4820000},
        )
        self.assertEqual((pts, out), (-1, "wrong"))

        # Boolean masquerading as int must fail
        pts, out, _ = score_prediction(
            {"id": "x", "type": "number", "answer": True},
            {"id": "x", "type": "number", "answer": 1},
        )
        self.assertEqual((pts, out), (-1, "wrong"))

        # Unanswerable with non-str reason becomes abstain (0) per rulebook §7
        pts, out, _ = score_prediction(
            {"id": "x", "type": "unanswerable", "reason": 123},
            {"id": "x", "type": "unanswerable", "answer": None},
        )
        self.assertEqual((pts, out), (0, "abstain"))

        # Answering unanswerable with 0 is -1
        pts, out, _ = score_prediction(
            {"id": "x", "type": "number", "answer": 0},
            {"id": "x", "type": "unanswerable", "answer": None},
        )
        self.assertEqual((pts, out), (-1, "wrong"))


class TestLoader(unittest.TestCase):
    def test_vn_number_formats(self):
        self.assertEqual(_parse_vn_number("45.000đ", True), 45000)
        self.assertEqual(_parse_vn_number("1.194.833.600đ", True), 1194833600)
        self.assertEqual(_parse_vn_number("19,000.0000", True), 19000)
        self.assertEqual(_parse_vn_number("39k", True), 39000)
        self.assertEqual(_parse_vn_number("1tr140", True), 1140000)
        self.assertEqual(_parse_vn_number("332,5972tr", True), 332597200)
        # Keep phone numbers / zero-padded IDs as None (text)
        self.assertIsNone(_parse_vn_number("0907860932", False))
        # Preserve small decimals when dot is not thousands separator
        self.assertEqual(_parse_vn_number("1.5", False), 1.5)

    def test_synthetic_messy_excel_ingestion_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            bdir = root / "biz_tmp"
            bdir.mkdir()
            (bdir / "README.md").write_text("# Test biz", encoding="utf-8")

            # 1) Multi-sheet monthly XLSX with super-header, continuation blank rows,
            #    subtotal rows, exact duplicate inside same order, and yearless date
            wb = openpyxl.Workbook()
            ws1 = wb.active
            ws1.title = "Tháng 01-2025"
            ws1.append(["Đơn", None, None, "Hàng", None, "Tiền"])
            ws1.append(["Mã đơn hàng", "Ngày", "Khách hàng", "Tên sản phẩm", "Số lượng", "Thành tiền"])
            ws1.append(["ORD001", "15/1", "47 Cộng Hòa Test", "Cà phê sữa", "2 ly", "60.000đ"])
            # Continuation line of ORD001 (missing order cols)
            ws1.append([None, None, None, "Bạc xỉu", "1 ly", "35k"])
            # Exact export duplicate inside ORD001 -> must drop 1
            ws1.append([None, None, None, "Bạc xỉu", "1 ly", "35k"])
            # New order with explicit Khách lẻ
            ws1.append(["ORD002", 45672, None, "Trà đào", 1, "1tr050"])
            # Daily subtotal -> must drop
            ws1.append([None, "Tổng ngày 15/01", None, None, None, "1.145.000đ"])
            ws1.append(["Ghi chú: số liệu ghi tay"])
            wb.save(bdir / "DonHang_1.xlsx")

            # 2) Flat unkeyed CSV with two genuinely identical rows (must keep BOTH per Rulebook §8)
            #    and integer prices in 20000..80000 range (must NEVER become Excel serial dates!)
            csv_path = bdir / "chi_phi.csv"
            csv_path.write_text(
                "\ufeffNgày chi,Mục,So tien,gia_ban\n"
                "01/01/2025,Điện,500.000đ,29000\n"
                "01/01/2025,Điện,500.000đ,45000\n",
                encoding="utf-8",
            )

            ws = load_business_workspace(bdir, cache_dir=root / "cache", force_rebuild=True)
            self.assertIn("donhang", ws.tables)
            self.assertIn("chi_phi", ws.tables)
            chi_phi_cols = {c.sql_name: c.inferred_type for c in ws.tables["chi_phi"].columns}
            self.assertEqual(chi_phi_cols["gia_ban"], "integer")

            conn = ws.open_connection()
            try:
                rows = conn.execute(
                    "SELECT ma_don_hang, ngay, khach_hang, ten_san_pham, so_luong, thanh_tien FROM donhang"
                ).fetchall()
                # Expect 3 rows: ORD001 item1, ORD001 item2 (deduped duplicate dropped), ORD002 (not inheriting ORD001 customer!)
                self.assertEqual(len(rows), 3)
                self.assertEqual(rows[0], ("ORD001", "2025-01-15", "47 Cộng Hòa Test", "Cà phê sữa", 2, 60000))
                self.assertEqual(rows[1], ("ORD001", "2025-01-15", "47 Cộng Hòa Test", "Bạc xỉu", 1, 35000))
                self.assertEqual(rows[2], ("ORD002", "2025-01-15", None, "Trà đào", 1, 1050000))

                cost_rows = conn.execute("SELECT ngay_chi, muc, so_tien, gia_ban FROM chi_phi").fetchall()
                self.assertEqual(len(cost_rows), 2)
                self.assertEqual(cost_rows[0], ("2025-01-01", "Điện", 500000, 29000))
            finally:
                conn.close()

    def test_sqlite_normalized_dirty_dates(self):
        import sqlite3

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            bdir = root / "biz_sql"
            bdir.mkdir()
            raw_db = bdir / "pos.sqlite"
            con_w = sqlite3.connect(raw_db)
            con_w.execute(
                "CREATE TABLE don_hang (MaHoaDon TEXT, NgayLap TEXT, HanSuDung TEXT, TongThanhToan INTEGER, SoDienThoai TEXT)"
            )
            con_w.executemany(
                "INSERT INTO don_hang VALUES (?, ?, ?, ?, ?)",
                [
                    ("ORD01", "01/01/2025", "15/06/2027", 535000, "0901234567"),
                    ("ORD02", "1 thg 1 2025", "2027-06-15", 65000, "0912345678"),
                    ("ORD03", "45658", "15/06/2027", 27500, "0987654321"),
                ],
            )
            con_w.commit()
            con_w.close()

            ws = load_business_workspace(bdir, cache_dir=root / "cache", force_rebuild=True)
            self.assertEqual(ws.source_kind, "sqlite_normalized")
            cols = {c.sql_name: c.inferred_type for c in ws.tables["don_hang"].columns}
            self.assertEqual(cols["NgayLap"], "date")
            self.assertEqual(cols["HanSuDung"], "date")
            self.assertEqual(cols["TongThanhToan"], "integer")
            self.assertEqual(cols["SoDienThoai"], "text")

            con_r = ws.open_connection()
            try:
                rows = con_r.execute(
                    'SELECT MaHoaDon, NgayLap, HanSuDung, TongThanhToan, SoDienThoai FROM "don_hang" ORDER BY MaHoaDon'
                ).fetchall()
                self.assertEqual(
                    rows,
                    [
                        ("ORD01", "2025-01-01", "2027-06-15", 535000, "0901234567"),
                        ("ORD02", "2025-01-01", "2027-06-15", 65000, "0912345678"),
                        ("ORD03", "2025-01-01", "2027-06-15", 27500, "0987654321"),
                    ],
                )
            finally:
                con_r.close()

            # Warm cache reload preserves normalized types
            ws2 = load_business_workspace(bdir, cache_dir=root / "cache", force_rebuild=False)
            cols2 = {c.sql_name: c.inferred_type for c in ws2.tables["don_hang"].columns}
            self.assertEqual(cols2["NgayLap"], "date")


if __name__ == "__main__":
    unittest.main()
