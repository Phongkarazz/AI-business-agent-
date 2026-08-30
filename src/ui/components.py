"""
Reusable UI components for rendering query results, charts, forecasts, automated insights, and notifications.
"""

import streamlit as st
from src.config import LOG_INLINE_MAX_CHARS
from src.analytics.heuristics import get_axis_columns
from src.analytics.anomaly import detect_outliers, analyze_data_anomalies
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
    """Hiển thị kết quả truy vấn gồm Log, SQL, Bảng dữ liệu, Biểu đồ, Insight Bất thường và Dự báo."""
    # 1. Hiển thị Logs
    for line in result.get("logs", []):
        if line.startswith("⚠️ Cảnh báo tự động"):
            st.warning(line)
        elif len(line) > LOG_INLINE_MAX_CHARS:
            short = line[:LOG_INLINE_MAX_CHARS].rsplit(" ", 1)[0] + "..."
            st.caption(short)
            with st.expander("Xem đầy đủ", expanded=False):
                st.write(line)
        else:
            st.caption(line)

    # 2. Hiển thị lỗi nếu có
    if result.get("error"):
        st.error(result["error"])
        if result.get("sql"):
            st.code(result["sql"], language="sql")
        return

    df = result.get("df")
    sql_query = result.get("sql")
    if sql_query:
        st.code(sql_query, language="sql")

    if df is None or df.empty:
        st.warning("Không có dữ liệu trả về.")
        return

    # 3. Hiển thị DataFrame và nút Tải CSV
    st.dataframe(df, width='stretch')
    st.download_button(
        "⬇️ Tải CSV",
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
            st.caption(f"🚨 **Phát hiện {n_findings} điểm/xu hướng bất thường** trên dữ liệu. Chuyển sang tab **'{tab_insight_label}'** để xem báo cáo chi tiết.")

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
