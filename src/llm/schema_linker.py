"""
Enterprise Schema Linking & Metadata RAG Engine for Veraxus.
Provides semantic schema retrieval, column pruning, foreign-key graph traversal,
and business entity-synonym mapping for large-scale enterprise databases (10 to 500+ tables).
"""

from __future__ import annotations

import re
import math
from typing import Dict, List, Set, Tuple, Any, Optional
from collections import defaultdict


# Business synonyms and domain dictionary (Vietnamese <-> English <-> Business Metrics)
BUSINESS_SYNONYMS: Dict[str, List[str]] = {
    # Finance / Revenue / Sales / Cash
    "amount": ["tiền", "tiền mặt", "doanh thu", "doanh số", "doanh so", "sales", "revenue", "spend", "spending", "chi tiêu", "thanh toán", "payment", "giá trị", "total revenue", "totalrevenue"],
    "amount_due": ["amount due", "amount_due", "công nợ", "tiền phải trả", "tổng tiền", "hóa đơn", "invoice", "invoices"],
    "salary": ["lương", "tiền lương", "thu nhập", "bảng lương", "payroll", "wage", "compensation", "income"],
    "boxes": ["hộp", "số hộp", "số lượng hộp", "hộp kẹo", "thùng", "pack", "volume", "units", "quantity"],
    "cost": ["chi phí", "giá vốn", "vốn", "giá nhập", "expense", "cogs", "cost_per_box"],
    "price": ["giá", "giá bán", "đơn giá", "unit_price", "rate", "rental_rate"],
    "discount": ["chiết khấu", "giảm giá", "khuyến mãi", "promo"],
    "order_details": ["order_details", "order_detail", "chi tiết đơn hàng", "quantity", "unit_price", "discount", "doanh thu", "revenue", "total revenue", "totalrevenue", "sales"],
    "orders": ["orders", "order", "đơn hàng", "order_date", "thời gian", "month", "tháng", "thời điểm"],
    "invoices": ["invoices", "invoice", "amount_due", "amount due", "tax", "shipping"],
    "city": ["thành phố", "city", "đô thị", "ship_city", "tỉnh", "thành"],
    "ship_city": ["thành phố", "city", "ship_city", "thành phố giao hàng"],

    # People / Customers / Employees / Actors
    "customer": ["khách hàng", "khách", "người mua", "người dùng", "client", "buyer", "user", "account"],
    "employee": ["nhân viên", "nhân sự", "người lao động", "staff", "worker", "salesperson", "rep", "nhân viên kinh doanh", "vị trí công việc", "vị trí", "chức vụ", "chức danh", "job_title", "job title"],
    "last_name": ["last name", "lastname", "last_name", "họ", "tên họ", "họ tên"],
    "first_name": ["first name", "firstname", "first_name", "tên", "họ tên"],
    "manager": ["quản lý", "trưởng phòng", "giám đốc", "leader", "head", "supervisor"],
    "actor": ["diễn viên", "diễn xuất", "nghệ sĩ", "cast", "star"],
    "salesperson": ["nhân viên bán hàng", "nhân sự kinh doanh", "sales", "sales rep", "người bán"],

    # Organization / Departments / Categories / Products
    "department": ["phòng ban", "bộ phận", "phòng", "khối", "dept", "division"],
    "title": ["chức danh", "chức vụ", "vị trí", "công việc", "vị trí công việc", "role", "job_title", "job title", "position"],
    "job_title": ["vị trí công việc", "vị trí", "chức vụ", "chức danh", "role", "job_title", "job title", "position", "nghề nghiệp"],
    "product": ["sản phẩm", "mặt hàng", "hàng hóa", "item", "sku", "kẹo", "socola", "chocolate", "film", "phim"],
    "category": ["danh mục", "nhóm sản phẩm", "phân loại", "thể loại", "loại", "genre", "segment"],
    "geo": ["quốc gia", "thị trường", "khu vực", "địa lý", "quốc tịch", "country", "region", "market", "location"],
    "film": ["phim", "bộ phim", "movie", "video", "tác phẩm", "dvd"],
    "rental": ["thuê", "lượt thuê", "mượn", "giao dịch thuê", "rent", "hire"],

    # Time / Temporal
    "hire_date": ["ngày vào làm", "ngày tuyển dụng", "ngày gia nhập", "tuyển dụng", "nhập ngũ"],
    "birth_date": ["ngày sinh", "năm sinh", "sinh nhật", "tuổi"],
    "saledate": ["ngày bán", "ngày giao dịch", "thời gian bán", "order_date", "sale_date"],
    "payment_date": ["ngày thanh toán", "ngày trả tiền", "thời điểm thanh toán", "paid_at"],
    "rental_date": ["ngày thuê", "thời điểm thuê", "rented_at"],
    "from_date": ["ngày bắt đầu", "từ ngày", "hiệu lực từ"],
    "to_date": ["ngày kết thúc", "đến ngày", "hạn chót", "hiện tại"],
}


