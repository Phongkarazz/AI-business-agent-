"""
Hammer Schema Masking Engine (OPPO ACL Findings 2024/2025).
Anonymizes database tables and column names during training/fine-tuning data generation,
forcing the model to attend to column descriptions and types rather than memorizing fixed names.
Enables Zero-Shot transfer and high generalization across unseen database schemas.
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple, Any
from sqlalchemy import inspect


class SchemaMasker:
    """Công cụ ẩn danh hóa và che dấu Schema (Function / Schema Masking).
    
    Theo nghiên cứu Hammer (OPPO 2024), việc thay thế tên hàm và tên cột bằng các định danh
    ngẫu nhiên trong quá trình huấn luyện sẽ ép mô hình phải đọc hiểu phần mô tả ngữ nghĩa
    (Descriptions) thay vì học vẹt (overfitting) vào một database cụ thể.
    """

    TABLE_PREFIXES = ["tbl_txn", "tbl_entity", "tbl_dim", "tbl_fact", "tbl_core"]
    COL_PREFIXES = {
        "id": "id_key",
        "numeric": "metric_val",
        "text": "attr_name",
        "date": "dim_date",
        "categorical": "dim_cat"
    }

    def __init__(self, engine=None):
        self.engine = engine
        self.table_map: Dict[str, str] = {}  # original -> masked
        self.reverse_table_map: Dict[str, str] = {}  # masked -> original
        self.col_map: Dict[str, Dict[str, str]] = {}  # table -> {original_col -> masked_col}
        self.reverse_col_map: Dict[str, Dict[str, str]] = {}

    def build_masking_maps(self, tables_info: List[Dict[str, Any]]) -> Tuple[Dict[str, str], Dict[str, Dict[str, str]]]:
        """Tạo bảng tra cứu mã hóa ẩn danh ngẫu nhiên cho danh sách bảng và cột."""
        self.table_map.clear()
        self.reverse_table_map.clear()
        self.col_map.clear()
        self.reverse_col_map.clear()

        tbl_idx = 1
        for t_info in tables_info:
            orig_tbl = t_info["name"]
            prefix = self.TABLE_PREFIXES[(tbl_idx - 1) % len(self.TABLE_PREFIXES)]
            masked_tbl = f"{prefix}_{tbl_idx:02d}"
            self.table_map[orig_tbl] = masked_tbl
            self.reverse_table_map[masked_tbl] = orig_tbl

            self.col_map[orig_tbl] = {}
            self.reverse_col_map[masked_tbl] = {}

            c_idx = 1
            for col in t_info.get("columns", []):
                orig_col = col["name"]
                col_type = str(col.get("type", "")).lower()
                
                if "int" in col_type or "id" in orig_col.lower() or orig_col.lower().endswith("id"):
                    c_prefix = self.COL_PREFIXES["id"]
                elif any(k in col_type for k in ["float", "double", "decimal", "numeric", "real"]):
                    c_prefix = self.COL_PREFIXES["numeric"]
                elif any(k in col_type for k in ["date", "time", "year"]):
                    c_prefix = self.COL_PREFIXES["date"]
                else:
                    c_prefix = self.COL_PREFIXES["text"]

                masked_col = f"{c_prefix}_{c_idx:02d}"
                self.col_map[orig_tbl][orig_col] = masked_col
                self.reverse_col_map[masked_tbl][masked_col] = orig_col
                c_idx += 1

            tbl_idx += 1

        return self.table_map, self.col_map

    def mask_sql(self, sql_query: str) -> str:
        """Chuyển đổi một câu lệnh SQL từ tên gốc sang tên ẩn danh (Masked SQL)."""
        if not sql_query or not self.table_map:
            return sql_query

        masked = sql_query

        # 1. Thay thế tên cột theo từng bảng (nếu có tiền tố table.col hoặc thay theo từ đơn)
        for orig_tbl, cols in self.col_map.items():
            masked_tbl = self.table_map.get(orig_tbl, orig_tbl)
            for orig_col, masked_col in cols.items():
                # Dạng table.column
                pattern_dot = re.compile(rf"\b{re.escape(orig_tbl)}\.{re.escape(orig_col)}\b", re.IGNORECASE)
                masked = pattern_dot.sub(f"{masked_tbl}.{masked_col}", masked)

                # Dạng column đơn lẻ
                pattern_col = re.compile(rf"\b{re.escape(orig_col)}\b", re.IGNORECASE)
                masked = pattern_col.sub(masked_col, masked)

        # 2. Thay thế tên bảng
        for orig_tbl, masked_tbl in self.table_map.items():
            pattern_tbl = re.compile(rf"\b{re.escape(orig_tbl)}\b", re.IGNORECASE)
            masked = pattern_tbl.sub(masked_tbl, masked)

        return masked

    def unmask_sql(self, masked_sql_query: str) -> str:
        """Khôi phục câu lệnh SQL ẩn danh về tên gốc trong CSDL thực."""
        if not masked_sql_query or not self.reverse_table_map:
            return masked_sql_query

        unmasked = masked_sql_query

        # Thay thế tên cột
        for masked_tbl, cols in self.reverse_col_map.items():
            orig_tbl = self.reverse_table_map.get(masked_tbl, masked_tbl)
            for masked_col, orig_col in cols.items():
                pattern_dot = re.compile(rf"\b{re.escape(masked_tbl)}\.{re.escape(masked_col)}\b", re.IGNORECASE)
                unmasked = pattern_dot.sub(f"{orig_tbl}.{orig_col}", unmasked)

                pattern_col = re.compile(rf"\b{re.escape(masked_col)}\b", re.IGNORECASE)
                unmasked = pattern_col.sub(orig_col, unmasked)

        # Thay thế tên bảng
        for masked_tbl, orig_tbl in self.reverse_table_map.items():
            pattern_tbl = re.compile(rf"\b{re.escape(masked_tbl)}\b", re.IGNORECASE)
            unmasked = pattern_tbl.sub(orig_tbl, unmasked)

        return unmasked

    def generate_masked_schema_doc(self, tables_info: List[Dict[str, Any]]) -> str:
        """Tạo bản mô tả Schema ẩn danh nhưng bảo toàn 100% ngữ nghĩa & kiểu dữ liệu.
        
        Mô hình khi học từ schema này sẽ buộc phải đọc hiểu Type và Description,
        giúp nó sẵn sàng thích ứng với bất kỳ database nào của khách hàng.
        """
        if not self.table_map:
            self.build_masking_maps(tables_info)

        lines = ["=== DATABASE SCHEMA SPECIFICATION (ANONYMIZED ZERO-SHOT FORMAT) ==="]
        for t_info in tables_info:
            orig_tbl = t_info["name"]
            masked_tbl = self.table_map.get(orig_tbl, orig_tbl)
            desc_tbl = t_info.get("description", f"Business entity storing records for {orig_tbl}")
            
            lines.append(f"\nTable `{masked_tbl}` (Semantic Meaning: {desc_tbl}):")
            for col in t_info.get("columns", []):
                orig_col = col["name"]
                masked_col = self.col_map.get(orig_tbl, {}).get(orig_col, orig_col)
                col_type = col.get("type", "TEXT")
                col_desc = col.get("description", f"Dimension/Metric representing {orig_col}")
                lines.append(f"  - `{masked_col}` ({col_type}): {col_desc}")

        return "\n".join(lines)
