"""
Synthetic Scenario & Analytical Query Generator.
Generates comprehensive business queries, SQL pairs, and multi-turn decisions:
- Type A: Direct Executable Analytics (Aggregations, Top-N, Multi-table JOINs, Time-series)
- Type B: Ambiguous Queries requiring Clarification (sys.ask_missing_info - When2Call)
- Type C: Out-of-Scope Queries requiring Abstention (abstain / out-of-domain - When2Call & BFCL)
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from sqlalchemy import inspect, text
from src.data_gen.verifier import APIGenVerifier, VerificationResult
from src.data_gen.masking import SchemaMasker


@dataclass
class SyntheticSample:
    """Đại diện cho một mẫu dữ liệu huấn luyện được sinh ra."""
    sample_id: str
    sample_type: str  # "tool_sql", "ask_missing_info", "abstain"
    query_vi: str
    query_en: str
    target_sql: str = ""
    masked_sql: str = ""
    expected_response: str = ""
    rejected_response: str = ""  # Dành cho huấn luyện DPO (Negative Sample)
    category: str = "general"
    verification: Optional[VerificationResult] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class SyntheticDataGenerator:
    """Bộ máy sinh kịch bản dữ liệu huấn luyện đa dạng cho Veraxus."""

    def __init__(self, engine, verifier: Optional[APIGenVerifier] = None, masker: Optional[SchemaMasker] = None):
        self.engine = engine
        self.verifier = verifier or APIGenVerifier(engine)
        self.masker = masker or SchemaMasker(engine)
        self.inspector = inspect(engine) if engine else None
        self.tables_info: List[Dict[str, Any]] = []
        self._analyze_schema()

    def _analyze_schema(self):
        """Khám phá tự động cấu trúc bảng, các trường đo lường (Metrics) và trường phân loại (Dimensions)."""
        if not self.inspector:
            return

        self.tables_info.clear()
        for t_name in self.inspector.get_table_names():
            columns = self.inspector.get_columns(t_name)
            pk = self.inspector.get_pk_constraint(t_name).get("constrained_columns", [])
            fks = self.inspector.get_foreign_keys(t_name)

            col_defs = []
            for col in columns:
                c_name = col["name"]
                c_type = str(col["type"]).upper()
                col_defs.append({
                    "name": c_name,
                    "type": c_type,
                    "is_pk": c_name in pk,
                    "is_numeric": any(k in c_type for k in ["INT", "FLOAT", "DOUBLE", "DECIMAL", "NUMERIC", "REAL"]),
                    "is_date": any(k in c_type for k in ["DATE", "TIME", "YEAR"]),
                    "is_text": any(k in c_type for k in ["CHAR", "VARCHAR", "TEXT", "STRING"])
                })

            self.tables_info.append({
                "name": t_name,
                "columns": col_defs,
                "foreign_keys": fks,
                "description": f"Bảng dữ liệu {t_name}"
            })

    def generate_batch(
        self,
        num_samples: int = 50,
        trilemma_distribution: Optional[Dict[str, float]] = None,
        apply_masking: bool = False
    ) -> List[SyntheticSample]:
        """Sinh một tập dữ liệu hàng loạt bao gồm cả 3 hành vi (Gọi Tool, Hỏi lại, Từ chối)."""
        dist = trilemma_distribution or {"tool_sql": 0.70, "ask_missing_info": 0.15, "abstain": 0.15}
        samples: List[SyntheticSample] = []

        n_tool = int(num_samples * dist.get("tool_sql", 0.70))
        n_ask = int(num_samples * dist.get("ask_missing_info", 0.15))
        n_abstain = num_samples - n_tool - n_ask

        # 1. Sinh các câu hỏi phân tích SQL thực tế (Type A: Tool SQL)
        tool_samples = self._generate_sql_samples(n_tool, apply_masking)
        samples.extend(tool_samples)

        # 2. Sinh các câu hỏi mơ hồ thiếu thông tin (Type B: Ask Missing Info - When2Call)
        ask_samples = self._generate_ask_missing_samples(n_ask)
        samples.extend(ask_samples)

        # 3. Sinh các câu hỏi ngoài phạm vi (Type C: Abstain / Out-of-Domain - When2Call)
        abstain_samples = self._generate_abstain_samples(n_abstain)
        samples.extend(abstain_samples)

        random.shuffle(samples)
        return samples

    def _generate_sql_samples(self, target_count: int, apply_masking: bool) -> List[SyntheticSample]:
        """Sinh các kịch bản Text-to-SQL và kiểm định qua bộ lọc 3 tầng của APIGen."""
        results: List[SyntheticSample] = []
        if not self.tables_info:
            return results

        # Khởi tạo Masking map nếu bật Hammer
        if apply_masking:
            self.masker.build_masking_maps(self.tables_info)

        # Mẫu kịch bản có sẵn dựa trên schema phát hiện
        table_names = [t["name"] for t in self.tables_info]
        is_choc = any(t in table_names for t in ["sales", "products", "people", "geo"])

        candidate_templates = []
        if is_choc:
            candidate_templates = self._get_chocolate_domain_templates()
        else:
            candidate_templates = self._get_generic_domain_templates()

        idx = 1
        for item in candidate_templates:
            if len(results) >= target_count:
                break

            q_vi = item["q_vi"]
            q_en = item["q_en"]
            sql = item["sql"]

            # Kiểm định APIGen 3 tầng
            ver_res = self.verifier.verify_query(q_vi, sql, self.engine)
            if not ver_res.is_valid:
                # Bị loại bởi bộ lọc APIGen (Lỗi syntax hoặc empty result)
                continue

            masked_sql = self.masker.mask_sql(sql) if apply_masking else ""

            s = SyntheticSample(
                sample_id=f"SYN_SQL_{idx:04d}",
                sample_type="tool_sql",
                query_vi=q_vi,
                query_en=q_en,
                target_sql=sql,
                masked_sql=masked_sql,
                expected_response=f"```sql\n{sql}\n```",
                category=item.get("cat", "analytics"),
                verification=ver_res,
                metadata={
                    "rows_returned": ver_res.row_count,
                    "exec_ms": round(ver_res.execution_time_ms, 2),
                    "tier_passed": ver_res.tier_passed
                }
            )
            results.append(s)
            idx += 1

        return results

    def _generate_ask_missing_samples(self, count: int) -> List[SyntheticSample]:
        """Sinh kịch bản người dùng đưa câu hỏi mơ hồ -> Agent chủ động hỏi lại (When2Call)."""
        scenarios = [
            {
                "q_vi": "Cho tôi xem số liệu doanh thu",
                "q_en": "Show me revenue figures",
                "expected": "Dạ, bạn muốn xem tổng doanh thu theo chu kỳ Quý hay lọc cụ thể theo Quốc gia, Sản phẩm nào ạ?",
                "rejected": "SELECT SUM(Amount) FROM sales WHERE SaleDate >= '2024-01-01';",  # Bịa năm 2024
                "cat": "missing_time_dimension"
            },
            {
                "q_vi": "So sánh doanh số bán hàng",
                "q_en": "Compare sales performance",
                "expected": "Bạn muốn đối chiếu doanh số giữa năm 2021 với 2022 hay so sánh giữa các Team kinh doanh?",
                "rejected": "SELECT * FROM sales LIMIT 5;",
                "cat": "missing_comparison_target"
            },
            {
                "q_vi": "Ai là người bán xuất sắc nhất?",
                "q_en": "Who is the top salesperson?",
                "expected": "Dạ bạn muốn tìm người bán dẫn đầu theo tiêu chí Doanh thu (Amount) hay Sản lượng hộp (Boxes) trong năm nào ạ?",
                "rejected": "SELECT Salesperson, MAX(Amount) FROM sales;",  # SQL sai cú pháp logic
                "cat": "missing_metric_criterion"
            },
            {
                "q_vi": "Sản phẩm nào đang bị giảm sút?",
                "q_en": "Which products are declining?",
                "expected": "Bạn muốn kiểm tra sự sụt giảm trong Quý gần nhất hay so sánh tốc độ tăng trưởng YoY của cả năm?",
                "rejected": "SELECT Product FROM products WHERE Status = 'declining';",  # Bịa cột Status
                "cat": "missing_time_window"
            },
            {
                "q_vi": "Báo cáo tình hình kinh doanh gần đây",
                "q_en": "Recent business performance report",
                "expected": "Dạ, bạn muốn xem tổng quan Dashboard Doanh số hay tập trung vào phân tích Thị trường & Đội ngũ bán hàng?",
                "rejected": "SELECT * FROM sales ORDER BY SaleDate DESC LIMIT 10;",
                "cat": "vague_intent"
            }
        ]

        results = []
        for i in range(count):
            item = scenarios[i % len(scenarios)]
            s = SyntheticSample(
                sample_id=f"SYN_ASK_{i+1:04d}",
                sample_type="ask_missing_info",
                query_vi=item["q_vi"],
                query_en=item["q_en"],
                target_sql="",
                expected_response=item["expected"],
                rejected_response=item["rejected"],
                category=item["cat"],
                metadata={"behavior": "clarify_proactively"}
            )
            results.append(s)
        return results

    def _generate_abstain_samples(self, count: int) -> List[SyntheticSample]:
        """Sinh kịch bản người dùng hỏi ngoài phạm vi -> Agent từ chối an toàn (When2Call & BFCL)."""
        scenarios = [
            {
                "q_vi": "Dự báo thời tiết Hà Nội ngày mai có mưa không?",
                "q_en": "Will it rain in Hanoi tomorrow?",
                "expected": "Tôi là Trợ lý Dữ liệu Kinh doanh Veraxus. Tôi chỉ hỗ trợ tra cứu và phân tích số liệu nội bộ của doanh nghiệp, không có dữ liệu khí tượng thời tiết bên ngoài.",
                "rejected": "SELECT * FROM weather WHERE city = 'Hanoi';",  # Bịa bảng weather
                "cat": "out_of_domain_weather"
            },
            {
                "q_vi": "Viết giúp tôi một bài thơ tình lãng mạn về mùa thu",
                "q_en": "Write a romantic autumn poem",
                "expected": "Tôi được thiết lập chuyên sâu cho vai trò Giám đốc Dữ liệu Điều hành (AI Business Analyst). Vui lòng đặt câu hỏi liên quan đến doanh số, sản phẩm hoặc nhân sự doanh nghiệp.",
                "rejected": "Mùa thu lá vàng rơi...",
                "cat": "out_of_domain_creative"
            },
            {
                "q_vi": "Giá vàng SJC hôm nay tăng hay giảm bao nhiêu?",
                "q_en": "What is the gold price today?",
                "expected": "CSDL hiện tại chỉ chứa dữ liệu bán hàng và vận hành của doanh nghiệp, không kết nối bảng giá thị trường tài chính bên ngoài.",
                "rejected": "SELECT gold_price FROM market_prices;",  # Bịa bảng
                "cat": "out_of_domain_finance"
            },
            {
                "q_vi": "Hướng dẫn tôi công thức làm món bánh socola hạnh nhân",
                "q_en": "Recipe for chocolate almond cake",
                "expected": "Mặc dù doanh nghiệp kinh doanh sản phẩm chocolate, CSDL chỉ lưu trữ số liệu xuất nhập và doanh thu bán hàng, không chứa công thức chế biến ẩm thực.",
                "rejected": "SELECT recipe FROM products WHERE Product LIKE '%Choco%';",
                "cat": "out_of_domain_cooking"
            }
        ]

        results = []
        for i in range(count):
            item = scenarios[i % len(scenarios)]
            s = SyntheticSample(
                sample_id=f"SYN_ABST_{i+1:04d}",
                sample_type="abstain",
                query_vi=item["q_vi"],
                query_en=item["q_en"],
                target_sql="",
                expected_response=item["expected"],
                rejected_response=item["rejected"],
                category=item["cat"],
                metadata={"behavior": "refuse_politely"}
            )
            results.append(s)
        return results

    def _get_chocolate_domain_templates(self) -> List[Dict[str, str]]:
        """Bộ kịch bản phân tích mẫu đa dạng cho CSDL Awesome Chocolates."""
        return [
            {
                "q_vi": "Tổng doanh thu và tổng số hộp bán ra toàn hệ thống là bao nhiêu?",
                "q_en": "What is the total revenue and total boxes sold across the system?",
                "sql": "SELECT SUM(Amount) AS Total_Revenue, SUM(Boxes) AS Total_Boxes FROM sales;",
                "cat": "kpi_totals"
            },
            {
                "q_vi": "Top 5 sản phẩm có doanh thu cao nhất năm 2022",
                "q_en": "Top 5 products by revenue in 2022",
                "sql": "SELECT p.Product, SUM(s.Amount) AS Revenue FROM sales s JOIN products p ON s.PID = p.PID WHERE s.SaleDate >= '2022-01-01' AND s.SaleDate <= '2022-12-31' GROUP BY p.Product ORDER BY Revenue DESC LIMIT 5;",
                "cat": "ranking_top5"
            },
            {
                "q_vi": "Doanh số bán hàng phân bổ theo từng quốc gia",
                "q_en": "Sales revenue distributed by country",
                "sql": "SELECT g.Geo, SUM(s.Amount) AS Revenue, SUM(s.Boxes) AS Boxes FROM sales s JOIN geo g ON s.GeoID = g.GeoID GROUP BY g.Geo ORDER BY Revenue DESC;",
                "cat": "breakdown_geo"
            },
            {
                "q_vi": "Hiệu suất doanh số của các Team kinh doanh",
                "q_en": "Sales performance by business team",
                "sql": "SELECT p.Team, SUM(s.Amount) AS Total_Sales, COUNT(s.SPID) AS Transaction_Count FROM sales s JOIN people p ON s.SPID = p.SPID GROUP BY p.Team ORDER BY Total_Sales DESC;",
                "cat": "breakdown_team"
            },
            {
                "q_vi": "Giá trị đơn hàng trung bình (AOV) trong năm 2021",
                "q_en": "Average Order Value in 2021",
                "sql": "SELECT AVG(Amount) AS Average_Order_Value FROM sales WHERE SaleDate >= '2021-01-01' AND SaleDate <= '2021-12-31';",
                "cat": "kpi_average"
            },
            {
                "q_vi": "Top 10 nhân sự bán hàng xuất sắc nhất về số lượng hộp",
                "q_en": "Top 10 salespeople by box volume",
                "sql": "SELECT p.Salesperson, p.Team, SUM(s.Boxes) AS Total_Boxes FROM sales s JOIN people p ON s.SPID = p.SPID GROUP BY p.Salesperson, p.Team ORDER BY Total_Boxes DESC LIMIT 10;",
                "cat": "ranking_people"
            },
            {
                "q_vi": "Doanh thu theo từng danh mục sản phẩm (Category)",
                "q_en": "Revenue by product category",
                "sql": "SELECT p.Category, SUM(s.Amount) AS Category_Revenue FROM sales s JOIN products p ON s.PID = p.PID GROUP BY p.Category ORDER BY Category_Revenue DESC;",
                "cat": "breakdown_category"
            },
            {
                "q_vi": "Các đơn hàng có giá trị lớn trên $10,000 tại thị trường Ấn Độ",
                "q_en": "Large orders over $10,000 in India market",
                "sql": "SELECT s.SaleDate, s.Amount, s.Boxes, g.Geo FROM sales s JOIN geo g ON s.GeoID = g.GeoID WHERE s.Amount > 10000 AND g.Geo = 'India' ORDER BY s.Amount DESC;",
                "cat": "filter_high_value"
            },
            {
                "q_vi": "Doanh thu trung bình mỗi tháng trong năm 2022",
                "q_en": "Average monthly revenue in 2022",
                "sql": "SELECT strftime('%Y-%m', SaleDate) AS Month, SUM(Amount) AS Monthly_Revenue FROM sales WHERE SaleDate >= '2022-01-01' AND SaleDate <= '2022-12-31' GROUP BY Month ORDER BY Month ASC;",
                "cat": "time_series_monthly"
            },
            {
                "q_vi": "Thống kê số lượng ticket hỗ trợ khách hàng theo từng mức độ ưu tiên",
                "q_en": "Customer support tickets count by priority level",
                "sql": "SELECT Priority, COUNT(*) AS Ticket_Count, Status FROM crm_tickets GROUP BY Priority, Status ORDER BY Ticket_Count DESC;",
                "cat": "crm_tickets"
            }
        ]

    def _get_generic_domain_templates(self) -> List[Dict[str, str]]:
        """Bộ mẫu tổng quát tự động áp dụng cho CSDL bất kỳ dựa trên Schema phát hiện."""
        templates = []
        for t_info in self.tables_info:
            t_name = t_info["name"]
            num_cols = [c["name"] for c in t_info["columns"] if c["is_numeric"]]
            text_cols = [c["name"] for c in t_info["columns"] if c["is_text"]]

            if num_cols:
                n_col = num_cols[0]
                templates.append({
                    "q_vi": f"Tổng {n_col} và giá trị trung bình trong bảng {t_name}",
                    "q_en": f"Total and average {n_col} in table {t_name}",
                    "sql": f"SELECT SUM({n_col}) AS Total_{n_col}, AVG({n_col}) AS Avg_{n_col} FROM {t_name};",
                    "cat": "generic_kpi"
                })

            if num_cols and text_cols:
                n_col = num_cols[0]
                d_col = text_cols[0]
                templates.append({
                    "q_vi": f"Top 5 {d_col} có {n_col} lớn nhất trong {t_name}",
                    "q_en": f"Top 5 {d_col} with highest {n_col} in {t_name}",
                    "sql": f"SELECT {d_col}, SUM({n_col}) AS Total FROM {t_name} GROUP BY {d_col} ORDER BY Total DESC LIMIT 5;",
                    "cat": "generic_top5"
                })

        return templates
