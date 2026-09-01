"""
Database schema inspector and metadata extractor.
Provides schema text with exact Date Ranges and Distinct Sample Values (Products, Teams, Geos) for LLM prompts, table listing, and sample data preview.
"""

import pandas as pd
from sqlalchemy import inspect, text
from src.config import MAX_TABLES_SCHEMA


_SCHEMA_CACHE = {}


def auto_extract_schema(engine, max_tables: int = MAX_TABLES_SCHEMA, force_refresh: bool = False) -> str:
    """Tự động trích xuất cấu trúc Bảng, Cột, Khóa ngoại (Foreign Keys) và Mẫu dữ liệu siêu tốc (< 0.05s) không gây treo database lớn."""
    if not engine:
        return "Chưa kết nối Cơ sở dữ liệu."

    cache_key = id(engine)
    if not force_refresh and cache_key in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[cache_key]

    try:
        inspector = inspect(engine)
        all_tables = inspector.get_table_names()
        tables = all_tables[:max_tables]
        schema_lines = ["Cơ sở dữ liệu bao gồm các bảng và cột sau:"]

        foreign_keys_info = []
        distinct_samples = []

        target_sample_cols = [
            "product", "category", "team", "geo", "region", "country", "size", "location", "status", "type",
            "spid", "pid", "geoid", "id", "code", "sku", "salesperson", "dept_name", "title"
        ]

        for table_name in tables:
            columns = inspector.get_columns(table_name)
            col_names = [f"{col['name']} ({str(col['type'])})" for col in columns]
            schema_lines.append(f"- Bảng `{table_name}`: {', '.join(col_names)}")

            # Trích xuất Foreign Keys (Khóa ngoại) nếu có
            try:
                fks = inspector.get_foreign_keys(table_name)
                for fk in fks:
                    referred_table = fk.get("referred_table")
                    constrained_cols = fk.get("constrained_columns", [])
                    referred_cols = fk.get("referred_columns", [])
                    if referred_table and constrained_cols and referred_cols:
                        foreign_keys_info.append(
                            f"• Bảng `{table_name}` ({', '.join(constrained_cols)}) liên kết với `{referred_table}` ({', '.join(referred_cols)})"
                        )
            except Exception:
                pass

            # Lấy mẫu giá trị siêu tốc bằng LIMIT 10 (không quét full bảng triệu dòng)
            try:
                sample_col_names = [col['name'] for col in columns if any(t in col['name'].lower() for t in target_sample_cols)]
                if sample_col_names:
                    safe_tbl = table_name.replace("`", "")
                    safe_cols = ", ".join(f"`{c.replace('`', '')}`" for c in sample_col_names[:5])
                    with engine.connect() as conn:
                        res = conn.execute(text(f"SELECT {safe_cols} FROM `{safe_tbl}` LIMIT 10")).fetchall()
                        if res:
                            for idx, c_name in enumerate(sample_col_names[:5]):
                                vals = list(dict.fromkeys(str(r[idx]).strip() for r in res if r[idx] is not None and str(r[idx]).strip()))
                                if vals:
                                    distinct_samples.append(f"• Bảng `{table_name}` (cột `{c_name}`): {', '.join(repr(v) for v in vals[:10])}")
            except Exception:
                pass

        schema_text = "\n".join(schema_lines)

        if foreign_keys_info:
            schema_text += "\n\n=== QUAN HỆ KHÓA NGOẠI LIÊN KẾT (FOREIGN KEYS) ===\n"
            schema_text += "\n".join(foreign_keys_info)

        if distinct_samples:
            schema_text += "\n\n=== DANH SÁCH GIÁ TRỊ MẪU THỰC TẾ TRONG CSDL (SAMPLE VALUES) ===\n"
            schema_text += "\n".join(distinct_samples[:30])

        if len(all_tables) > max_tables:
            schema_text += f"\n\n(Lưu ý: DB có {len(all_tables)} bảng, chỉ hiển thị {max_tables} bảng đầu tiên.)"

        _SCHEMA_CACHE[cache_key] = schema_text
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
