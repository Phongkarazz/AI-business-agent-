#!/usr/bin/env python3
"""
Script tự động khởi tạo và import CSDL Yến Sào (yen_sao_db) vào MySQL Local.
Sử dụng cấu hình đã lưu trong .saved_config.json hoặc nhập từ dòng lệnh.
"""

import os
import sys
import json
import re

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load_saved_mysql_config():
    config_path = os.path.join(PROJECT_ROOT, ".saved_config.json")
    cfg = {
        "host": "localhost",
        "port": 3306,
        "user": "root",
        "pass": os.getenv("MYSQL_PASSWORD", "")
    }
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if saved.get("db_host"):
                    cfg["host"] = saved["db_host"]
                if saved.get("db_port") and str(saved["db_port"]).isdigit():
                    cfg["port"] = int(saved["db_port"])
                if saved.get("db_user"):
                    cfg["user"] = saved["db_user"]
                if saved.get("db_pass"):
                    cfg["pass"] = saved["db_pass"]
        except Exception:
            pass
    return cfg

def main():
    print("=" * 65)
    print("🕊️  VERAXUS - KHỞI TẠO CSDL KINH DOANH YẾN SÀO NHA TRANG (yen_sao_db)")
    print("=" * 65)

    cfg = load_saved_mysql_config()
    print(f"👉 Thông số kết nối MySQL:")
    print(f"   - Host: {cfg['host']}")
    print(f"   - Port: {cfg['port']}")
    print(f"   - User: {cfg['user']}")
    print(f"   - Pass: {'*' * len(cfg['pass']) if cfg['pass'] else '(trống)'}")

    # Import thư viện kết nối MySQL
    connector = None
    try:
        import mysql.connector
        connector = "mysql.connector"
    except ImportError:
        try:
            import pymysql
            connector = "pymysql"
        except ImportError:
            print("\n❌ LỖI: Chưa cài đặt thư viện MySQL trong môi trường Python này.")
            print("👉 Vui lòng chạy lệnh sau để cài đặt:")
            print("   pip install mysql-connector-python")
            sys.exit(1)

    # Bước 1: Kết nối tới máy chủ MySQL
    print(f"\n[1/4] 🔌 Đang kết nối tới MySQL server ({cfg['host']}:{cfg['port']})...")
    conn = None
    last_err = None
    for target_host in [cfg["host"], "127.0.0.1", "localhost"]:
        try:
            if connector == "mysql.connector":
                conn = mysql.connector.connect(
                    host=target_host,
                    port=cfg["port"],
                    user=cfg["user"],
                    password=cfg["pass"],
                    connection_timeout=5
                )
            else:
                conn = pymysql.connect(
                    host=target_host,
                    port=cfg["port"],
                    user=cfg["user"],
                    password=cfg["pass"],
                    connect_timeout=5
                )
            cfg["host"] = target_host
            break
        except Exception as e:
            last_err = e

    if not conn:
        print(f"\n❌ Kết nối thất bại: {last_err}")
        print("💡 Hãy kiểm tra lại:")
        print("   1. MySQL server đã bật chưa? (Chạy: brew services start mysql)")
        print(f"   2. Kiểm tra lại mật khẩu cho user '{cfg['user']}' (trong .saved_config.json hoặc biến môi trường MYSQL_PASSWORD).")
        sys.exit(1)

    print(f"✅ Đã kết nối thành công tới MySQL ({cfg['host']})!")

    # Bước 2: Tạo CSDL yen_sao_db
    print("\n[2/4] 📦 Đang tạo database 'yen_sao_db'...")
    cursor = conn.cursor()
    try:
        cursor.execute("CREATE DATABASE IF NOT EXISTS yen_sao_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
        cursor.execute("USE yen_sao_db;")
        print("✅ Đã sẵn sàng database 'yen_sao_db'!")
    except Exception as e:
        print(f"❌ Lỗi khi tạo database: {e}")
        conn.close()
        sys.exit(1)

    # Bước 3: Đọc file yen_sao.sql và thực thi
    sql_file = os.path.join(PROJECT_ROOT, "data", "yen_sao.sql")
    if not os.path.exists(sql_file):
        print(f"❌ Không tìm thấy file dữ liệu tại {sql_file}")
        conn.close()
        sys.exit(1)

    print(f"\n[3/4] 📥 Đang nạp dữ liệu từ {os.path.basename(sql_file)}...")
    with open(sql_file, "r", encoding="utf-8") as f:
        sql_content = f.read()

    # Tách các câu lệnh theo dấu chấm phẩy
    # Bỏ các dòng chú thích và dòng trống
    statements = []
    current_stmt = []
    for line in sql_content.splitlines():
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("--") or trimmed.startswith("/*"):
            continue
        current_stmt.append(line)
        if trimmed.endswith(";"):
            stmt_str = "\n".join(current_stmt).strip()
            if stmt_str.endswith(";"):
                stmt_str = stmt_str[:-1].strip()
            if stmt_str:
                statements.append(stmt_str)
            current_stmt = []

    executed_count = 0
    for stmt in statements:
        try:
            cursor.execute(stmt)
            executed_count += 1
        except Exception as e:
            # Bỏ qua lỗi drop table if exists nếu bảng chưa có
            if "Unknown table" not in str(e):
                print(f"⚠️ Cảnh báo câu lệnh: {e}")

    conn.commit()
    print(f"✅ Đã thực thi thành công {executed_count} câu lệnh SQL!")

    # Bước 4: Kiểm tra và đếm dòng các bảng
    print("\n[4/4] 🔍 Kiểm tra số lượng bản ghi đã nạp:")
    tables = ["san_pham", "khach_hang", "don_hang", "chi_tiet_don_hang"]
    for t in tables:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM `{t}`;")
            count = cursor.fetchone()[0]
            print(f"   - Bảng `{t}`: {count} bản ghi")
        except Exception as e:
            print(f"   - Bảng `{t}`: Lỗi ({e})")

    cursor.close()
    conn.close()

    print("\n" + "=" * 65)
    print("🎉 HOÀN TẤT! CƠ SỞ DỮ LIỆU 'yen_sao_db' ĐÃ SẴN SÀNG.")
    print("👉 Bây giờ trong Veraxus (trên giao diện Streamlit):")
    print("   1. Chọn nguồn dữ liệu: '🖥️ MySQL Máy tính này (Localhost)'")
    print("   2. Tên Database: 'yen_sao_db'")
    print("   3. Bấm '⚡ KẾT NỐI HỆ THỐNG'")
    print("=" * 65)

if __name__ == "__main__":
    main()
