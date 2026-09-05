"""
Reusable UI components for rendering query results, charts, forecasts, automated insights,
follow-up question suggestions, and multi-format reporting export (Excel, PNG, PDF).
Features clean Silent Fix interface, Priority Tagging display, Bilingual English/Vietnamese support,
1-Click Copy Error button, and conversational AI explanation handling.
"""

import re
import streamlit as st
import pandas as pd
from src.analytics.heuristics import get_axis_columns, sanitize_insight_markdown, pick_label_column, is_id_like, sanitize_followup_question, split_insight_sections
from src.analytics.anomaly import analyze_data_anomalies
from src.analytics.forecasting import forecast_series
from src.analytics.export_reports import export_to_excel, export_to_png, export_to_pdf
from src.analytics.share_report import send_telegram_report, send_email_report
from src.config_store import load_saved_config
from src.visualization.charts import render_smart_chart
from src.llm.agent import generate_auto_insights


def render_voice_input_button(key: str = "voice_input_widget"):
    """Hiển thị nút Micro nhập liệu bằng giọng nói tiếng Việt thời gian thực (Web Speech API)."""
    voice_html = """
    <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 8px;">
        <button id="micBtn" onclick="toggleSpeechRecognition()" style="
            background: linear-gradient(135deg, #1F4E78 0%, #2563EB 100%);
            color: #ffffff;
            border: none;
            border-radius: 20px;
            padding: 7px 16px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            transition: all 0.2s ease;
        ">
            <span id="micIcon">🎙️</span> <span id="micText">Nói câu hỏi (Tiếng Việt)</span>
        </button>
        <span id="speechStatus" style="font-size: 13px; color: #475569; font-style: italic;"></span>
    </div>
    <script>
        let recognition = null;
        let isListening = false;

        function toggleSpeechRecognition() {
            const micBtn = document.getElementById('micBtn');
            const micIcon = document.getElementById('micIcon');
            const micText = document.getElementById('micText');
            const speechStatus = document.getElementById('speechStatus');

            if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
                alert('Trình duyệt của bạn chưa hỗ trợ nhận diện giọng nói (Web Speech API). Vui lòng sử dụng Google Chrome, Microsoft Edge hoặc Safari.');
                return;
            }

            if (isListening) {
                if (recognition) recognition.stop();
                isListening = false;
                micBtn.style.background = 'linear-gradient(135deg, #1F4E78 0%, #2563EB 100%)';
                micIcon.innerText = '🎙️';
                micText.innerText = 'Nói câu hỏi (Tiếng Việt)';
                speechStatus.innerText = '';
                return;
            }

            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            recognition = new SpeechRecognition();
            recognition.lang = 'vi-VN';
            recognition.continuous = false;
            recognition.interimResults = false;

            recognition.onstart = function() {
                isListening = true;
                micBtn.style.background = '#DC2626';
                micIcon.innerText = '🔴';
                micText.innerText = 'Đang lắng nghe...';
                speechStatus.innerText = 'Hãy nói câu hỏi của bạn vào micro...';
            };

            recognition.onresult = function(event) {
                const transcript = event.results[0][0].transcript.trim();
                speechStatus.innerText = 'Đã điền câu hỏi! Bạn có thể sửa nếu cần và nhấn Enter hoặc ⬆️ để gửi.';
                
                // Cập nhật vào Streamlit chat_input thông qua React Native Property Setter
                const textAreas = window.parent.document.querySelectorAll('textarea, input[type="text"]');
                for (let ta of textAreas) {
                    if (ta.placeholder && (ta.placeholder.includes('Hỏi bất kỳ') || ta.placeholder.includes('Ask anything'))) {
                        try {
                            const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value")?.set;
                            if (nativeSetter) {
                                nativeSetter.call(ta, transcript);
                            } else {
                                ta.value = transcript;
                            }
                        } catch(e) {
                            ta.value = transcript;
                        }
                        
                        ta.dispatchEvent(new Event('input', { bubbles: true }));
                        ta.dispatchEvent(new Event('change', { bubbles: true }));
                        
                        // Đặt con trỏ chuột vào ô chat để người dùng xem và sửa tiếp
                        ta.focus();
                        try {
                            ta.setSelectionRange(ta.value.length, ta.value.length);
                        } catch(e) {}
                        break;
                    }
                }
            };

            recognition.onerror = function(event) {
                isListening = false;
                micBtn.style.background = 'linear-gradient(135deg, #1F4E78 0%, #2563EB 100%)';
                micIcon.innerText = '🎙️';
                micText.innerText = 'Nói câu hỏi (Tiếng Việt)';
                speechStatus.innerText = 'Lỗi: ' + event.error;
            };

            recognition.onend = function() {
                isListening = false;
                micBtn.style.background = 'linear-gradient(135deg, #1F4E78 0%, #2563EB 100%)';
                micIcon.innerText = '🎙️';
                micText.innerText = 'Nói câu hỏi (Tiếng Việt)';
            };

            recognition.start();
        }
    </script>
    """
    st.components.v1.html(voice_html, height=45)