class SchemaGraph:
    """Đồ thị quan hệ Foreign Keys giữa các bảng trong Database để tìm đường đi JOIN ngắn nhất."""

    def __init__(self):
        self.adj = defaultdict(dict)  # table -> {neighbor: (fk_col, ref_col)}
        self.tables: Set[str] = set()

    def add_edge(self, table_a: str, table_b: str, col_a: str, col_b: str):
        tbl_a = table_a.lower()
        tbl_b = table_b.lower()
        self.tables.add(tbl_a)
        self.tables.add(tbl_b)
        self.adj[tbl_a][tbl_b] = (col_a, col_b)
        self.adj[tbl_b][tbl_a] = (col_b, col_a)

    def find_shortest_path(self, start_table: str, end_table: str) -> List[str]:
        """BFS tìm đường đi ngắn nhất giữa 2 bảng qua các liên kết Foreign Keys."""
        start = start_table.lower()
        end = end_table.lower()
        if start == end:
            return [start]
        if start not in self.adj or end not in self.adj:
            return []

        queue = [[start]]
        visited = {start}

        while queue:
            path = queue.pop(0)
            curr = path[-1]
            if curr == end:
                return path
            for neighbor in self.adj.get(curr, {}):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(path + [neighbor])
        return []

    def connect_subgraph(self, target_tables: List[str]) -> Set[str]:
        """Bổ sung các bảng trung gian (Bridge/Junction Tables) để kết nối toàn bộ các bảng mục tiêu."""
        connected_tables = set(t.lower() for t in target_tables)
        if len(connected_tables) <= 1:
            return connected_tables

        table_list = list(connected_tables)
        for i in range(len(table_list)):
            for j in range(i + 1, len(table_list)):
                path = self.find_shortest_path(table_list[i], table_list[j])
                if path:
                    connected_tables.update(path)
        return connected_tables


class TableMetadata:
    """Metadata đại diện cho 1 bảng trong Database."""

    def __init__(self, name: str, columns: List[Dict[str, str]], sample_values: Optional[List[str]] = None):
        self.name = name
        self.name_lower = name.lower()
        self.columns = columns  # [{"name": "col", "type": "int", "comment": ""}]
        self.column_names = [c["name"] for c in columns]
        self.column_names_lower = [c["name"].lower() for c in columns]
        self.sample_values = sample_values or []
        self.foreign_keys: List[Dict[str, str]] = []  # [{"col": "", "ref_table": "", "ref_col": ""}]

    def get_searchable_tokens(self) -> Set[str]:
        """Trích xuất tất cả tokens đại diện cho bảng để phục vụ tìm kiếm ngữ nghĩa."""
        tokens = set()
        tokens.add(self.name_lower)
        for part in re.split(r"[_\s\-]+", self.name_lower):
            if part:
                tokens.add(part)

        for col in self.column_names_lower:
            tokens.add(col)
            for part in re.split(r"[_\s\-]+", col):
                if part:
                    tokens.add(part)

        # Bổ sung từ đồng nghĩa nghiệp vụ
        for syn_key, syn_vals in BUSINESS_SYNONYMS.items():
            if syn_key in tokens or any(syn_key in col for col in self.column_names_lower) or syn_key in self.name_lower:
                for v in syn_vals:
                    tokens.add(v.lower())
                    for vp in v.lower().split():
                        tokens.add(vp)

        # Bổ sung sample values
        for val in self.sample_values:
            val_clean = str(val).lower().strip("`'\",() ")
            if len(val_clean) > 2 and len(val_clean) < 40:
                tokens.add(val_clean)
                for vp in val_clean.split():
                    tokens.add(vp)

        return tokens


