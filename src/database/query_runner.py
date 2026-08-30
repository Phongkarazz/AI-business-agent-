"""
Safe query execution engine with pagination/capping and error sanitization.
"""

from urllib.parse import quote_plus
import pandas as pd
from sqlalchemy import text
from src.config import MAX_ROWS_CAP


def sanitize_error(msg: str, pw: str) -> str:
    """Che mật khẩu nếu xuất hiện trong chuỗi thông báo lỗi."""
    if pw:
        msg = msg.replace(pw, "***")
        msg = msg.replace(quote_plus(pw), "***")
    return msg


def read_sql_capped(sql_query: str, engine, cap: int = MAX_ROWS_CAP, chunksize: int = 1000):
    """Đọc dữ liệu theo từng chunk, dừng ngay khi đạt giới hạn cap để tránh tràn bộ nhớ."""
    chunks, total, truncated = [], 0, False
    with engine.connect() as conn:
        for chunk in pd.read_sql(text(sql_query), conn, chunksize=chunksize):
            chunks.append(chunk)
            total += len(chunk)
            if total >= cap:
                truncated = True
                break
    if not chunks:
        return pd.DataFrame(), False
    df = pd.concat(chunks, ignore_index=True)
    if len(df) > cap:
        df = df.head(cap)
        truncated = True
    return df, truncated