def notify(message: str, detail: str = None, icon: str = "⚠️", toast_only: bool = False):
    """Hiển thị thông báo bằng toast góc màn hình và caption rõ ràng."""
    st.toast(message, icon=icon)
    if not toast_only:
        st.caption(f"{icon} {message}")
        if detail:
            with st.expander("Xem chi tiết kỹ thuật", expanded=False):
                st.code(detail)


def render_executive_kpi_cards(df: pd.DataFrame, is_en: bool = False, user_query: str = ""):
    """Hiển thị cụm thẻ tóm tắt chỉ số điều hành (Executive KPI Summary Cards) trên đầu kết quả.
    Tự động nhận diện cột trung bình/tỷ lệ để tránh lỗi cộng dồn (Sum of averages fallacy) và làm nổi bật đối tượng mục tiêu.
    """
    import re
    if df is None or df.empty:
        return

    measure_cols, label_cols, _ = get_axis_columns(df)
    if not measure_cols:
        measure_cols = [
            c for c in df.columns
            if pd.api.types.is_numeric_dtype(df[c]) and not is_id_like(c)
            and not (any(k in str(c).lower() for k in ["year", "hireyear", "nam"]) and not any(k in str(c).lower() for k in ["service", "thâm_niên"]))
        ]
        label_cols = [c for c in df.columns if c not in measure_cols]

    total_rows = len(df)

    if measure_cols and total_rows > 1:
        # Ưu tiên cột đo lường tuyệt đối (Count/Amount/Salary/YearsOfService) hơn cột % khi hiển thị trên thẻ KPI
        count_like_cols = [c for c in measure_cols if not any(k in str(c).lower() for k in ["percent", "percentage", "pct", "tỷ lệ", "phan_tram", "rate", "ratio"])]
        # Ưu tiên cột tổng thể (Total/Tổng/All) nếu có
        total_like_cols = [c for c in count_like_cols if any(k in str(c).lower() for k in ["total", "tổng", "count_all", "all"])]
        m_col = total_like_cols[0] if total_like_cols else (count_like_cols[0] if count_like_cols else measure_cols[0])
        
        # Tách camelCase và chuẩn hóa tên chỉ số hiển thị chuyên nghiệp
        raw_m = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(m_col)).replace("_", " ").strip()
        m_low = raw_m.lower()
        if not is_en:
            if any(k in m_low for k in ["current salary", "currentsalary", "lương mới nhất", "lương hiện tại"]):
                m_clean = "Lương Hiện Tại"
            elif any(k in m_low for k in ["avg salary", "avgsalary"]):
                m_clean = "Lương Trung Bình"
            elif "salary" in m_low or "lương" in m_low:
                m_clean = "Mức Lương"
            elif any(k in m_low for k in ["headcount", "totalemployees", "số lượng nhân sự"]):
                m_clean = "Quy Mô Nhân Sự"
            elif any(k in m_low for k in ["totalsalarybudget", "salarybudget", "quỹ lương"]):
                m_clean = "Quỹ Lương"
            elif any(k in m_low for k in ["yearsofservice", "years of service", "thâm niên"]):
                m_clean = "Thâm Niên"
            elif "raisecount" in m_low:
                m_clean = "Số Lần Tăng Lương"
            else:
                m_clean = raw_m.title()
        else:
            m_clean = raw_m.title()

        # Kiểm tra truy vấn xếp hạng Top N
        is_top_query = any(k in (user_query or "").lower() for k in ["top", "danh sách", "hàng đầu", "cao nhất", "thấp nhất"])
        scope_suffix = f" (Top {total_rows})" if is_top_query and total_rows <= 30 else ""

        # Ký hiệu tiền tệ
        is_currency = any(k in str(m_col).lower() for k in ["salary", "lương", "budget", "quỹ", "tiền", "cost", "revenue", "chi phí", "thu nhập"])
        curr_symbol = "$" if is_currency else ""

        valid_vals = pd.to_numeric(df[m_col], errors="coerce").dropna()
        if not valid_vals.empty:
            avg_val = valid_vals.mean()
            max_idx = valid_vals.idxmax()
            min_idx = valid_vals.idxmin()
            peak_val = df.loc[max_idx, m_col]
            min_val = df.loc[min_idx, m_col]

            # Lấy nhãn đối tượng đầy đủ
            _, label_series, _ = pick_label_column(df, label_cols)
            if label_series is not None and max_idx in label_series.index:
                peak_label = str(label_series.loc[max_idx])
            elif label_cols:
                peak_label = str(df.loc[max_idx, label_cols[0]])
            else:
                peak_label = f"#{max_idx + 1}"

            if label_series is not None and min_idx in label_series.index:
                min_label = str(label_series.loc[min_idx])
            elif label_cols:
                min_label = str(df.loc[min_idx, label_cols[0]])
            else:
                min_label = f"#{min_idx + 1}"

            def _fmt_kpi_val(v):
                try:
                    fv = float(v)
                    if fv.is_integer() or fv > 100:
                        return f"{curr_symbol}{fv:,.0f}"
                    return f"{curr_symbol}{fv:,.2f}"
                except Exception:
                    return str(v)

            fmt_avg = _fmt_kpi_val(avg_val)
            fmt_peak = _fmt_kpi_val(peak_val)
            fmt_min = _fmt_kpi_val(min_val)

            # Kiểm tra xem m_col có phải là giá trị trung bình/tỷ lệ/min/max không (để tránh lỗi cộng dồn thống kê)
            is_avg_or_rate = any(k in m_col.lower() for k in [
                "avg", "average", "mean", "trung_bình", "rate", "ratio", "pct", "percent", "tỷ_lệ", "max", "min"
            ])

            # Kiểm tra xem người dùng có hỏi về một đối tượng cụ thể (ví dụ Customer Service) không
            target_idx = None
            target_name = None
            if user_query and label_series is not None:
                uq_low = user_query.lower()
                for idx, lbl in label_series.items():
                    lbl_str = str(lbl).strip()
                    if len(lbl_str) >= 3 and lbl_str.lower() in uq_low:
                        target_idx = idx
                        target_name = lbl_str
                        break

            col1, col2, col3, col4 = st.columns(4)

            if is_avg_or_rate:
                # CỘT TRUNG BÌNH/TỶ LỆ: Hiển thị Thống kê tổng hợp khoa học, KHÔNG cộng dồn!
                with col1:
                    st.metric("📋 " + ("Số đối tượng so sánh" if not is_en else "Comparing Entities"), f"{total_rows:,}")
                with col2:
                    st.metric(f"📈 " + ("Mức trung bình chuẩn" if not is_en else "Benchmark Average"), fmt_avg)
                with col3:
                    st.metric(f"🏆 " + ("Dẫn đầu (Cao nhất)" if not is_en else "Highest"), peak_label, delta=f"{fmt_peak}")
                with col4:
                    if target_idx is not None and target_idx in valid_vals.index:
                        t_val = df.loc[target_idx, m_col]
                        fmt_t_val = _fmt_kpi_val(t_val)
                        rank = int((valid_vals > t_val).sum()) + 1
                        st.metric(f"🎯 {target_name}", fmt_t_val, delta=f"Hạng {rank}/{total_rows}")
                    else:
                        st.metric(f"📉 " + ("Thấp nhất" if not is_en else "Lowest"), min_label, delta=f"{fmt_min}")
            else:
                # CỘT SỐ LƯỢNG/TỔNG QUỸ/TIỀN TỆ TUYỆT ĐỐI: Hiển thị Tổng cộng
                total_val = valid_vals.sum()
                fmt_total = _fmt_kpi_val(total_val)
                with col1:
                    if is_top_query and total_rows <= 30:
                        st.metric("🏆 " + ("Quy mô Top" if not is_en else "Top Size"), f"Top {total_rows}")
                    else:
                        st.metric("📋 " + ("Tổng số dòng" if not is_en else "Total Rows"), f"{total_rows:,}")
                with col2:
                    st.metric(f"💰 " + ("Tổng " if not is_en else "Total ") + m_clean + scope_suffix, fmt_total)
                with col3:
                    st.metric(f"📈 " + ("Trung bình" if not is_en else "Average"), fmt_avg)
                with col4:
                    st.metric(f"🏆 " + ("Đỉnh cao nhất" if not is_en else "Peak Record"), peak_label, delta=f"{fmt_peak}")
            st.write("")

    elif total_rows == 1 and measure_cols:
        m_col = measure_cols[0]
        m_clean = str(m_col).replace("_", " ").title()
        val = df[m_col].iloc[0]
        fmt_val = f"{val:,.0f}" if isinstance(val, (int, float)) and val > 100 else f"{val:,.2f}"
        col1, col2 = st.columns(2)
        with col1:
            st.metric("📋 " + ("Số lượng bản ghi" if not is_en else "Record Count"), "1")
        with col2:
            st.metric("🎯 " + m_clean, fmt_val)
        st.write("")


