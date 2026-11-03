"""
Tạo CSDL SQLite Yến Sào Nha Trang (yen_sao.db) để test trực tiếp trên Veraxus.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "yen_sao.db")

def init_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 1. Bảng sản phẩm
    cur.execute("""
    CREATE TABLE san_pham (
        ma_sp TEXT PRIMARY KEY,
        ten_sp TEXT NOT NULL,
        danh_muc TEXT NOT NULL,
        quy_cach TEXT DEFAULT 'Hộp',
        gia_von REAL NOT NULL,
        gia_ban_le REAL NOT NULL,
        gia_ban_si REAL NOT NULL,
        ton_kho INTEGER NOT NULL DEFAULT 0
    );
    """)

    san_pham_data = [
        ('YTC_100G', 'Yến tinh chế rút lông cao cấp (100g)', 'Yến tinh chế', 'Hộp 100g', 2800000, 4200000, 3500000, 35),
        ('YTC_50G', 'Yến tinh chế rút lông cao cấp (50g)', 'Yến tinh chế', 'Hộp 50g', 1450000, 2200000, 1850000, 50),
        ('YTHO_L1_100G', 'Yến thô nguyên tổ đảo loại 1 (100g)', 'Yến thô', 'Hộp 100g', 2200000, 3300000, 2750000, 22),
        ('YTHO_L2_100G', 'Yến thô nhà nuôi loại 2 (100g)', 'Yến thô', 'Hộp 100g', 1700000, 2600000, 2150000, 18),
        ('YVUN_100G', 'Yến vụn tinh chế đắp tổ (100g)', 'Yến tinh chế', 'Hộp 100g', 1600000, 2400000, 1950000, 40),
        ('YCHUNG_DTH', 'Set 6 hũ yến chưng đông trùng hạ thảo (70ml)', 'Yến chưng sẵn', 'Lốc 6 hũ', 220000, 420000, 320000, 120),
        ('YCHUNG_SEN', 'Set 6 hũ yến chưng hạt sen đường phèn (70ml)', 'Yến chưng sẵn', 'Lốc 6 hũ', 180000, 360000, 270000, 150),
        ('YCHUNG_TAO', 'Set 6 hũ yến chưng táo đỏ kỷ tử (70ml)', 'Yến chưng sẵn', 'Lốc 6 hũ', 190000, 380000, 280000, 110),
        ('YCHUNG_KDUONG', 'Set 6 hũ yến chưng không đường ăn kiêng (70ml)', 'Yến chưng sẵn', 'Lốc 6 hũ', 180000, 360000, 270000, 85),
        ('SET_QUA_TET', 'Hộp quà biếu Tết Thượng Hạng (100g yến + 4 hũ chưng)', 'Hộp quà biếu', 'Hộp cao cấp', 3200000, 5200000, 4300000, 28)
    ]
    cur.executemany("INSERT INTO san_pham VALUES (?, ?, ?, ?, ?, ?, ?, ?)", san_pham_data)

    # 2. Bảng khách hàng & đại lý
    cur.execute("""
    CREATE TABLE khach_hang (
        ma_kh TEXT PRIMARY KEY,
        ten_khach_hang TEXT NOT NULL,
        loai_khach TEXT NOT NULL,
        khu_vuc TEXT NOT NULL,
        so_dien_thoai TEXT,
        ngay_hop_tac TEXT NOT NULL
    );
    """)

    khach_hang_data = [
        ('DL_HN01', 'Đại lý Thu Trang (Hà Nội)', 'Đại lý sỉ', 'Hà Nội', '0912345678', '2023-01-15'),
        ('DL_HCM01', 'Đại lý Minh Phát (TP.HCM)', 'Đại lý sỉ', 'TP.HCM', '0988776655', '2023-02-20'),
        ('DL_DN01', 'Đại lý Hoàng Yến (Đà Nẵng)', 'Đại lý sỉ', 'Đà Nẵng', '0905123456', '2023-03-10'),
        ('DL_HP01', 'Đại lý An Khang (Hải Phòng)', 'Đại lý sỉ', 'Hải Phòng', '0936789123', '2023-05-12'),
        ('CTV_MAI', 'Chị Ngọc Mai (Cộng tác viên)', 'Cộng tác viên', 'TP.HCM', '0977112233', '2023-06-01'),
        ('CTV_LAN', 'Chị Hương Lan (Cộng tác viên)', 'Cộng tác viên', 'Hà Nội', '0966445566', '2023-07-15'),
        ('KH_VIP01', 'Cô Thanh Nga (Khách VIP)', 'Khách VIP', 'TP.HCM', '0903998877', '2023-04-05'),
        ('KH_VIP02', 'Bác Hoàng Dũng (Khách VIP)', 'Khách VIP', 'Hà Nội', '0913887766', '2023-08-20'),
        ('KH_LE01', 'Anh Quốc Bảo', 'Khách lẻ', 'Cần Thơ', '0945667788', '2023-09-10'),
        ('KH_LE02', 'Chị Kim Oanh', 'Khách lẻ', 'Bình Dương', '0933221100', '2023-10-02'),
        ('KH_LE03', 'Chị Minh Thư', 'Khách lẻ', 'Đồng Nai', '0918776655', '2023-11-15'),
        ('DL_CT01', 'Đại lý Cần Thơ Yến', 'Đại lý sỉ', 'Cần Thơ', '0922334455', '2024-01-05')
    ]
    cur.executemany("INSERT INTO khach_hang VALUES (?, ?, ?, ?, ?, ?)", khach_hang_data)

    # 3. Bảng đơn hàng
    cur.execute("""
    CREATE TABLE don_hang (
        ma_don TEXT PRIMARY KEY,
        ma_kh TEXT NOT NULL,
        ngay_dat TEXT NOT NULL,
        kenh_ban TEXT NOT NULL,
        tong_tien REAL NOT NULL,
        tien_da_tra REAL NOT NULL,
        con_no REAL NOT NULL,
        trang_thai TEXT NOT NULL,
        FOREIGN KEY (ma_kh) REFERENCES khach_hang(ma_kh)
    );
    """)

    don_hang_data = [
        ('DH2023_01', 'DL_HN01', '2023-09-05', 'Bán sỉ đại lý', 35000000, 35000000, 0, 'Đã thanh toán'),
        ('DH2023_02', 'DL_HCM01', '2023-09-12', 'Bán sỉ đại lý', 52500000, 40000000, 12500000, 'Còn nợ gối đầu'),
        ('DH2023_03', 'KH_VIP01', '2023-09-18', 'Trực tiếp tại tiệm', 8400000, 8400000, 0, 'Đã thanh toán'),
        ('DH2023_04', 'CTV_MAI', '2023-09-25', 'Zalo / Hotline', 7400000, 7400000, 0, 'Đã thanh toán'),
        ('DH2023_05', 'DL_DN01', '2023-10-02', 'Bán sỉ đại lý', 27500000, 20000000, 7500000, 'Còn nợ gối đầu'),
        ('DH2023_06', 'KH_LE01', '2023-10-10', 'Facebook', 3300000, 3300000, 0, 'Đã thanh toán'),
        ('DH2023_07', 'DL_HP01', '2023-10-15', 'Bán sỉ đại lý', 38000000, 25000000, 13000000, 'Còn nợ gối đầu'),
        ('DH2023_08', 'KH_VIP02', '2023-10-22', 'Trực tiếp tại tiệm', 10400000, 10400000, 0, 'Đã thanh toán'),
        ('DH2023_09', 'DL_HN01', '2023-11-05', 'Bán sỉ đại lý', 42000000, 42000000, 0, 'Đã thanh toán'),
        ('DH2023_10', 'CTV_LAN', '2023-11-12', 'Zalo / Hotline', 5700000, 5700000, 0, 'Đã thanh toán'),
        ('DH2023_11', 'DL_HCM01', '2023-11-20', 'Bán sỉ đại lý', 68000000, 45000000, 23000000, 'Còn nợ gối đầu'),
        ('DH2023_12', 'KH_LE02', '2023-11-28', 'Facebook', 2600000, 2600000, 0, 'Đã thanh toán'),
        ('DH2023_13', 'DL_DN01', '2023-12-05', 'Bán sỉ đại lý', 32000000, 32000000, 0, 'Đã thanh toán'),
        ('DH2023_14', 'DL_HN01', '2023-12-15', 'Bán sỉ đại lý', 65000000, 50000000, 15000000, 'Còn nợ gối đầu'),
        ('DH2023_15', 'KH_VIP01', '2023-12-20', 'Trực tiếp tại tiệm', 15600000, 15600000, 0, 'Đã thanh toán'),
        ('DH2023_16', 'DL_HP01', '2023-12-25', 'Bán sỉ đại lý', 43000000, 20000000, 23000000, 'Còn nợ gối đầu'),
        ('DH2024_01', 'DL_HCM01', '2024-01-08', 'Bán sỉ đại lý', 86000000, 60000000, 26000000, 'Còn nợ gối đầu'),
        ('DH2024_02', 'DL_CT01', '2024-01-15', 'Bán sỉ đại lý', 35000000, 20000000, 15000000, 'Còn nợ gối đầu'),
        ('DH2024_03', 'KH_VIP02', '2024-01-20', 'Trực tiếp tại tiệm', 20800000, 20800000, 0, 'Đã thanh toán'),
        ('DH2024_04', 'CTV_MAI', '2024-02-05', 'Zalo / Hotline', 12500000, 12500000, 0, 'Đã thanh toán'),
        ('DH2024_05', 'DL_HN01', '2024-02-18', 'Bán sỉ đại lý', 45000000, 45000000, 0, 'Đã thanh toán'),
        ('DH2024_06', 'KH_LE03', '2024-02-25', 'Facebook', 4400000, 4400000, 0, 'Đã thanh toán'),
        ('DH2024_07', 'DL_DN01', '2024-03-05', 'Bán sỉ đại lý', 29000000, 15000000, 14000000, 'Còn nợ gối đầu'),
        ('DH2024_08', 'DL_HCM01', '2024-03-15', 'Bán sỉ đại lý', 72000000, 50000000, 22000000, 'Còn nợ gối đầu'),
        ('DH2024_09', 'KH_VIP01', '2024-03-22', 'Trực tiếp tại tiệm', 8400000, 8400000, 0, 'Đã thanh toán'),
        ('DH2024_10', 'DL_HP01', '2024-04-02', 'Bán sỉ đại lý', 34000000, 20000000, 14000000, 'Còn nợ gối đầu')
    ]
    cur.executemany("INSERT INTO don_hang VALUES (?, ?, ?, ?, ?, ?, ?, ?)", don_hang_data)

    # 4. Bảng chi tiết đơn hàng
    cur.execute("""
    CREATE TABLE chi_tiet_don_hang (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ma_don TEXT NOT NULL,
        ma_sp TEXT NOT NULL,
        so_luong INTEGER NOT NULL,
        don_gia REAL NOT NULL,
        thanh_tien REAL NOT NULL,
        FOREIGN KEY (ma_don) REFERENCES don_hang(ma_don),
        FOREIGN KEY (ma_sp) REFERENCES san_pham(ma_sp)
    );
    """)

    chi_tiet_data = [
        ('DH2023_01', 'YTC_100G', 10, 3500000, 35000000),
        ('DH2023_02', 'YTC_100G', 15, 3500000, 52500000),
        ('DH2023_03', 'YTC_100G', 2, 4200000, 8400000),
        ('DH2023_04', 'YCHUNG_DTH', 20, 250000, 5000000),
        ('DH2023_04', 'YCHUNG_SEN', 10, 240000, 2400000),
        ('DH2023_05', 'YTHO_L1_100G', 10, 2750000, 27500000),
        ('DH2023_06', 'YTHO_L1_100G', 1, 3300000, 3300000),
        ('DH2023_07', 'YTC_50G', 20, 1900000, 38000000),
        ('DH2023_08', 'SET_QUA_TET', 2, 5200000, 10400000),
        ('DH2023_09', 'YTC_100G', 12, 3500000, 42000000),
        ('DH2023_10', 'YCHUNG_DTH', 15, 260000, 3900000),
        ('DH2023_10', 'YCHUNG_SEN', 5, 250000, 1250000),
        ('DH2023_11', 'SET_QUA_TET', 12, 4300000, 51600000),
        ('DH2023_11', 'YVUN_100G', 8, 2050000, 16400000),
        ('DH2023_12', 'YTHO_L2_100G', 1, 2600000, 2600000),
        ('DH2023_13', 'YCHUNG_DTH', 50, 320000, 16000000),
        ('DH2023_13', 'YCHUNG_SEN', 50, 270000, 13500000),
        ('DH2023_13', 'YCHUNG_TAO', 10, 250000, 2500000),
        ('DH2023_14', 'SET_QUA_TET', 15, 4300000, 64500000),
        ('DH2023_15', 'SET_QUA_TET', 3, 5200000, 15600000),
        ('DH2023_16', 'SET_QUA_TET', 10, 4300000, 43000000),
        ('DH2024_01', 'YTC_100G', 20, 3500000, 70000000),
        ('DH2024_01', 'YTC_50G', 8, 2000000, 16000000),
        ('DH2024_02', 'YTC_100G', 10, 3500000, 35000000),
        ('DH2024_03', 'SET_QUA_TET', 4, 5200000, 20800000),
        ('DH2024_04', 'YCHUNG_DTH', 30, 280000, 8400000),
        ('DH2024_04', 'YCHUNG_SEN', 15, 270000, 4050000),
        ('DH2024_05', 'YTC_100G', 12, 3500000, 42000000),
        ('DH2024_05', 'YVUN_100G', 1, 3000000, 3000000),
        ('DH2024_06', 'YTC_50G', 2, 2200000, 4400000),
        ('DH2024_07', 'YTHO_L1_100G', 10, 2900000, 29000000),
        ('DH2024_08', 'YTC_100G', 20, 3600000, 72000000),
        ('DH2024_09', 'YTC_100G', 2, 4200000, 8400000),
        ('DH2024_10', 'YTHO_L1_100G', 10, 3400000, 34000000)
    ]
    cur.executemany("INSERT INTO chi_tiet_don_hang (ma_don, ma_sp, so_luong, don_gia, thanh_tien) VALUES (?, ?, ?, ?, ?)", chi_tiet_data)

    conn.commit()
    conn.close()
    print("✅ Đã tạo thành công cơ sở dữ liệu SQLite tại:", DB_PATH)

if __name__ == "__main__":
    init_db()
