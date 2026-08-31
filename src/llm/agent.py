"""
SQL Generation and Execution Agent with safety validation, parenthesis checking,
self-healing loop (including 0-row empty result recovery), conversational explanation detection,
automatic business insight discovery with Priority Tagging, bilingual support, and follow-up question suggestions.
"""

import json
import re
import pandas as pd

from src.config import FORBIDDEN_KEYWORDS, MAX_ROWS_CAP
from src.database.query_runner import read_sql_capped, sanitize_error
from src.database.schema import get_table_names
from src.analytics.heuristics import is_id_like, detect_query_language, sanitize_insight_markdown
from src.analytics.anomaly import analyze_data_anomalies
from .client import call_llm
from .prompts import (
    build_sql_prompt,
    build_fix_prompt,
    build_self_check_prompt,
    build_anomaly_prompt,
    build_auto_insight_prompt,
    build_followup_prompt,
)


def strip_comments_and_literals(sql: str) -> str:
    """Loại bỏ comment SQL (#, --, /* */) và chuỗi ký tự trước khi kiểm tra an toàn và cú pháp."""
    # Bỏ comment dạng block /* ... */
    sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
    # Bỏ comment dạng dòng -- ...
    sql = re.sub(r'--[^\n]*', '', sql)
    # Bỏ comment dạng dòng # ...
    sql = re.sub(r'#[^\n]*', '', sql)
    # Bỏ chuỗi ký tự '...' và "..."
    sql = re.sub(r"'[^']*'", "''", sql)
    sql = re.sub(r'"[^"]*"', '""', sql)
    return sql


def check_parentheses_balance(sql: str) -> tuple[bool, str]:
    """Kiểm tra số lượng dấu mở ngoặc '(' và đóng ngoặc ')' trong SQL."""
    cleaned = strip_comments_and_literals(sql)
    open_count = cleaned.count("(")
    close_count = cleaned.count(")")
    if open_count != close_count:
        return False, f"Lỗi cú pháp SQL: Thừa hoặc thiếu dấu ngoặc đơn () (Có {open_count} dấu '(' nhưng có {close_count} dấu ')')."
    return True, ""


def is_safe_select(sql: str) -> bool:
    """Kiểm tra câu lệnh SQL có phải là SELECT/WITH hợp lệ và an toàn không."""
    if not sql:
        return False

    cleaned = strip_comments_and_literals(sql.strip())
    raw_cleaned = cleaned.strip().rstrip(";")
    lowered = raw_cleaned.lower()

    if not (lowered.startswith("select") or lowered.startswith("with")):
        return False

    if ";" in raw_cleaned:  # Chặn stacked queries
        return False

    for kw in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{kw}\b", lowered):
            return False
    return True


def is_conversational_explanation(text_response: str) -> bool:
    """Nhận diện khi mô hình AI trả về câu giải thích tự nhiên (ví dụ: schema không có bảng phù hợp) thay vì SQL."""
    if not text_response:
        return False

    cleaned = text_response.strip().lower()
    explanation_indicators = [
        "tôi xin lỗi", "xin lỗi", "tôi xin nhận lỗi", "không có bảng", "không tìm thấy bảng",
        "schema không có", "schema không chứa", "không chứa thông tin", "không thể cung cấp câu sql",
        "câu hỏi yêu cầu dữ liệu từ các bảng không tồn tại", "cơ sở dữ liệu không có",
        "sorry", "i apologize", "no table found", "schema does not contain", "cannot write a query"
    ]
    return any(indicator in cleaned for indicator in explanation_indicators)


def detect_duplicate_entity_warning(df: pd.DataFrame) -> str | None:
    """Kiểm tra xem có dấu hiệu nhân bản dữ liệu do JOIN bảng lịch sử không."""
    if df is None or df.empty:
        return None

    id_cols = [c for c in df.columns if is_id_like(c)]
    for c in id_cols:
        try:
            n_unique = df[c].nunique(dropna=True)
        except Exception:
            continue
        if 0 < n_unique < len(df):
            return (
                f"Cột `{c}` chỉ có {n_unique} giá trị duy nhất nhưng kết quả trả về "
                f"{len(df)} dòng (dấu hiệu JOIN với bảng lịch sử chưa lọc bản ghi hiện tại)."
            )
    return None


