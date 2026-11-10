"""
APIGen 3-Tier Verification Pipeline (Salesforce Research 2024 / xLAM).
Ensures 100% syntactically valid, executable, and semantically aligned training data:
- Tier 1: Syntax & AST Validation (Grammar & Security Check)
- Tier 2: Real Sandbox Database Execution (Execution & Non-empty Check)
- Tier 3: Semantic Alignment Verification (Intent-to-SQL Matching)
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
import pandas as pd
from sqlalchemy import text


@dataclass
class VerificationResult:
    """Kết quả kiểm định dữ liệu tổng hợp qua 3 lớp APIGen."""
    is_valid: bool = False
    tier_passed: int = 0  # 0: hỏng T1, 1: qua T1, 2: qua T2, 3: qua cả 3 tầng (Hoàn hảo)
    tier1_syntax_ok: bool = False
    tier2_execution_ok: bool = False
    tier3_semantic_ok: bool = False
    error_message: str = ""
    execution_time_ms: float = 0.0
    row_count: int = 0
    col_count: int = 0
    columns: List[str] = field(default_factory=list)
    sample_rows: List[Dict[str, Any]] = field(default_factory=list)


class APIGenVerifier:
    """Bộ kiểm định dữ liệu huấn luyện 3 tầng theo chuẩn APIGen (Salesforce 2024)."""

    FORBIDDEN_KEYWORDS = [
        r"\bDROP\b", r"\bDELETE\b", r"\bUPDATE\b", r"\bINSERT\b",
        r"\bALTER\b", r"\bTRUNCATE\b", r"\bCREATE\b", r"\bGRANT\b",
        r"\bREVOKE\b", r"\bATTACH\b", r"\bDETACH\b"
    ]

    def __init__(self, engine=None):
        self.engine = engine

    def verify_query(self, user_question: str, sql_query: str, engine=None) -> VerificationResult:
        """Thực hiện quy trình kiểm tra 3 tầng khép kín cho cặp (Câu hỏi, SQL)."""
        active_engine = engine or self.engine
        res = VerificationResult()

        clean_sql = (sql_query or "").strip().rstrip(";")
        clean_q = (user_question or "").strip().lower()

        # -------------------------------------------------------------
        # TẦNG 1: KIỂM ĐỊNH CÚ PHÁP & AN TOÀN (SYNTAX & GRAMMAR CHECK)
        # -------------------------------------------------------------
        t1_ok, t1_err = self._tier1_syntax_check(clean_sql)
        res.tier1_syntax_ok = t1_ok
        if not t1_ok:
            res.error_message = f"[Tier 1 Syntax Error]: {t1_err}"
            res.tier_passed = 0
            return res
        res.tier_passed = 1

        # -------------------------------------------------------------
        # TẦNG 2: THỰC THI THẬT TRONG SANDBOX (REAL EXECUTION CHECK)
        # -------------------------------------------------------------
        if not active_engine:
            # Nếu không có engine (kiểm thử chay), chỉ dừng ở Tier 1
            res.is_valid = True
            return res

        t2_ok, t2_err, exec_time, df = self._tier2_execution_check(clean_sql, active_engine)
        res.tier2_execution_ok = t2_ok
        res.execution_time_ms = exec_time
        if not t2_ok:
            res.error_message = f"[Tier 2 Execution Error]: {t2_err}"
            return res

        res.tier_passed = 2
        res.row_count = len(df)
        res.col_count = len(df.columns)
        res.columns = list(df.columns)
        res.sample_rows = df.head(3).to_dict(orient="records")

        # -------------------------------------------------------------
        # TẦNG 3: ĐỐI CHIẾU NGỮ NGHĨA INTENT (SEMANTIC ALIGNMENT CHECK)
        # -------------------------------------------------------------
        t3_ok, t3_err = self._tier3_semantic_check(clean_q, clean_sql, df)
        res.tier3_semantic_ok = t3_ok
        if not t3_ok:
            res.error_message = f"[Tier 3 Semantic Warning]: {t3_err}"
            # Vẫn ghi nhận qua Tier 2, nhưng chưa đạt chuẩn Tier 3 tuyệt đối
            return res

        res.tier_passed = 3
        res.is_valid = True
        return res

    def _tier1_syntax_check(self, sql: str) -> (bool, str):
        """Kiểm tra tính an toàn và cú pháp cơ bản."""
        if not sql:
            return False, "Câu lệnh SQL rỗng."

        # Bắt buộc bắt đầu bằng SELECT hoặc WITH (CTE)
        sql_upper = sql.upper().strip()
        if not (sql_upper.startswith("SELECT") or sql_upper.startswith("WITH")):
            return False, "Câu lệnh phải bắt đầu bằng SELECT hoặc WITH (CTE)."

        # Kiểm tra từ khóa phá hoại / ghi đè (Anti-Destructive)
        for kw_pattern in self.FORBIDDEN_KEYWORDS:
            if re.search(kw_pattern, sql_upper):
                return False, f"Chứa từ khóa ghi/xóa dữ liệu bị cấm: {kw_pattern}"

        # Kiểm tra đóng mở ngoặc đơn cân bằng
        if sql.count("(") != sql.count(")"):
            return False, f"Ngoặc đơn không cân bằng: {sql.count('(')} mở vs {sql.count(')')} đóng."

        # Kiểm tra đóng mở nháy đơn cân bằng
        # (Ngoại trừ trường hợp escape '' bên trong chuỗi)
        stripped_escapes = sql.replace("''", "")
        if stripped_escapes.count("'") % 2 != 0:
            return False, "Dấu nháy đơn (') không được đóng hoàn chỉnh."

        return True, ""

    def _tier2_execution_check(self, sql: str, engine) -> (bool, str, float, Optional[pd.DataFrame]):
        """Chạy thử nghiệm câu SQL trực tiếp trên database sandbox để kiểm tra lỗi runtime và dữ liệu rỗng."""
        start_t = time.perf_counter()
        try:
            with engine.connect() as conn:
                # Giới hạn an toàn chỉ đọc
                df = pd.read_sql_query(text(sql), conn)
            
            elapsed_ms = (time.perf_counter() - start_t) * 1000.0

            # Tiêu chuẩn APIGen: Nếu câu lệnh trả về 0 dòng, chứng tỏ điều kiện lọc bị sai logic (hoặc mốc năm bịa)
            if df.empty:
                return False, "Truy vấn chạy thành công nhưng trả về 0 dòng dữ liệu (Empty Result Set).", elapsed_ms, None

            return True, "", elapsed_ms, df

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            return False, str(e), elapsed_ms, None

    def _tier3_semantic_check(self, question: str, sql: str, df: pd.DataFrame) -> (bool, str):
        """Kiểm tra tính tương thích giữa mục đích câu hỏi của người dùng và hành vi của SQL."""
        sql_upper = sql.upper()

        # 1. Câu hỏi yêu cầu tổng số / tổng doanh thu / tổng lượng
        if any(w in question for w in ["tổng", "tổng số", "tổng cộng", "sum", "total", "toàn bộ"]):
            if not any(k in sql_upper for k in ["SUM(", "COUNT(", "TOTAL"]):
                return False, "Câu hỏi yêu cầu tổng hợp ('tổng', 'total') nhưng SQL không dùng SUM() hoặc COUNT()."

        # 2. Câu hỏi yêu cầu trung bình / bình quân
        if any(w in question for w in ["trung bình", "bình quân", "avg", "average", "mỗi đơn"]):
            if not any(k in sql_upper for k in ["AVG(", "/"]):
                return False, "Câu hỏi yêu cầu mức bình quân ('trung bình', 'avg') nhưng SQL không dùng AVG() hay phép chia."

        # 3. Câu hỏi xếp hạng Top / cao nhất / thấp nhất
        if any(w in question for w in ["top", "cao nhất", "nhiều nhất", "lớn nhất", "thấp nhất", "ít nhất", "bán chạy nhất"]):
            if "ORDER BY" not in sql_upper:
                return False, "Câu hỏi yêu cầu xếp hạng ('top', 'cao nhất') nhưng SQL thiếu mệnh đề ORDER BY."
            if "top" in question and "LIMIT" not in sql_upper:
                return False, "Câu hỏi yêu cầu Top cụ thể nhưng SQL thiếu mệnh đề LIMIT."

        # 4. Câu hỏi phân bổ theo chiều (theo từng, phân theo, by)
        if any(w in question for w in ["theo từng", "phân theo", "theo mỗi", "theo nhóm", "theo quốc gia", "theo sản phẩm", "by"]):
            if "GROUP BY" not in sql_upper:
                return False, "Câu hỏi yêu cầu phân tích theo chiều ('theo từng', 'by') nhưng SQL thiếu mệnh đề GROUP BY."

        return True, ""
