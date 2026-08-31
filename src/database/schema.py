"""
Database schema inspector and metadata extractor.
Provides schema text with exact Date Ranges for LLM prompts, table listing, and sample data preview.
"""

import pandas as pd
from sqlalchemy import inspect, text
from src.config import MAX_TABLES_SCHEMA


def auto_extract_schema(engine, max_tables: int = MAX_TABLES_SCHEMA) -> str:
    """Tự động trích xuất cấu trúc Bảng, Cột và Khoảng thời gian thực tế (Date Range) từ Database."""
    try:
        inspector = inspect(engine)
        all_tables = inspector.get_table_names()
        tables = all_tables[:max_tables]
        schema_text = "Cơ sở dữ liệu bao gồm các bảng và cột sau:\n"

        date_ranges = []

        for table_name in tables:
            schema_text += f"- Bảng `{table_name}`: "
            columns = inspector.get_columns(table_name)
            col_names = [f"{col['name']} ({str(col['type'])})" for col in columns]
            schema_text += ", ".join(col_names) + "\n"

            # Tự động quét các cột thời gian để trích xuất MIN và MAX date thực tế
            for col in columns:
                col_name = col["name"]
                col_type = str(col["type"]).lower()
                if "date" in col_type or "time" in col_type or "date" in col_name.lower():
                    try:
                        safe_tbl = table_name.replace("`", "")
                        safe_col = col_name.replace("`", "")
                        with engine.connect() as conn:
                            res = conn.execute(
                                text(f"SELECT MIN(`{safe_col}`), MAX(`{safe_col}`) FROM `{safe_tbl}` WHERE `{safe_col}` IS NOT NULL")
                            ).fetchone()
                            if res and res[0] is not None and res[1] is not None:
                                min_d = str(res[0])[:10]
                                max_d = str(res[1])[:10]
                                min_year = min_d[:4]
                                max_year = max_d[:4]
                                year_desc = f"{min_year}" if min_year == max_year else f"{min_year} đến {max_year}"
                                date_ranges.append(
                                    f"• Bảng `{table_name}` (cột `{col_name}`): Dữ liệu có từ ngày {min_d} đến {max_d} (Các năm có dữ liệu: {year_desc})"
                                )
                    except Exception:
                        pass

        if date_ranges:
            schema_text += "\n=== KHOẢNG THỜI GIAN THỰC TẾ TRONG DỮ LIỆU (DATE RANGE) ===\n"
            schema_text += "\n".join(date_ranges) + "\n"
            schema_text += "LƯU Ý QUAN TRỌNG: Chỉ truy vấn và gợi ý trong các năm/khoảng thời gian thực tế ở trên.\n"
            schema_text += "===========================================================\n"

        if len(all_tables) > max_tables:
            schema_text += f"\n(Lưu ý: DB có {len(all_tables)} bảng, chỉ hiển thị {max_tables} bảng đầu tiên.)\n"
        return schema_text
    except Exception as e:
        return f"Không thể tự động đọc schema: {e}"


def get_table_names(engine) -> list[str]:
    """Lấy danh sách tất cả các bảng trong database đang kết nối."""
    if not engine:
        return []
    try:
        inspector = inspect(engine)
        return inspector.get_table_names()
    except Exception:
        return []


def get_table_columns_info(engine, table_name: str) -> list[dict]:
    """Lấy danh sách chi tiết các cột và kiểu dữ liệu của một bảng."""
    if not engine or not table_name:
        return []
    try:
        inspector = inspect(engine)
        columns = inspector.get_columns(table_name)
        return [{"name": col["name"], "type": str(col["type"])} for col in columns]
    except Exception:
        return []


def get_table_sample_df(engine, table_name: str, limit: int = 5) -> pd.DataFrame:
    """Đọc nhanh 5 dòng mẫu của một bảng để xem trước cấu trúc dữ liệu."""
    if not engine or not table_name:
        return pd.DataFrame()
    try:
        safe_table_name = table_name.replace("`", "").replace("'", "").replace('"', "")
        query = f"SELECT * FROM `{safe_table_name}` LIMIT {int(limit)}"
        with engine.connect() as conn:
            df = pd.read_sql(text(query), conn)
        return df
    except Exception:
        return pd.DataFrame()