def self_check_sql(client, provider: str, model_name: str, schema_context: str, user_query: str, sql_query: str, df: pd.DataFrame, lang: str = "vi") -> dict:
    """Thực hiện bước AI QA self-check để kiểm định kết quả SQL."""
    sample = df.head(5).to_string(index=False)
    prompt = build_self_check_prompt(schema_context, user_query, sql_query, sample, lang=lang)
    res, err = call_llm(client, provider, model_name, prompt)

    if not res:
        return {"day_du": True, "ly_do": "Bỏ qua self-check."}

    try:
        cleaned = res.strip().strip("`").replace("json\n", "").strip()
        parsed = json.loads(cleaned)
        ly_do = str(parsed.get("ly_do", ""))
        if len(ly_do) > 200:
            ly_do = ly_do[:200].rsplit(" ", 1)[0] + "..."
        parsed["ly_do"] = ly_do
        return parsed
    except Exception:
        return {"day_du": True, "ly_do": "Không parse được JSON self-check."}


def explain_anomalies_agent(client, provider: str, model_name: str, user_query: str, x_col: str, y_col: str, outliers_df: pd.DataFrame, lang: str = "vi") -> str | None:
    """Gọi LLM giải thích nguyên nhân kinh doanh của các điểm bất thường."""
    points = outliers_df[[x_col, y_col]].to_dict(orient="records")
    prompt = build_anomaly_prompt(user_query, x_col, y_col, points, lang=lang)
    res, _ = call_llm(client, provider, model_name, prompt)
    return res


def generate_auto_insights(client, provider: str, model_name: str, user_query: str, df: pd.DataFrame, anomalies_info: dict, lang: str = "vi") -> str | None:
    """Tự động phân tích và sinh báo cáo Insight Kinh doanh với Gắn Nhãn Mức Độ Ưu Tiên (Priority Tagging)."""
    if df is None or df.empty:
        return None

    sample_str = df.head(10).to_string(index=False)
    prompt = build_auto_insight_prompt(user_query, sample_str, anomalies_info, lang=lang)
    insight, _ = call_llm(client, provider, model_name, prompt)
    if insight:
        return sanitize_insight_markdown(insight)
    return None


def is_ambiguous_question(q: str) -> bool:
    """Kiểm tra câu hỏi có chứa các đại từ mơ hồ (này, đó, trên, these...) gây lỗi 0 dòng khi chạy độc lập."""
    if not q:
        return True
    q_low = q.lower()
    ambiguous_patterns = [
        r"\b\d+\s*nhân viên này\b", r"\bnhân viên này\b", r"\bsản phẩm này\b",
        r"\bnhóm này\b", r"\bđối tượng này\b", r"\bkhu vực này\b",
        r"\bthị trường này\b", r"\bthese\b", r"\bthis product\b", r"\bthese reps\b"
    ]
    return any(re.search(p, q_low) for p in ambiguous_patterns)


def generate_grounded_fallback_followups(df: pd.DataFrame, lang: str = "vi") -> list[str]:
    """Sinh các câu hỏi đào sâu bám sát 100% vào các thực thể cụ thể có sẵn trong kết quả truy vấn."""
    if df is None or df.empty:
        return []

    followups = []
    cols = df.columns.tolist()

    # 1. Nếu có cột Team / Nhóm
    team_col = next((c for c in cols if "team" in c.lower() or "nhóm" in c.lower()), None)
    if team_col:
        valid_teams = [str(v).strip() for v in df[team_col].dropna().unique() if str(v).strip() and "(chưa" not in str(v).lower()]
        if valid_teams:
            t_name = valid_teams[0]
            if lang == "en":
                followups.append(f"Top 5 sales representatives in {t_name} team")
                followups.append(f"Monthly sales revenue for {t_name} team")
                followups.append(f"Best selling chocolate products by {t_name} team")
            else:
                followups.append(f"Top 5 nhân viên có doanh số cao nhất trong nhóm {t_name}")
                followups.append(f"Doanh số của nhóm {t_name} theo từng tháng")
                followups.append(f"Các sản phẩm bán chạy nhất của nhóm {t_name}")
            return followups[:3]

    # 2. Nếu có cột Product / Sản phẩm
    prod_col = next((c for c in cols if "product" in c.lower() or "sản phẩm" in c.lower()), None)
    if prod_col:
        valid_prods = [str(v).strip() for v in df[prod_col].dropna().unique() if str(v).strip()]
        if valid_prods:
            p_name = valid_prods[0]
            if lang == "en":
                followups.append(f"Monthly revenue trend for {p_name}")
                followups.append(f"Top 5 sales representatives selling {p_name}")
                followups.append(f"Sales distribution of {p_name} across countries")
            else:
                followups.append(f"Doanh số sản phẩm {p_name} theo từng tháng")
                followups.append(f"Top 5 nhân viên bán được nhiều sản phẩm {p_name} nhất")
                followups.append(f"Phân bổ doanh thu của sản phẩm {p_name} theo từng quốc gia")
            return followups[:3]

    # 3. Nếu có cột Salesperson / Người bán
    rep_col = next((c for c in cols if "salesperson" in c.lower() or "nhân viên" in c.lower() or "people" in c.lower()), None)
    if rep_col:
        valid_reps = [str(v).strip() for v in df[rep_col].dropna().unique() if str(v).strip()]
        if valid_reps:
            r_name = valid_reps[0]
            if lang == "en":
                followups.append(f"Monthly sales performance of {r_name}")
                followups.append(f"Top products sold by {r_name}")
                followups.append(f"Sales revenue by country for {r_name}")
            else:
                followups.append(f"Doanh số của nhân viên {r_name} theo từng tháng")
                followups.append(f"Các sản phẩm bán chạy nhất của nhân viên {r_name}")
                followups.append(f"Doanh thu theo từng quốc gia của nhân viên {r_name}")
            return followups[:3]

    # 4. Nếu có cột Geo / Quốc gia / Khu vực
    geo_col = next((c for c in cols if "geo" in c.lower() or "country" in c.lower() or "quốc gia" in c.lower()), None)
    if geo_col:
        valid_geos = [str(v).strip() for v in df[geo_col].dropna().unique() if str(v).strip()]
        if valid_geos:
            g_name = valid_geos[0]
            if lang == "en":
                followups.append(f"Top 5 best selling products in {g_name}")
                followups.append(f"Monthly sales trend in {g_name}")
            else:
                followups.append(f"Top 5 sản phẩm bán chạy nhất tại thị trường {g_name}")
                followups.append(f"Xu hướng doanh số theo từng tháng tại thị trường {g_name}")
            return followups[:3]

    return followups