def render_insight_cards(insights_raw: str, df: pd.DataFrame = None, is_en: bool = False):
    """Render 3 Thẻ Giao Diện Độc Lập (Cards) cho Insight: Bất thường, Nguyên nhân, Đề xuất chiến lược phân cấp 3 bậc."""
    if not insights_raw and (df is None or df.empty):
        return

    sections = split_insight_sections(insights_raw or "", df=df)
    p21 = sections.get("anomaly", "").strip()
    p22 = sections.get("hypothesis", "").strip()
    p23 = sections.get("action_plan", "").strip()

    st.markdown("---")
    st.markdown("#### 🤖 Strategic Insights & Executive Action Plan:" if is_en else "#### 🤖 Nhận định & Đề xuất Chiến lược từ AI:")

    # Card 1: Phát hiện bất thường & Xu hướng
    if p21:
        with st.container(border=True):
            title_21 = "🚨 1. Key Discoveries & Trend Anomalies" if is_en else "🚨 1. Phát hiện Bất thường & Xu hướng Chính"
            st.markdown(f"<h4 style='color: #B23C00; margin: 2px 0 10px 0; font-size: 1.12rem; font-weight: 800;'>{title_21}</h4>", unsafe_allow_html=True)
            st.markdown(p21)

    # Card 2: Giả thuyết & Nguyên nhân
    if p22:
        with st.container(border=True):
            title_22 = "🔍 2. Potential Root Causes & Hypotheses" if is_en else "🔍 2. Giả thuyết & Nguyên nhân Tiềm năng"
            st.markdown(f"<h4 style='color: #01579B; margin: 2px 0 10px 0; font-size: 1.12rem; font-weight: 800;'>{title_22}</h4>", unsafe_allow_html=True)
            st.markdown(p22)

    # Card 3: Đề xuất chiến lược phân cấp (Cấp bách | Trung hạn | Dài hạn)
    if not p23 and df is not None and not df.empty:
        from src.analytics.heuristics import generate_data_grounded_action_plan
        p23 = generate_data_grounded_action_plan(df, is_en=is_en)

    if p23:
        with st.container(border=True):
            title_23 = "🎯 3. Executive Strategic Recommendations (Urgent | Medium | Long-term)" if is_en else "🎯 3. Đề xuất Chiến lược Phân cấp (Cấp bách | Trung hạn | Dài hạn)"
            st.markdown(f"<h4 style='color: #1B5E20; margin: 2px 0 10px 0; font-size: 1.12rem; font-weight: 800;'>{title_23}</h4>", unsafe_allow_html=True)
            st.markdown(p23)


