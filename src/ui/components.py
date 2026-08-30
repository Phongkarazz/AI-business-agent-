"""
Reusable UI components for rendering query results, charts, forecasts, automated insights,
follow-up question suggestions, and notifications.
Features clean Silent Fix interface, Priority Tagging display, Bilingual English/Vietnamese support,
1-Click Copy Error button, and conversational AI explanation handling.
"""

import streamlit as st
from src.analytics.heuristics import get_axis_columns
from src.analytics.anomaly import analyze_data_anomalies
from src.analytics.forecasting import forecast_series
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


def render_result(result: dict, turn_id: str):
    """Hiển thị kết quả truy vấn sạch sẽ (Silent Fix) với bảng, biểu đồ, insight, dự báo và câu hỏi tiếp nối song ngữ."""
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

    # 3. Hiển thị Bảng dữ liệu & Nút Tải CSV
    st.dataframe(df, width='stretch')
    c_csv, _ = st.columns([2, 5])
    with c_csv:
        st.download_button(
            "⬇️ Download CSV" if is_en else "⬇️ Tải file CSV",
            df.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"result_{turn_id}.csv",
            mime="text/csv",
            key=f"csv_{turn_id}"
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
        render_smart_chart(df, norm_override, turn_id)

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
        insights = result.get("insights")
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
                        result["insights"] = generated
                        st.markdown("---")
                        st.markdown("#### 🤖 Strategic Insights & Executive Action Plan:" if is_en else "#### 🤖 Nhận định & Đề xuất Chiến lược từ AI:")
                        st.markdown(generated)

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

    # 6. Chi tiết Kỹ thuật & SQL (Expander thu gọn ở cuối cùng)
    exp_tech = "🛠️ Technical Details & SQL Query (Debug)" if is_en else "🛠️ Chi tiết Kỹ thuật & Câu lệnh SQL (Debug)"
    with st.expander(exp_tech, expanded=False):
        if sql_query:
            st.markdown("**Executed SQL Query:**" if is_en else "**Câu lệnh SQL đã thực thi:**")
            st.code(sql_query, language="sql")

        attempts = result.get("attempts", 1)
        if attempts > 1:
            msg_healing = f"ℹ️ AI Agent auto-corrected and finalized query after **{attempts} attempts in the background (Silent Self-Healing)**." if is_en else f"ℹ️ AI Agent đã tự động sửa lỗi và hoàn thiện câu lệnh sau **{attempts} lần thử trong nền (Silent Self-Healing)**."
            st.info(msg_healing)

        logs = result.get("logs", [])
        if logs:
            st.markdown("**Execution Logs:**" if is_en else "**Nhật ký các bước thực thi:**")
            for log in logs:
                st.text(f"• {log}")
