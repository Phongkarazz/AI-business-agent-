"""
Reusable UI components for rendering query results, charts, forecasts, and notifications.
"""

import streamlit as st
from src.config import LOG_INLINE_MAX_CHARS
from src.analytics.heuristics import get_axis_columns
from src.analytics.anomaly import detect_outliers
from src.analytics.forecasting import forecast_series
from src.visualization.charts import render_smart_chart
from src.llm.agent import explain_anomalies_agent


def notify(message: str, detail: str = None, icon: str = "⚠️", toast_only: bool = False):
    """Hiển thị thông báo bằng toast góc màn hình và caption rõ ràng."""
    st.toast(message, icon=icon)
    if not toast_only:
        st.caption(f"{icon} {message}")
        if detail:
            with st.expander("Xem chi tiết kỹ thuật", expanded=False):
                st.code(detail)


def render_result(result: dict, turn_id: str):
    """Hiển thị kết quả truy vấn gồm Log, SQL, Bảng dữ liệu, Biểu đồ và Dự báo."""
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

    # 4. Tabs: Biểu đồ & Dự báo
    tab1, tab2 = st.tabs(["📊 Biểu đồ", "🔮 Dự báo"])

    with tab1:
        chart_override = st.selectbox(
            "Loại biểu đồ",
            ["Tự động", "Line", "Bar", "Area", "Scatter"],
            key=f"charttype_{turn_id}"
        )
        render_smart_chart(df, chart_override, turn_id)

        measure_cols, _, time_col = get_axis_columns(df)
        if time_col and measure_cols:
            y_col = measure_cols[0]
            outliers = detect_outliers(df, y_col)
            if not outliers.empty:
                if st.button(f"🔍 AI giải thích {len(outliers)} điểm bất thường", key=f"outlier_{turn_id}"):
                    client = st.session_state.get("client")
                    provider = st.session_state.get("provider")
                    model_name = st.session_state.get("model_name")
                    with st.spinner("AI đang phân tích bất thường..."):
                        explanation = explain_anomalies_agent(
                            client, provider, model_name, result["query"], time_col, y_col, outliers
                        )
                    if explanation:
                        st.info(f"🤖 **Nhận xét AI:** {explanation}")

    with tab2:
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
