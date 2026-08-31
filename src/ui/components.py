"""
Reusable UI components for rendering query results, charts, forecasts, automated insights,
follow-up question suggestions, and multi-format reporting export (Excel, PNG, PDF).
Features clean Silent Fix interface, Priority Tagging display, Bilingual English/Vietnamese support,
1-Click Copy Error button, and conversational AI explanation handling.
"""

import streamlit as st
import pandas as pd
from src.analytics.heuristics import get_axis_columns, sanitize_insight_markdown
from src.analytics.anomaly import analyze_data_anomalies
from src.analytics.forecasting import forecast_series
from src.analytics.export_reports import export_to_excel, export_to_png, export_to_pdf
from src.visualization.charts import render_smart_chart
from src.llm.agent import generate_auto_insights


def notify(message: str, detail: str = None, icon: str = "⚠️", toast_only: bool = False):
    """Hiển thị thông báo bằng toast góc màn hình và caption rõ ràng."""
    st.toast(message, icon=icon)
    if not toast_only:
        st.caption(f"{icon} {message}")
        if detail:
            with st.expander("Xem chi tiết kỹ thuật", expanded=False):
                st.code(detail)


def render_executive_kpi_cards(df: pd.DataFrame, is_en: bool = False):
    """Hiển thị cụm thẻ tóm tắt chỉ số điều hành (Executive KPI Summary Cards) trên đầu kết quả."""
    if df is None or df.empty:
        return

    measure_cols, label_cols, _ = get_axis_columns(df)
    if not measure_cols:
        measure_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        label_cols = [c for c in df.columns if c not in measure_cols]

    total_rows = len(df)

    if measure_cols and total_rows > 1:
        m_col = measure_cols[0]
        m_clean = str(m_col).replace("_", " ").title()

        valid_vals = pd.to_numeric(df[m_col], errors="coerce").dropna()
        if not valid_vals.empty:
            total_val = valid_vals.sum()
            avg_val = valid_vals.mean()
            max_idx = valid_vals.idxmax()
            peak_val = df.loc[max_idx, m_col]
            peak_label = str(df.loc[max_idx, label_cols[0]]) if label_cols else f"#{max_idx + 1}"

            fmt_total = f"{total_val:,.0f}" if isinstance(total_val, (int, float)) and total_val > 100 else f"{total_val:,.2f}"
            fmt_avg = f"{avg_val:,.0f}" if isinstance(avg_val, (int, float)) and avg_val > 100 else f"{avg_val:,.2f}"
            fmt_peak = f"{peak_val:,.0f}" if isinstance(peak_val, (int, float)) and peak_val > 100 else f"{peak_val:,.2f}"

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("📋 " + ("Tổng số dòng" if not is_en else "Total Rows"), f"{total_rows:,}")
            with col2:
                st.metric(f"💰 " + ("Tổng " if not is_en else "Total ") + m_clean, fmt_total)
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
        st.error(f"❌ {result['error']}")

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
    result["df"] = df

    # 3. Thẻ Tóm tắt Chỉ số Điều hành (Executive KPI Summary Cards)
    render_executive_kpi_cards(df, is_en=is_en)

    # 4. Hiển thị Bảng dữ liệu & Cụm Nút Xuất Báo Cáo Đa Định Dạng (CSV, Excel, PDF)
    st.dataframe(df, width='stretch')

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
        chart_options = ["Automatic", "Line", "Bar", "Area", "Scatter"] if is_en else ["Tự động", "Line", "Bar", "Area", "Scatter"]
        chart_override_label = "Chart Type" if is_en else "Loại biểu đồ"
        chart_override = st.selectbox(
            chart_override_label,
            chart_options,
            key=f"charttype_{turn_id}"
        )
        norm_override = "Tự động" if chart_override in ("Tự động", "Automatic") else chart_override
        chart_fig = render_smart_chart(df, norm_override, turn_id)

        # Nút Tải Ảnh Biểu Đồ PNG Độ Nét Cao
        if chart_fig:
            png_bytes = export_to_png(chart_fig)
            if png_bytes:
                c_png, _ = st.columns([3, 7])
                with c_png:
                    st.download_button(
                        "📸 Tải Ảnh Biểu đồ PNG (HD)" if not is_en else "📸 Download Chart PNG (HD)",
                        png_bytes,
                        file_name=f"chart_{turn_id}.png",
                        mime="image/png",
                        key=f"png_{turn_id}",
                        use_container_width=True
                    )

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

        # Báo cáo phân tích chuyên sâu từ AI với Priority Tagging
        insights = sanitize_insight_markdown(result.get("insights", ""))
        if insights:
            st.markdown("---")
            st.markdown("#### 🤖 Strategic Insights & Executive Action Plan:" if is_en else "#### 🤖 Nhận định & Đề xuất Chiến lược từ AI:")
            st.markdown(insights)
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
                        st.markdown("---")
                        st.markdown("#### 🤖 Strategic Insights & Executive Action Plan:" if is_en else "#### 🤖 Nhận định & Đề xuất Chiến lược từ AI:")
                        st.markdown(clean_gen)

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
            with col_f:
                help_text = f"Run query: {q_text}" if is_en else f"Chạy tiếp câu hỏi: {q_text}"
                if st.button(f"👉 {q_text}", key=f"btn_fup_{turn_id}_{abs(hash(q_text))}", use_container_width=True, help=help_text):
                    st.session_state["pending_prompt"] = q_text
                    st.rerun()

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