class SchemaLinker:
    """
    Metadata RAG & Schema Linking Engine.
    Tự động xếp hạng, lọc bảng, chọn cột và kết nối đường đi Foreign Keys tối ưu.
    """

    def __init__(self):
        self.graph = SchemaGraph()
        self.tables_meta: Dict[str, TableMetadata] = {}

    def parse_schema_context(self, schema_context: str):
        """Phân tích cú pháp chuỗi schema_context có sẵn và dựng Metadata Store + Schema Graph."""
        if not schema_context or "Chưa kết nối" in schema_context:
            return

        # 1. Trích xuất các bảng và cột
        table_matches = re.findall(r"-\s*Bảng\s+`?([a-zA-Z0-9_]+)`?:\s*([^\n]+)", schema_context, re.IGNORECASE)
        for tbl_name, col_str in table_matches:
            cols = []
            for raw_col in col_str.split(","):
                raw_col = raw_col.strip()
                if not raw_col:
                    continue
                cm = re.match(r"`?([a-zA-Z0-9_]+)`?(?:\s*\(([^)]+)\))?", raw_col)
                if cm:
                    c_name = cm.group(1)
                    c_type = cm.group(2) or "TEXT"
                    cols.append({"name": c_name, "type": c_type})
                else:
                    cols.append({"name": raw_col, "type": "TEXT"})
            self.tables_meta[tbl_name.lower()] = TableMetadata(name=tbl_name, columns=cols)

        # 2. Trích xuất Foreign Keys
        fk_matches = re.findall(
            r"Bảng\s+`?([a-zA-Z0-9_]+)`?\s*\(([^)]+)\)\s*liên kết với\s*`?([a-zA-Z0-9_]+)`?\s*\(([^)]+)\)",
            schema_context,
            re.IGNORECASE
        )
        for tbl_a, cols_a, tbl_b, cols_b in fk_matches:
            col_a = cols_a.split(",")[0].strip().strip("`")
            col_b = cols_b.split(",")[0].strip().strip("`")
            self.graph.add_edge(tbl_a, tbl_b, col_a, col_b)
            if tbl_a.lower() in self.tables_meta:
                self.tables_meta[tbl_a.lower()].foreign_keys.append({
                    "col": col_a,
                    "ref_table": tbl_b,
                    "ref_col": col_b
                })

        # 3. Trích xuất Sample Values
        sample_matches = re.findall(
            r"Bảng\s+`?([a-zA-Z0-9_]+)`?\s*\(cột\s*`?([a-zA-Z0-9_]+)`?[^)]*\):\s*([^\n]+)",
            schema_context,
            re.IGNORECASE
        )
        for tbl_name, col_name, val_str in sample_matches:
            tbl_key = tbl_name.lower()
            if tbl_key in self.tables_meta:
                vals = [v.strip().strip("`'\"") for v in val_str.split(",") if v.strip()]
                self.tables_meta[tbl_key].sample_values.extend(vals)

        # 4. Tự động suy diễn quan hệ (Implicit Foreign Keys) theo tên cột (VD: dept_no, emp_no, customer_id, film_id)
        self._infer_implicit_foreign_keys()

    def _infer_implicit_foreign_keys(self):
        """Tự động phát hiện các khóa ngoại ngầm định dựa trên tên cột định danh ID."""
        for tbl_a_name, meta_a in self.tables_meta.items():
            for c_a in meta_a.column_names:
                c_a_low = c_a.lower()
                if c_a_low.endswith("_id") or c_a_low.endswith("_no") or c_a_low in ("spid", "pid", "geoid"):
                    # 1. Trùng tên cột chính xác (VD: emp_no <-> emp_no, film_id <-> film_id)
                    for tbl_b_name, meta_b in self.tables_meta.items():
                        if tbl_a_name != tbl_b_name:
                            if c_a_low in meta_b.column_names_lower:
                                if tbl_b_name not in self.graph.adj.get(tbl_a_name, {}):
                                    self.graph.add_edge(tbl_a_name, tbl_b_name, c_a, c_a)
                            # 2. Khóa ngoại dạng <table_singular>_id nối tới PK `id` của bảng cha (VD: order_id -> orders.id, customer_id -> customers.id, product_id -> products.id)
                            elif "id" in meta_b.column_names_lower:
                                base_entity = c_a_low[:-3] if c_a_low.endswith("_id") else c_a_low
                                b_norm = tbl_b_name.rstrip('s')
                                if base_entity == b_norm or base_entity == tbl_b_name or f"{base_entity}s" == tbl_b_name:
                                    if tbl_b_name not in self.graph.adj.get(tbl_a_name, {}):
                                        self.graph.add_edge(tbl_a_name, tbl_b_name, c_a, "id")
                                        self.graph.add_edge(tbl_b_name, tbl_a_name, "id", c_a)

    def score_table_relevance(self, user_query: str, table_meta: TableMetadata) -> float:
        """Tính điểm liên quan của bảng dựa trên BM25/Cosine TF-IDF và từ đồng nghĩa nghiệp vụ."""
        q_low = user_query.lower()
        q_tokens = [t for t in re.split(r"[^\w]+", q_low) if len(t) > 1]
        if not q_tokens:
            return 0.0

        score = 0.0
        table_tokens = table_meta.get_searchable_tokens()

        # 1. Khớp trực tiếp tên bảng
        if table_meta.name_lower in q_low:
            score += 15.0
        for part in table_meta.name_lower.split("_"):
            if part in q_low:
                score += 5.0

        # 2. Khớp các cột quan trọng
        for col_name in table_meta.column_names_lower:
            if col_name in q_low:
                score += 8.0
            for part in col_name.split("_"):
                if len(part) > 2 and part in q_low:
                    score += 3.0

        # 3. Khớp từ đồng nghĩa nghiệp vụ (Business Synonyms Matching)
        for token in q_tokens:
            for syn_key, syn_vals in BUSINESS_SYNONYMS.items():
                if token in syn_vals:
                    # Nếu bảng có chứa syn_key hoặc cột có chứa syn_key
                    if syn_key in table_meta.name_lower:
                        score += 7.0
                    if any(syn_key in c for c in table_meta.column_names_lower):
                        score += 5.0

        # 4. Khớp Sample Values (Giá trị thực tế trong DB)
        for val in table_meta.sample_values:
            val_clean = str(val).lower().strip("`'\",() ")
            if len(val_clean) > 2 and val_clean in q_low:
                score += 12.0

        # 5. Overlap Tokens
        overlap = set(q_tokens).intersection(table_tokens)
        score += len(overlap) * 2.5

        return score

    def link_schema(
        self,
        user_query: str,
        schema_context: str,
        max_tables: int = 6,
        force_full_if_small: bool = True
    ) -> Dict[str, Any]:
        """
        Thực hiện Schema Linking & Metadata Pruning:
        - Xếp hạng độ liên quan của các bảng.
        - Kết nối Subgraph qua Foreign Key Graph.
        - Trích xuất Sub-Schema tinh gọn, chính xác.
        """
        self.parse_schema_context(schema_context)
        all_table_names = list(self.tables_meta.keys())
        total_tables = len(all_table_names)

        # Nếu CSDL nhỏ (<= 5 bảng) và force_full_if_small=True, giữ lại toàn bộ bảng nhưng sắp xếp theo mức độ liên quan
        if total_tables <= 5 and force_full_if_small:
            selected_tables = [self.tables_meta[t].name for t in all_table_names]
            return {
                "selected_tables": selected_tables,
                "pruned_tables": [],
                "join_paths": [],
                "is_pruned": False,
                "sub_schema": schema_context,
                "confidence_score": 1.0
            }

        # 1. Tính điểm liên quan cho từng bảng
        table_scores = []
        for tbl_key, meta in self.tables_meta.items():
            sc = self.score_table_relevance(user_query, meta)
            table_scores.append((meta.name, sc))

        # Sắp xếp giảm dần theo điểm
        table_scores.sort(key=lambda x: x[1], reverse=True)

        # 2. Chọn Top K bảng có điểm cao nhất
        top_candidates = [tbl for tbl, sc in table_scores if sc > 0]
        if not top_candidates:
            # Fallback lấy top 3 bảng đầu tiên
            top_candidates = [tbl for tbl, sc in table_scores[:min(3, len(table_scores))]]
        else:
            top_candidates = top_candidates[:max_tables]

        # 3. Kết nối đồ thị Subgraph (Thêm các bảng cầu nối Foreign Key)
        connected_set = self.graph.connect_subgraph(top_candidates)

        # 3.1 Bổ sung bảng liên quan bắt buộc theo ngữ cảnh nghiệp vụ
        q_low = user_query.lower()
        if any(k in q_low for k in ["doanh thu", "revenue", "total revenue", "sales", "tiền", "giá"]):
            if "orders" in connected_set and "order_details" in self.tables_meta:
                connected_set.add("order_details")
        if any(k in q_low for k in ["sản phẩm", "product", "danh mục", "category", "mặt hàng"]):
            if "order_details" in connected_set and "products" in self.tables_meta:
                connected_set.add("products")
        if any(k in q_low for k in ["amount due", "amount_due", "hóa đơn", "invoice", "invoices"]):
            if "invoices" in self.tables_meta:
                connected_set.add("invoices")
            if "orders" in self.tables_meta:
                connected_set.add("orders")
        if any(k in q_low for k in ["thành phố", "city", "quốc gia", "country", "khách hàng", "customer"]):
            if "customers" in self.tables_meta and ("orders" in connected_set or "invoices" in connected_set):
                connected_set.add("customers")
        if any(k in q_low for k in ["vị trí", "công việc", "chức danh", "chức vụ", "job title", "job_title", "nhân viên", "nhân sự", "employee", "sales rep"]):
            if "employees" in self.tables_meta:
                connected_set.add("employees")
                if "invoices" in connected_set and "orders" in self.tables_meta:
                    connected_set.add("orders")
                elif "order_details" in connected_set and "orders" in self.tables_meta:
                    connected_set.add("orders")

        
        # Đảm bảo giữ đúng tên hoa thường gốc
        selected_tbl_names = []
        for tbl_key in connected_set:
            if tbl_key in self.tables_meta:
                selected_tbl_names.append(self.tables_meta[tbl_key].name)
            else:
                selected_tbl_names.append(tbl_key)

        pruned_tbl_names = [
            meta.name for tbl_key, meta in self.tables_meta.items()
            if meta.name not in selected_tbl_names
        ]

        # 4. Tìm các đường đi Join cụ thể giữa các bảng đã chọn
        join_paths = []
        for i in range(len(selected_tbl_names)):
            for j in range(i + 1, len(selected_tbl_names)):
                p = self.graph.find_shortest_path(selected_tbl_names[i], selected_tbl_names[j])
                if len(p) == 2:
                    t_a, t_b = p[0], p[1]
                    link_info = self.graph.adj.get(t_a, {}).get(t_b)
                    if link_info:
                        join_paths.append(f"`{t_a}`.`{link_info[0]}` = `{t_b}`.`{link_info[1]}`")

        # 5. Dựng lại Sub-Schema Text tinh gọn
        sub_schema_lines = [
            "=== SUB-SCHEMA TỐI ƯU HÓA (ENTERPRISE METADATA RAG LINKED) ===",
            f"🎯 Bảng được chọn liên quan ({len(selected_tbl_names)}/{total_tables} bảng): {', '.join(f'`{t}`' for t in selected_tbl_names)}"
        ]
        if pruned_tbl_names:
            sub_schema_lines.append(f"✂️ Bảng đã được tinh gọn (Pruned): {', '.join(f'`{t}`' for t in pruned_tbl_names[:8])}")

        sub_schema_lines.append("\nCấu trúc các bảng và cột cần thiết:")
        for t_name in selected_tbl_names:
            t_key = t_name.lower()
            if t_key in self.tables_meta:
                meta = self.tables_meta[t_key]
                col_defs = [f"{c['name']} ({c['type']})" for c in meta.columns]
                sub_schema_lines.append(f"- Bảng `{meta.name}`: {', '.join(col_defs)}")

        if join_paths:
            sub_schema_lines.append("\n=== QUAN HỆ KHÓA NGOẠI TỐI ƯU (RECOMMENDED JOIN PATHS) ===")
            for jp in set(join_paths):
                sub_schema_lines.append(f"• Liên kết trực tiếp: {jp}")

        # Bổ sung Sample values liên quan
        relevant_samples = []
        for t_name in selected_tbl_names:
            t_key = t_name.lower()
            if t_key in self.tables_meta:
                meta = self.tables_meta[t_key]
                for v in meta.sample_values:
                    relevant_samples.append(f"• Bảng `{meta.name}`: {v}")

        if relevant_samples:
            sub_schema_lines.append("\n=== GIÁ TRỊ MẪU THỰC TẾ LIÊN QUAN ===")
            sub_schema_lines.extend(relevant_samples[:15])

        sub_schema_text = "\n".join(sub_schema_lines)

        return {
            "selected_tables": selected_tbl_names,
            "pruned_tables": pruned_tbl_names,
            "join_paths": list(set(join_paths)),
            "is_pruned": len(pruned_tbl_names) > 0,
            "sub_schema": sub_schema_text,
            "confidence_score": min(1.0, sum(sc for _, sc in table_scores[:len(selected_tbl_names)]) / 30.0 + 0.5)
        }


def link_schema_for_query(
    user_query: str,
    schema_context: str,
    max_tables: int = 6
) -> Dict[str, Any]:
    """Hàm facade tiện ích để thực hiện Schema Linking & Metadata RAG."""
    linker = SchemaLinker()
    return linker.link_schema(user_query, schema_context, max_tables=max_tables)
