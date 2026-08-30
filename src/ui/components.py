"""
Reusable UI components for rendering query results, charts, forecasts, automated insights,
follow-up question suggestions, and notifications.
Features clean Silent Fix interface, 1-Click Copy Error button, and conversational AI explanation handling.
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
    """Hiển thị kết quả truy vấn sạch sẽ (Silent Fix) với bảng, biểu đồ, insight, dự báo và câu hỏi tiếp nối."""
    # 1. Hiển thị giải thích tự nhiên từ AI nếu câu hỏi nằm ngoài phạm vi Schema
    if result.get("explanation"):
        st.info(f"💡 **Thông báo từ Trợ lý AI:**\n\n{result['explanation']}")
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

        st.caption("📋 **Sao chép toàn bộ thông tin lỗi** *(Di chuột vào khung bên dưới và bấm biểu tượng 📋 Copy ở góc trên bên phải)*:")
        st.code(debug_copy_text, language="markdown")

        with st.expander("🛠️ Chi tiết Kỹ thuật & Lịch sử lỗi (Debug Logs)", expanded=False):
            if result.get("sql"):
                st.markdown("**Câu lệnh SQL cuối cùng:**")
                st.code(result["sql"], language="sql")
            st.markdown("**Nhật ký các lần thử:**")
            for log in logs:
                st.text(f"• {log}")
        return

    df = result.get("df")
    sql_query = result.get("sql")

    if df is None or df.empty:
        st.warning("⚠️ Không có dữ liệu nào trả về cho câu hỏi này.")
        if sql_query:
            with st.expander("🛠️ Chi tiết Câu lệnh SQL", expanded=False):
                st.code(sql_query, language="sql")
        return

    # 3. Hiển thị Bảng dữ liệu & Nút Tải CSV
    st.dataframe(df, width='stretch')
    c_csv, _ = st.columns([2, 5])
    with c_csv:
        st.download_button(
            "⬇️ Tải file CSV",
            df.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"ket_qua_{turn_id}.csv",
            mime="text/csv",
            key=f"csv_{turn_id}"
        )

    # 4. Tabs: Biểu đồ, Insight & Bất thường, Dự báo
    anomalies_info = result.get("anomalies_info") or analyze_data_anomalies(df)
    has_anomaly = anomalies_info.get("has_anomaly", False)

    tab_insight_label = "💡 Insight & Bất thường 🚨" if has_anomaly else "💡 Insight & Phân tích"
    tab1, tab2, tab3 = st.tabs(["📊 Biểu đồ", tab_insight_label, "🔮 Dự báo"])

    with tab1:
        chart_override = st.selectbox(
            "Loại biểu đồ",
            ["Tự động", "Line", "Bar", "Area", "Scatter"],
            key=f"charttype_{turn_id}"
        )
        render_smart_chart(df, chart_override, turn_id)

        if has_anomaly:
            n_findings = len(anomalies_info.get("findings", []))
            st.caption(f"🚨 **Phát hiện {n_findings} điểm/xu hướng bất thường** trên dữ liệu. Xem phân tích chi tiết tại tab **'{tab_insight_label}'**.")

    with tab2:
        st.subheader("💡 Báo cáo Phân tích Insight & Phát hiện Bất thường")

        # Thống kê nhanh
        stats = anomalies_info.get("summary_stats", {})
        if stats:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Tổng số dòng", f"{stats.get('count', 0):,}")
            c2.metric("Trung bình (Mean)", f"{stats.get('mean', 0):,.2f}")
            c3.metric("Lớn nhất (Max)", f"{stats.get('max', 0):,.2f}")
            c4.metric("Nhỏ nhất (Min)", f"{stats.get('min', 0):,.2f}")

        # Danh sách điểm bất thường phát hiện theo thuật toán
        if has_anomaly:
            st.markdown("#### 🚨 Các phát hiện bất thường từ thuật toán:")
            for f in anomalies_info.get("findings", []):
                st.warning(f"• {f.get('message')}")
        else:
            st.success("✅ Thuật toán không phát hiện điểm đột biến hoặc biến động cực đoan bất thường trong tập dữ liệu này.")

        # Báo cáo phân tích chuyên sâu từ AI
        insights = result.get("insights")
        if insights:
            st.markdown("---")
            st.markdown("#### 🤖 Nhận định & Đề xuất Chiến lược từ AI:")
            st.markdown(insights)
        else:
            if st.button("🔍 Yêu cầu AI phân tích Insight & Đề xuất hành động", key=f"gen_insight_{turn_id}"):
                client = st.session_state.get("client")
                provider = st.session_state.get("provider")
                model_name = st.session_state.get("model_name")
                with st.spinner("AI đang tổng hợp và phân tích dữ liệu chuyên sâu..."):
                    generated = generate_auto_insights(
                        client, provider, model_name, result["query"], df, anomalies_info
                    )
                    if generated:
                        result["insights"] = generated
                        st.markdown("---")
                        st.markdown("#### 🤖 Nhận định & Đề xuất Chiến lược từ AI:")
                        st.markdown(generated)

    with tab3:
        st.caption(
            "🧮 Dự báo dùng thuật toán hồi quy tuyến tính xác định (deterministic) — không phải AI 'đoán' số. "
            "Lựa chọn này đảm bảo kết quả nhất quán, có thể kiểm chứng bằng toán học. "
            "Dự báo chỉ khả dụng khi kết quả có cột thời gian và chỉ số đo lường số học."
        )
        periods = st.session_state.get("forecast_periods", 3)
        fig, method = forecast_series(df, periods=periods)
        if fig is None:
            st.info(method)
        else:
            st.plotly_chart(fig, width='stretch', key=f"forecast_{turn_id}")
            st.caption(f"Phương pháp: {method}")

    # 5. Gợi ý Câu hỏi Phân tích Tiếp nối (Follow-up Question Suggestions)
    followups = result.get("followups", [])
    if followups:
        st.markdown("---")
        st.markdown("##### 💡 Gợi ý câu hỏi phân tích tiếp nối (Nhấp để chạy ngay):")
        cols = st.columns(len(followups))
        for col_f, q_text in zip(cols, followups):
            with col_f:
                if st.button(f"👉 {q_text}", key=f"btn_fup_{turn_id}_{abs(hash(q_text))}", use_container_width=True, help=f"Chạy tiếp câu hỏi: {q_text}"):
                    st.session_state["pending_prompt"] = q_text
                    st.rerun()

    # 6. Chi tiết Kỹ thuật & SQL (Expander thu gọn ở cuối cùng)
    with st.expander("🛠️ Chi tiết Kỹ thuật & Câu lệnh SQL (Debug)", expanded=False):
        if sql_query:
            st.markdown("**Câu lệnh SQL đã thực thi:**")
            st.code(sql_query, language="sql")

        attempts = result.get("attempts", 1)
        if attempts > 1:
            st.info(f"ℹ️ AI Agent đã tự động sửa lỗi và hoàn thiện câu lệnh sau **{attempts} lần thử trong nền (Silent Self-Healing)**.")

        logs = result.get("logs", [])
        if logs:
            st.markdown("**Nhật ký các bước thực thi:**")
            for log in logs:
                st.text(f"• {log}")