def generate_followup_questions(client, provider: str, model_name: str, user_query: str, schema_context: str, df: pd.DataFrame, lang: str = "vi") -> list[str]:
    """Tự động sinh 2-3 câu hỏi gợi ý phân tích tiếp nối (Follow-up suggestions) bám sát 100% vào thực thể có thật."""
    if df is None or df.empty:
        return []

    # 1. Chuẩn bị các câu hỏi dự phòng bám sát thực thể có thật trong kết quả
    fallback_questions = generate_grounded_fallback_followups(df, lang=lang)

    # 2. Gọi AI để sinh câu hỏi phân tích thông minh
    try:
        sample_str = df.head(5).to_string(index=False)
        prompt = build_followup_prompt(user_query, schema_context, sample_str, lang=lang)
        res, _ = call_llm(client, provider, model_name, prompt)

        ai_questions = []
        if res:
            cleaned = res.strip().strip("`").replace("json\n", "").strip()
            parsed = json.loads(cleaned)
            if isinstance(parsed, list):
                for q in parsed:
                    q_str = str(q).strip()
                    # Loại bỏ các câu hỏi chứa đại từ mơ hồ "này", "đó", "these reps"
                    if q_str and not is_ambiguous_question(q_str):
                        ai_questions.append(q_str)

        # 3. Kết hợp câu hỏi AI với câu hỏi bám sát thực thể
        combined = []
        for q in ai_questions:
            if q not in combined:
                combined.append(q)
        for q in fallback_questions:
            if q not in combined:
                combined.append(q)

        return combined[:3] if combined else fallback_questions[:3]
    except Exception:
        return fallback_questions[:3]