def render_result(result: dict, turn_id: str):
    """Hiển thị kết quả truy vấn sạch sẽ (Silent Fix) với thẻ KPI, bảng, biểu đồ, insight, dự báo và bộ xuất báo cáo đa định dạng."""
    lang = result.get("lang", "vi")
    is_en = (lang == "en")

    # 1. Hiển thị giải thích tự nhiên từ AI nếu câu hỏi nằm ngoài phạm vi Schema
    if result.get("explanation"):
        title_exp = "💡 **Notice from AI Assistant:**" if is_en else "💡 **Thông báo từ Trợ lý AI:**"
        st.info(f"{title_exp}\n\n{result['explanation']}")
        return

    # 2. Hiển thị lỗi nếu có kèm Khung Sao chép Lỗi 1-Click (Copy to Clipboard)
    if result.get("error"):
        err_msg = result['error']
        st.error(f"❌ {err_msg}")

        # Nút hành động nhanh khi hết số dư / quota
        if any(k in err_msg.lower() for k in ["hết số dư", "quota", "402", "429", "api key"]):
            c_e1, c_e2 = st.columns([1.5, 1.5])
            with c_e1:
                if st.button("⚙️ Mở Cài Đặt (Đổi sang Gemini Miễn Phí / Cập nhật Key)", key=f"btn_err_settings_{turn_id}", type="primary", use_container_width=True):
                    st.session_state["view_mode"] = "settings"
                    st.rerun()
            with c_e2:
                if "openrouter" in err_msg.lower():
                    st.link_button("💳 Nạp thêm credit OpenRouter ($5)", "https://openrouter.ai/settings/credits", use_container_width=True)

        # Chuẩn bị văn bản báo lỗi chuẩn chỉnh để 1-click copy
        logs = result.get("logs", [])
        logs_str = "\n".join(f"  • {l}" for l in logs) if logs else "  • Không có nhật ký thử lại."
        debug_copy_text = (
            f"=== THÔNG TIN LỖI TRUY VẤN VERAXUS FOR SQL ===\n"
            f"• Câu hỏi gốc: {result.get('query', '')}\n"
            f"• Thông báo lỗi: {result.get('error', '')}\n\n"
            f"• Câu lệnh SQL / Phản hồi cuối cùng:\n{result.get('sql', 'N/A')}\n\n"
            f"• Nhật ký các lần tự sửa lỗi:\n{logs_str}\n"
            f"================================================"
        )

        caption_copy = "📋 **Copy full error log** *(Hover and click 📋 Copy icon at top right)*:" if is_en else "📋 **Sao chép toàn bộ thông tin lỗi** *(Di chuột vào khung bên dưới và bấm biểu tượng 📋 Copy ở góc trên bên phải)*:"
        st.caption(caption_copy)
        st.code(debug_copy_text, language="markdown")

        expander_title = "🛠️ Technical Details & Debug Logs" if is_en else "🛠️ Chi tiết Kỹ thuật & Lịch sử lỗi (Debug Logs)"
        with st.expander(expander_title, expanded=False):
            if result.get("sql"):
                st.markdown("**Final SQL Query:**" if is_en else "**Câu lệnh SQL cuối cùng:**")
                st.code(result["sql"], language="sql")
            st.markdown("**Execution Logs:**" if is_en else "**Nhật ký các lần thử:**")
            for log in logs:
                st.text(f"• {log}")
        return

    df = result.get("df")
    sql_query = result.get("sql")

    if df is None or df.empty:
        st.warning("⚠️ No data returned for this query." if is_en else "⚠️ Không có dữ liệu nào trả về cho câu hỏi này.")
        if sql_query:
            with st.expander("🛠️ SQL Query Details" if is_en else "🛠️ Chi tiết Câu lệnh SQL", expanded=False):
                st.code(sql_query, language="sql")
        return

    # Tự động thay thế các ô chuỗi rỗng / khoảng trắng / NaN trong cột text bằng nhãn rõ ràng
    cleaned_df = df.copy()
    for col in cleaned_df.columns:
        if not pd.api.types.is_numeric_dtype(cleaned_df[col]):
            unassigned_label = "(Unassigned)" if is_en else "(Chưa phân nhóm)"
            cleaned_df[col] = cleaned_df[col].apply(
                lambda val: unassigned_label if pd.isna(val) or (isinstance(val, str) and not val.strip()) else val
            )
    df = cleaned_df
    # 3. Thẻ Tóm tắt Chỉ số Điều hành (Executive KPI Summary Cards)
    user_query = result.get("query", "")
    render_executive_kpi_cards(df, is_en=is_en, user_query=user_query)

    # 4. Hiển thị Bảng dữ liệu & Cụm Nút Xuất Báo Cáo Đa Định Dạng (CSV, Excel, PDF)
    display_df = df.copy()

    # Tự động gắn nhãn huy chương cho bảng xếp hạng Top N
    is_ranking = any(k in (user_query or "").lower() for k in ["top", "cao nhất", "thấp nhất", "xếp hạng", "danh sách", "lâu nhất", "nhiều nhất"])
    if is_ranking and len(display_df) <= 50:
        medals = {0: "🥇 #1", 1: "🥈 #2", 2: "🥉 #3"}
        display_df.index = [medals.get(i, f"#{i+1}") for i in range(len(display_df))]
        display_df.index.name = "Xếp hạng" if not is_en else "Rank"

    column_config = {}
    for col in display_df.columns:
        c_low = str(col).lower()
        if is_id_like(col):
            column_config[col] = st.column_config.NumberColumn(col, format="%d")
        elif any(k in c_low for k in ["salary", "lương", "thu nhập", "budget", "quỹ", "tiền", "cost", "revenue", "chi phí"]):
            # Format tiền tệ thông minh: hiển thị $%,d nếu số nguyên, $%,.2f nếu có số lẻ
            has_decimals = False
            try:
                numeric_vals = pd.to_numeric(display_df[col], errors="coerce").dropna()
                has_decimals = any(not float(v).is_integer() for v in numeric_vals)
            except Exception:
                pass
            column_config[col] = st.column_config.NumberColumn(
                col,
                format="$%,.2f" if has_decimals else "$%,d"
            )
        elif any(k in c_low for k in ["pct", "percent", "tỷ lệ", "rate", "ratio"]):
            column_config[col] = st.column_config.NumberColumn(
                col,
                format="%.2f%%"
            )
        elif any(k in c_low for k in ["headcount", "hires", "raise", "count", "số lượng", "tổng số"]):
            column_config[col] = st.column_config.NumberColumn(
                col,
                format="%,d"
            )

    st.dataframe(display_df, column_config=column_config, width='stretch')

    c_csv, c_excel, c_pdf, _ = st.columns([2, 2.5, 2.5, 3])
    with c_csv:
        st.download_button(
            "⬇️ Tải CSV" if not is_en else "⬇️ Download CSV",
            df.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"result_{turn_id}.csv",
            mime="text/csv",
            key=f"csv_{turn_id}",
            use_container_width=True
        )

    with c_excel:
        excel_bytes = export_to_excel(df, sheet_name=result.get("query", "Data"))
        st.download_button(
            "📊 Xuất Excel (.xlsx)" if not is_en else "📊 Export Excel (.xlsx)",
            excel_bytes,
            file_name=f"report_{turn_id}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"excel_{turn_id}",
            use_container_width=True
        )

    with c_pdf:
        pdf_bytes = export_to_pdf(result, df)
        st.download_button(
            "📄 Xuất Báo cáo PDF" if not is_en else "📄 Export PDF Report",
            pdf_bytes,
            file_name=f"executive_report_{turn_id}.pdf",
            mime="application/pdf",
            key=f"pdf_{turn_id}",
            use_container_width=True
        )

    # 4.1 Khung Gửi Báo Cáo Đa Kênh Tức Thì (Telegram Bot & Email SMTP)
    exp_share_title = "📤 Gửi Báo Cáo cho Sếp / Đội ngũ (Telegram & Email)" if not is_en else "📤 Share Report (Telegram Bot & Email)"
    with st.expander(exp_share_title, expanded=False):
        saved = load_saved_config()
        tab_tg, tab_em = st.tabs(["🚀 Gửi qua Telegram Bot", "📧 Gửi qua Email SMTP"])

        with tab_tg:
            st.caption("Gửi trực tiếp file Báo cáo PDF Executive kèm tóm tắt Insight vào nhóm Telegram.")
            tg_token = st.text_input(
                "Telegram Bot Token",
                value=st.session_state.get("telegram_bot_token") or saved.get("telegram_bot_token", ""),
                type="password",
                placeholder="123456789:ABCdef...",
                key=f"tg_tok_{turn_id}"
            )
            tg_chat_id = st.text_input(
                "Telegram Chat ID / Group ID",
                value=st.session_state.get("telegram_chat_id") or saved.get("telegram_chat_id", ""),
                placeholder="-100123456789 hoặc @channel_name",
                key=f"tg_chat_{turn_id}"
            )

            if st.button("🚀 Gửi Báo Cáo vào Telegram", key=f"btn_send_tg_{turn_id}", type="primary", use_container_width=True):
                if not tg_token or not tg_chat_id:
                    st.error("Vui lòng nhập Bot Token và Chat ID (hoặc cấu hình trong ⚙️ Cài đặt).")
                else:
                    with st.spinner("Đang gửi file báo cáo PDF vào Telegram..."):
                        insight_summary = result.get("insights", "") or result.get("query", "")
                        clean_cap = re.sub(r"#+\s*", "", insight_summary)
                        clean_cap = clean_cap.replace("###", "").replace("**", "").replace("`", "")[:900]
                        ok, msg = send_telegram_report(
                            tg_token, tg_chat_id, clean_cap, pdf_bytes, filename=f"executive_report_{turn_id}.pdf"
                        )
                        if ok:
                            st.success(f"✅ {msg}")
                            st.toast(f"✅ {msg}", icon="🚀")
                        else:
                            st.error(f"❌ {msg}")

        with tab_em:
            st.caption("Gửi email đính kèm file Báo cáo PDF cho ban giám đốc hoặc danh sách người nhận.")
            em_receivers = st.text_input(
                "Email Người nhận (cách nhau bằng dấu phẩy)",
                value=st.session_state.get("email_receivers") or saved.get("email_receivers", ""),
                placeholder="boss@company.com, leads@company.com",
                key=f"em_rec_{turn_id}"
            )
            em_subject = st.text_input(
                "Tiêu đề Email",
                value=f"Báo cáo Điều hành: {result.get('query', 'Tổng quan Doanh nghiệp')}",
                key=f"em_sub_{turn_id}"
            )

            if st.button("📧 Gửi Báo Cáo qua Email", key=f"btn_send_em_{turn_id}", type="primary", use_container_width=True):
                smtp_server = st.session_state.get("smtp_server") or saved.get("smtp_server", "smtp.gmail.com")
                smtp_port = st.session_state.get("smtp_port") or saved.get("smtp_port", "587")
                smtp_user = st.session_state.get("smtp_user") or saved.get("smtp_user", "")
                smtp_pass = st.session_state.get("smtp_pass") or saved.get("smtp_pass", "")

                if not smtp_user or not smtp_pass:
                    st.error("Chưa cấu hình Email người gửi và Mật khẩu ứng dụng trong mục ⚙️ Cài đặt.")
                elif not em_receivers:
                    st.error("Vui lòng nhập email người nhận.")
                else:
                    with st.spinner("Đang gửi email đính kèm báo cáo..."):
                        insight_summary = result.get("insights", "") or result.get("query", "")
                        ok, msg = send_email_report(
                            smtp_server, smtp_port, smtp_user, smtp_pass,
                            em_receivers, em_subject, insight_summary, pdf_bytes,
                            filename=f"executive_report_{turn_id}.pdf"
                        )
                        if ok:
                            st.success(f"✅ {msg}")
                            st.toast(f"✅ {msg}", icon="📧")
                        else:
                            st.error(f"❌ {msg}")

    # 4. Tabs: Biểu đồ, Insight & Bất thường, Dự báo
    anomalies_info = result.get("anomalies_info") or analyze_data_anomalies(df)
    has_anomaly = anomalies_info.get("has_anomaly", False)

    if is_en:
        tab_insight_label = "💡 Insights & Anomalies 🚨" if has_anomaly else "💡 Insights & Analysis"
        tab_chart_label = "📊 Chart"
        tab_forecast_label = "🔮 Forecast"
    else:
        tab_insight_label = "💡 Insight & Bất thường 🚨" if has_anomaly else "💡 Insight & Phân tích"
        tab_chart_label = "📊 Biểu đồ"
        tab_forecast_label = "🔮 Dự báo"

    tab1, tab2, tab3 = st.tabs([tab_chart_label, tab_insight_label, tab_forecast_label])

    with tab1:
        chart_options = (
            ["Automatic", "Bar (Vertical)", "Bar (Horizontal Ranking)", "Line", "Pie", "Area", "Scatter"]
            if is_en else
            ["Tự động", "Bar (Cột đứng)", "Bar (Cột ngang xếp hạng)", "Line (Đường)", "Pie (Tròn)", "Area (Miền)", "Scatter (Phân tán)"]
        )
        chart_override_label = "Chart Type" if is_en else "Loại biểu đồ"
        chart_override = st.selectbox(
            chart_override_label,
            chart_options,
            key=f"charttype_{turn_id}"
        )
        if "ngang" in chart_override.lower() or "horizontal" in chart_override.lower():
            norm_override = "Bar Ngang"
        elif "Bar" in chart_override:
            norm_override = "Bar"
        elif "Line" in chart_override:
            norm_override = "Line"
        elif "Pie" in chart_override:
            norm_override = "Pie"
        elif "Area" in chart_override:
            norm_override = "Area"
        elif "Scatter" in chart_override:
            norm_override = "Scatter"
        else:
            norm_override = "Tự động"

        chart_fig = render_smart_chart(df, norm_override, turn_id, user_query=user_query)

        if chart_fig:
            st.caption("💡 **Mẹo:** Rê chuột vào góc trên bên phải biểu đồ và bấm biểu tượng máy ảnh 📷 để tải ngay ảnh PNG độ nét cao (HD)." if not is_en else "💡 **Tip:** Hover over the top-right of the chart and click the camera icon 📷 to download HD PNG image instantly.")

        if has_anomaly:
            n_findings = len(anomalies_info.get("findings", []))
            caption_anom = f"🚨 **Detected {n_findings} statistical anomalies/trends**. See detailed report in **'{tab_insight_label}'** tab." if is_en else f"🚨 **Phát hiện {n_findings} điểm/xu hướng bất thường** trên dữ liệu. Xem phân tích chi tiết tại tab **'{tab_insight_label}'**."
            st.caption(caption_anom)

    with tab2:
        title_insight_header = "💡 Executive Business Insight & Anomaly Report" if is_en else "💡 Báo cáo Phân tích Insight & Phát hiện Bất thường"
        st.subheader(title_insight_header)

        # Thống kê nhanh
        stats = anomalies_info.get("summary_stats", {})
        if stats:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total Rows" if is_en else "Tổng số dòng", f"{stats.get('count', 0):,}")
            c2.metric("Mean" if is_en else "Trung bình (Mean)", f"{stats.get('mean', 0):,.2f}")
            c3.metric("Max" if is_en else "Lớn nhất (Max)", f"{stats.get('max', 0):,.2f}")
            c4.metric("Min" if is_en else "Nhỏ nhất (Min)", f"{stats.get('min', 0):,.2f}")

        # Danh sách điểm bất thường phát hiện theo thuật toán
        if has_anomaly:
            st.markdown("#### 🚨 Statistical Anomaly Findings:" if is_en else "#### 🚨 Các phát hiện bất thường từ thuật toán:")
            for f in anomalies_info.get("findings", []):
                st.warning(f"• {f.get('message')}")
        else:
            st.success("✅ No extreme anomalies or spikes detected in this dataset." if is_en else "✅ Thuật toán không phát hiện điểm đột biến hoặc biến động cực đoan bất thường trong tập dữ liệu này.")

        # Báo cáo phân tích chuyên sâu từ AI với Priority Tagging dạng 3 Cards
        insights = result.get("insights", "")
        if insights:
            render_insight_cards(insights, df=df, is_en=is_en)
        else:
            btn_insight_text = "🔍 Generate Executive Insights & Priority Action Plan" if is_en else "🔍 Yêu cầu AI phân tích Insight & Đề xuất hành động"
            if st.button(btn_insight_text, key=f"gen_insight_{turn_id}"):
                client = st.session_state.get("client")
                provider = st.session_state.get("provider")
                model_name = st.session_state.get("model_name")
                with st.spinner("Analyzing data and generating executive insights..." if is_en else "AI đang tổng hợp và phân tích dữ liệu chuyên sâu..."):
                    generated = generate_auto_insights(
                        client, provider, model_name, result["query"], df, anomalies_info, lang=lang
                    )
                    if generated:
                        clean_gen = sanitize_insight_markdown(generated)
                        result["insights"] = clean_gen
                        render_insight_cards(clean_gen, df=df, is_en=is_en)

    with tab3:
        caption_forecast = (
            "🧮 Forecast uses deterministic linear regression — mathematically verifiable. Available when dataset contains time and numerical measure columns."
            if is_en else
            "🧮 Dự báo dùng thuật toán hồi quy tuyến tính xác định (deterministic) — không phải AI 'đoán' số. "
            "Lựa chọn này đảm bảo kết quả nhất quán, có thể kiểm chứng bằng toán học. "
            "Dự báo chỉ khả dụng khi kết quả có cột thời gian và chỉ số đo lường số học."
        )
        st.caption(caption_forecast)
        periods = st.session_state.get("forecast_periods", 3)
        fig, method = forecast_series(df, periods=periods)
        if fig is None:
            st.info(method)
        else:
            st.plotly_chart(fig, width='stretch', key=f"forecast_{turn_id}")
            st.caption(f"Method: {method}" if is_en else f"Phương pháp: {method}")

    # 5. Gợi ý Câu hỏi Phân tích Tiếp nối (Follow-up Question Suggestions)
    followups = result.get("followups", [])
    if followups:
        st.markdown("---")
        header_fup = "##### 💡 Suggested Follow-up Questions (Click to run):" if is_en else "##### 💡 Gợi ý câu hỏi phân tích tiếp nối (Nhấp để chạy ngay):"
        st.markdown(header_fup)
        cols = st.columns(len(followups))
        for col_f, q_text in zip(cols, followups):
            clean_q = sanitize_followup_question(q_text)
            def _on_fup_click(q_target=clean_q):
                st.session_state["pending_prompt"] = q_target

            with col_f:
                help_text = f"Run query: {clean_q}" if is_en else f"Chạy tiếp câu hỏi: {clean_q}"
                st.button(
                    f"👉 {clean_q}",
                    key=f"btn_fup_{turn_id}_{abs(hash(clean_q))}",
                    use_container_width=True,
                    help=help_text,
                    on_click=_on_fup_click
                )

    # 6. Chi tiết Kỹ thuật & SQL Playground (Expander thu gọn ở cuối cùng)
    exp_tech = "🛠️ Technical Details & SQL Query Playground" if is_en else "🛠️ Chi tiết Kỹ thuật & SQL Playground (Sửa & Chạy trực tiếp)"
    with st.expander(exp_tech, expanded=False):
        if sql_query:
            st.markdown("#### ⚡ " + ("Chỉnh sửa & Chạy lại SQL Trực tiếp" if not is_en else "Live SQL Editor & Playground"))
            st.caption(
                "Bạn có thể sửa câu lệnh SQL (đổi điều kiện WHERE, GROUP BY, ORDER BY, LIMIT...) và bấm nút bên dưới để cập nhật kết quả tức thì mà không cần gọi lại AI."
                if not is_en else
                "You can edit the SQL query below and re-run it directly to update results instantly without calling AI."
            )
            edited_sql = st.text_area(
                "SQL Editor",
                value=sql_query,
                height=130,
                key=f"sql_edit_area_{turn_id}",
                label_visibility="collapsed"
            )

            btn_rerun_label = "⚡ Chạy lại câu lệnh SQL này" if not is_en else "⚡ Re-run Edited SQL"
            if st.button(btn_rerun_label, key=f"btn_rerun_{turn_id}", type="primary"):
                engine = st.session_state.get("engine")
                if not engine:
                    st.error("Chưa kết nối database để chạy câu lệnh SQL." if not is_en else "Database engine is not connected.")
                else:
                    from src.database.query_runner import read_sql_capped
                    from src.config import MAX_ROWS_CAP
                    try:
                        new_df, truncated = read_sql_capped(edited_sql, engine, cap=MAX_ROWS_CAP)
                        if new_df is not None:
                            result["sql"] = edited_sql
                            result["df"] = new_df
                            result["logs"].append(f"[SQL Playground] Updated with user-edited SQL.")
                            st.toast("⚡ Đã cập nhật kết quả với câu lệnh SQL mới!", icon="⚡")
                            st.rerun()
                    except Exception as e:
                        st.error(f"❌ Lỗi thực thi SQL: {e}")

            st.markdown("---")

        attempts = result.get("attempts", 1)
        if attempts > 1:
            msg_healing = f"ℹ️ AI Agent auto-corrected and finalized query after **{attempts} attempts in the background (Silent Self-Healing)**." if is_en else f"ℹ️ AI Agent đã tự động sửa lỗi và hoàn thiện câu lệnh sau **{attempts} lần thử trong nền (Silent Self-Healing)**."
            st.info(msg_healing)

        logs = result.get("logs", [])
        if logs:
            st.markdown("**Execution Logs:**" if is_en else "**Nhật ký các bước thực thi:**")
            for log in logs:
                st.text(f"• {log}")
