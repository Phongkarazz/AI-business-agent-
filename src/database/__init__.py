"""
Database package for connection management, schema inspection, and safe query execution.
"""

from .connection import try_connect
from .demo_data import build_demo_engine
from .schema import (
    auto_extract_schema,
    get_table_names,
    get_table_columns_info,
    get_table_sample_df,
)
from .query_runner import read_sql_capped, sanitize_error

__all__ = [
    "try_connect",
    "build_demo_engine",
    "auto_extract_schema",
    "get_table_names",
    "get_table_columns_info",
    "get_table_sample_df",
    "read_sql_capped",
    "sanitize_error",
]