def run_agent(
    user_query: str,
    client,
    provider: str,
    model_name: str,
    engine,
    schema_context: str,
    dialect: str = "SQLite",
    db_pass: str = "",
    enable_self_check: bool = True,
    enable_auto_insights: bool = True
) -> dict:
    """Điều phối toàn bộ chu trình Text-to-SQL, tự sửa lỗi âm thầm (bao gồm cứu kết quả 0 dòng) và tự động khám phá Insight."""
    # 0. Tự động nhận diện ngôn ngữ của câu hỏi (vi / en)
    lang = detect_query_language(user_query)

    result = {
        "query": user_query,
        "lang": lang,
        "df": None,
        "sql": None,
        "logs": [],
        "attempts": 0,
        "error": None,
        "explanation": None,
        "anomalies_info": None,
        "insights": None,
        "followups": [],
    }

    # 1. Sinh SQL ban đầu
    initial_prompt = build_sql_prompt(schema_context, dialect, user_query, lang=lang)
    sql_query, err = call_llm(client, provider, model_name, initial_prompt)

    if not sql_query:
        result["error"] = "Could not generate SQL from AI model." if lang == "en" else f"Không thể tạo SQL từ mô hình AI.{' Lý do: ' + err if err else ''}"
        return result

    # 1.1 Kiểm tra nếu AI trả về câu giải thích (ví dụ: schema không có dữ liệu này)
    if is_conversational_explanation(sql_query):
        result["explanation"] = sql_query
        return result

    # 2. Vòng lặp thực thi, kiểm định và tự sửa lỗi âm thầm (Silent Self-Healing)
    for attempt in range(1, 4):
        result["attempts"] = attempt
        result["logs"].append(f"[Lần {attempt}] SQL: {sql_query}")

        # Kiểm tra nếu ở các lần thử AI nhận ra không có bảng phù hợp
        if is_conversational_explanation(sql_query):
            result["explanation"] = sql_query
            return result

        if not is_safe_select(sql_query):
            result["logs"].append("❌ Kiểm tra an toàn thất bại: Không phải lệnh SELECT/WITH an toàn.")
            if attempt == 3:
                result["error"] = "Unsafe SQL query (Only single SELECT/WITH statements allowed)." if lang == "en" else "Câu lệnh SQL không an toàn (Chỉ chấp nhận lệnh SELECT/WITH đơn, không nhiều câu lệnh)."
                result["sql"] = sql_query
                return result

            fix_prompt = build_fix_prompt(
                schema_context, dialect, user_query, sql_query,
                "Query must start with SELECT or WITH and contain no forbidden keywords.",
                lang=lang
            )
            fixed_sql, _ = call_llm(client, provider, model_name, fix_prompt)
            sql_query = fixed_sql or sql_query
            continue

        # 2.1 Kiểm tra cân đối dấu ngoặc trước khi thực thi
        is_balanced, paren_err = check_parentheses_balance(sql_query)
        if not is_balanced:
            result["logs"].append(f"❌ Phát hiện lỗi cú pháp dấu ngoặc: {paren_err}")
            if attempt == 3:
                result["error"] = f"Thử sửa 3 lần thất bại: {paren_err}"
                result["sql"] = sql_query
                return result

            fix_prompt = build_fix_prompt(
                schema_context, dialect, user_query, sql_query, paren_err, lang=lang
            )
            fixed_sql, _ = call_llm(client, provider, model_name, fix_prompt)
            sql_query = fixed_sql or sql_query
            continue

        # 2.2 Thực thi SQL trên Database Engine
        try:
            df, truncated = read_sql_capped(sql_query, engine, cap=MAX_ROWS_CAP)
            if truncated:
                result["logs"].append(f"⚠️ Dữ liệu lớn: đã dừng đọc ở {MAX_ROWS_CAP:,} dòng để bảo vệ hệ thống.")

            # Tự động phát hiện & sửa nếu kết quả trả về 0 dòng (0-Row Empty Result Recovery)
            if df is not None and df.empty and attempt < 3:
                result["logs"].append("⚠️ Kết quả trả về 0 dòng dữ liệu (dấu hiệu dùng CURRENT_DATE(), lọc WHERE quá chặt, hoặc năm không có dữ liệu). Đang tự động điều chỉnh và thử lại...")
                empty_fix_reason = (
                    "SQL executed successfully but returned 0 ROWS OF DATA.\n"
                    "- If query filters by a specific year/quarter (e.g. 2023 / Q3 2023) that does not exist in the DB: Check the Date Range in the Schema above and adjust query to the latest available year in the dataset (e.g. 2021 / 2022) or remove restrictive date filters.\n"
                    "- If query uses CURRENT_DATE(), NOW(), CURDATE(): This DB contains historical data. Use (SELECT MAX(date_col) FROM table_name) as reference.\n"
                    "- If query filters Category/Product string: Relax or remove unnecessary WHERE conditions to fetch real data!"
                    if lang == "en" else
                    "Câu lệnh SQL đã thực thi thành công nhưng trả về 0 DÒNG DỮ LIỆU.\n"
                    "- Nếu câu lệnh lọc theo năm/quý cụ thể (như năm 2023 hoặc Quý 3 năm 2023) mà CSDL không có dữ liệu: Hãy nhìn vào phần KHOẢNG THỜI GIAN THỰC TẾ TRONG DỮ LIỆU ở Schema trên và điều chỉnh câu lệnh lấy năm gần nhất có dữ liệu (như năm 2021 hoặc 2022) hoặc bỏ điều kiện năm để trả về số liệu thực tế cho người dùng!\n"
                    "- Nếu câu lệnh có dùng CURRENT_DATE(), NOW(), CURDATE() hoặc lọc mốc năm cứng: CSDL này chứa dữ liệu lịch sử. Hãy thay thế bằng (SELECT MAX(date_col) FROM table_name) làm mốc ngày gần nhất hoặc bỏ lọc ngày để lấy dữ liệu thực tế.\n"
                    "- Nếu câu lệnh lọc Category/Product/Tên chuỗi: Hãy loại bỏ hoặc nới lỏng các điều kiện WHERE không cần thiết để trả về đúng dữ liệu thực tế cho người dùng!"
                )
                fix_prompt = build_fix_prompt(
                    schema_context, dialect, user_query, sql_query, empty_fix_reason, lang=lang
                )
                fixed_sql, _ = call_llm(client, provider, model_name, fix_prompt)
                sql_query = fixed_sql or sql_query
                continue

            dup_warning = detect_duplicate_entity_warning(df)
            if dup_warning:
                result["logs"].append(f"⚠️ Cảnh báo: {dup_warning}")

            if enable_self_check:
                check = self_check_sql(client, provider, model_name, schema_context, user_query, sql_query, df, lang=lang)
            else:
                check = {"day_du": True, "ly_do": "Skipped self-check." if lang == "en" else "Bỏ qua self-check (đã tắt trong cài đặt)."}

            if check.get("day_du", True) or attempt == 3:
                if check.get("day_du", True):
                    result["logs"].append(f"✅ Kiểm định SQL OK: {check.get('ly_do', 'SQL hợp lệ')}")
                else:
                    result["logs"].append(f"⚠️ Chấp nhận kết quả sau {attempt} lần thử: {check.get('ly_do', '')}")

                result["df"] = df
                result["sql"] = sql_query

                # 3. Tự động phát hiện bất thường & sinh Insight Kinh doanh với Priority Tagging
                if df is not None and not df.empty:
                    anomalies_info = analyze_data_anomalies(df)
                    result["anomalies_info"] = anomalies_info

                    if enable_auto_insights:
                        insights = generate_auto_insights(
                            client, provider, model_name, user_query, df, anomalies_info, lang=lang
                        )
                        result["insights"] = insights

                    # 4. Tự động sinh 2-3 câu hỏi gợi ý phân tích tiếp nối (Follow-up Questions)
                    followups = generate_followup_questions(
                        client, provider, model_name, user_query, schema_context, df, lang=lang
                    )
                    result["followups"] = followups

                return result

            result["logs"].append(f"⚠️ QA Self-check phát hiện vấn đề: {check.get('ly_do', '')}")
            fix_prompt = build_fix_prompt(
                schema_context, dialect, user_query, sql_query, check.get("ly_do", ""), lang=lang
            )
            fixed_sql, _ = call_llm(client, provider, model_name, fix_prompt)
            sql_query = fixed_sql or sql_query

        except Exception as e:
            error_msg = sanitize_error(str(e), db_pass)
            result["logs"].append(f"❌ Lỗi thực thi SQL: {error_msg}")
            if attempt == 3:
                result["error"] = f"Thử sửa 3 lần thất bại: {error_msg}"
                result["sql"] = sql_query
                return result

            # Bắt lỗi 1146 / Table doesn't exist để tự động bơm danh sách bảng thực tế
            augmented_error = error_msg
            lowered_err = error_msg.lower()
            if "doesn't exist" in lowered_err or "1146" in lowered_err or "no such table" in lowered_err:
                try:
                    valid_tables = get_table_names(engine)
                    if valid_tables:
                        augmented_error += (
                            f"\n\nNOTE: The table you referenced does not exist! "
                            f"Valid tables in this database are ONLY: {', '.join(valid_tables)}. "
                            f"Please strictly write SQL using ONLY these tables!"
                            if lang == "en" else
                            f"\n\nLƯU Ý ĐẶC BIỆT: Bảng bạn vừa gọi không tồn tại trong database này! "
                            f"Database này CHỈ CÓ CÁC BẢNG SAU: {', '.join(valid_tables)}. "
                            f"Hãy nhìn kỹ danh sách trên và viết lại SQL dùng đúng các bảng này!"
                        )
                except Exception:
                    pass

            fix_prompt = build_fix_prompt(
                schema_context, dialect, user_query, sql_query, augmented_error, lang=lang
            )
            fixed_sql, _ = call_llm(client, provider, model_name, fix_prompt)
            sql_query = fixed_sql or sql_query

    return result
