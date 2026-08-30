"""
Database schema inspector and metadata extractor.
Provides schema text for LLM prompts, table listing, and sample data preview.
"""

import pandas as pd
from sqlalchemy import inspect, text
from src.config import MAX_TABLES_SCHEMA


def auto_extract_schema(engine, max_tables: int = MAX_TABLES_SCHEMA) -> str:
    """Tự động trích xuất cấu trúc Bảng và Cột từ Database để cung cấp cho LLM."""
    try:
        inspector = inspect(engine)
        all_tables = inspector.get_table_names()
        tables = all_tables[:max_tables]
        schema_text = "Cơ sở dữ liệu bao gồm các bảng và cột sau:\n"
        for table_name in tables:
            schema_text += f"- Bảng `{table_name}`: "
            columns = inspector.get_columns(table_name)
            col_names = [f"{col['name']} ({str(col['type'])})" for col in columns]
            schema_text += ", ".join(col_names) + "\n"
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
        # Bọc tên bảng an toàn
        safe_table_name = table_name.replace("`", "").replace("'", "").replace('"', "")
        query = f"SELECT * FROM `{safe_table_name}` LIMIT {int(limit)}"
        with engine.connect() as conn:
            df = pd.read_sql(text(query), conn)
        return df
    except Exception:
        return pd.DataFrame()
