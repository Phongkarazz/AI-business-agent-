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
from src.visualization.charts import render_smart_chart, format_col_title
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

    # 0. KIỂM TRA BÀI TOÁN PHÂN TÍCH TỶ LỆ GIỚI TÍNH (GENDER PARITY & BREAKDOWN)
    def _is_female_col(c: str) -> bool:
        cl = str(c).lower()
        if any(k in cl for k in ["pct", "percent", "rate", "tỷ lệ", "tỉ lệ", "%"]):
            return False
        return any(k in cl for k in ["female", "nu", "nữ", "women", "gender_f"])

    def _is_male_col(c: str) -> bool:
        cl = str(c).lower()
        if any(k in cl for k in ["pct", "percent", "rate", "tỷ lệ", "tỉ lệ", "%"]):
            return False
        if _is_female_col(c) or "department" in cl:
            return False
        return any(k in cl for k in ["male", "nam", "gender_m"]) or bool(re.search(r"\bmen\b", cl))

    female_cols = [c for c in df.columns if _is_female_col(c)]
    male_cols = [c for c in df.columns if _is_male_col(c)]
    if not female_cols:
        female_cols = [c for c in df.columns if any(k in str(c).lower() for k in ["female", "nu", "nữ", "women"])]
    if not male_cols:
        male_cols = [c for c in df.columns if any(k in str(c).lower() for k in ["male", "nam"]) and not any(k in str(c).lower() for k in ["female", "nu", "nữ", "women", "department"])]

    if male_cols and female_cols and total_rows > 1:
        m_c = male_cols[0]
        f_c = female_cols[0]
        s_male = pd.to_numeric(df[m_c], errors="coerce").fillna(0)
        s_female = pd.to_numeric(df[f_c], errors="coerce").fillna(0)

        # Kiểm tra xem đây là SO SÁNH LƯƠNG/THU NHẬP (Gender Pay Equity) hay SỐ LƯỢNG NHÂN SỰ (Gender Headcount)
        is_gender_salary = any(
            any(k in str(c).lower() for k in ["salary", "lương", "luong", "pay", "income", "wage", "thu nhập", "budget", "quỹ"])
            for c in (male_cols + female_cols)
        ) or any(k in (user_query or "").lower() for k in ["lương", "salary", "thu nhập", "income", "pay"])

        dim_col = label_cols[0] if label_cols else "Group"
        dim_name = "Chức danh" if any(k in str(dim_col).lower() for k in ["title", "chức danh", "job"]) else (
            "Phòng ban" if any(k in str(dim_col).lower() for k in ["dept", "phòng", "department"]) else "Nhóm"
        )

        if is_gender_salary:
            # --- BÀI TOÁN BÌNH ĐẲNG THU NHẬP (GENDER PAY GAP / SALARY COMPARISON) ---
            avg_m = s_male.mean()
            avg_f = s_female.mean()
            diff_val = avg_m - avg_f
            diff_pct = (diff_val / avg_f * 100.0) if avg_f > 0 else 0.0

            if diff_val > 50:
                gap_delta = f"Nam cao hơn {abs(diff_pct):.1f}%"
                gap_str = f"+${diff_val:,.0f}"
            elif diff_val < -50:
                gap_delta = f"Nữ cao hơn {abs(diff_pct):.1f}%"
                gap_str = f"-${abs(diff_val):,.0f}"
            else:
                gap_delta = "Tương đương chuẩn"
                gap_str = "$0"

            # Tìm đối tượng có khoảng cách chênh lệch lương lớn nhất
            gap_series = s_male - s_female
            max_abs_idx = gap_series.abs().idxmax()
            if label_cols and max_abs_idx in df.index:
                max_lbl = str(df.loc[max_abs_idx, label_cols[0]])
                max_v = gap_series.loc[max_abs_idx]
                max_p = (max_v / s_female.loc[max_abs_idx] * 100.0) if s_female.loc[max_abs_idx] > 0 else 0.0
                who = "Nam +" if max_v >= 0 else "Nữ +"
                max_delta = f"{who}${abs(max_v):,.0f} ({abs(max_p):.1f}%)"
            else:
                max_lbl = "N/A"
                max_delta = "N/A"

            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.metric("👨 " + ("Lương TB Nam" if not is_en else "Male Avg Salary"), f"${avg_m:,.0f}", delta=f"{total_rows} {dim_name}")
            with c2:
                st.metric("👩 " + ("Lương TB Nữ" if not is_en else "Female Avg Salary"), f"${avg_f:,.0f}", delta=f"Chuẩn {dim_name}")
            with c3:
                st.metric("⚖️ " + ("Chênh lệch (Pay Gap)" if not is_en else "Gender Pay Gap"), gap_str, delta=gap_delta)
            with c4:
                st.metric("🎯 " + ("Khoảng cách lớn nhất" if not is_en else "Max Gap Entity"), max_lbl, delta=max_delta)

            st.caption(
                f"ℹ️ **Phân tích Bình đẳng Thu nhập Giới tính (Gender Pay Equity)**: So sánh mức lương trung bình giữa nhân viên Nam và Nữ trên {total_rows} {dim_name} để đánh giá tính công bằng đãi ngộ."
                if not is_en else
                f"ℹ️ **Gender Pay Equity Analysis**: Comparing average compensation between Male and Female employees across {total_rows} {dim_name}s."
            )
            st.write("")
            return

        tot_m = s_male.sum()
        tot_f = s_female.sum()
        tot_all = tot_m + tot_f
        if tot_all > 0:
            pct_f = (tot_f / tot_all) * 100.0
            pct_m = (tot_m / tot_all) * 100.0
            balanced_depts = int((s_male == s_female).sum())
            is_mgr = any(k in (user_query or "").lower() for k in ["manager", "quản lý", "trưởng phòng"]) or any("manager" in str(c).lower() for c in df.columns)
            entity_name = "Quản lý" if is_mgr else ("Nhân sự" if not is_en else "Workforce")
            
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.metric("👔 " + (f"Tổng số {entity_name}" if not is_en else f"Total {entity_name}"), f"{int(tot_all):,}", delta=f"{total_rows} {dim_name}")
            with c2:
                st.metric("👩 " + ("Tỷ lệ Nữ (Female)" if not is_en else "Female Ratio"), f"{pct_f:.1f}%", delta=f"{int(tot_f):,} người")
            with c3:
                st.metric("👨 " + ("Tỷ lệ Nam (Male)" if not is_en else "Male Ratio"), f"{pct_m:.1f}%", delta=f"{int(tot_m):,} người")
            with c4:
                st.metric("⚖️ " + ("Cân bằng 50-50" if not is_en else "Gender Parity"), f"{balanced_depts}/{total_rows} {dim_name}", delta="Cân bằng tuyệt đối")
            
            if is_mgr and tot_all > 9:
                st.caption(
                    f"ℹ️ **Lưu ý nghiệp vụ**: Bảng số liệu phản ánh toàn bộ **{int(tot_all)} lượt bổ nhiệm Quản lý trong lịch sử** công ty (1985 – 2002). Hiện tại toàn công ty có **9 Trưởng phòng đương nhiệm**."
                    if not is_en else
                    f"ℹ️ **Business Note**: Figures reflect all **{int(tot_all)} historical management appointments** (1985 – 2002). The company currently has **9 active department managers**."
                )
            st.write("")
            return

    # KIỂM TRA BÀI TOÁN SO SÁNH KHỐI / NHÓM PHÒNG BAN (VD: KỸ THUẬT VS KINH DOANH)
    group_col_cand = [
        c for c in df.columns
        if any(k in str(c).lower() for k in ["group", "nhóm", "khối"])
        and not is_id_like(c)
    ]
    uq_low_comp = (user_query or "").lower()
    is_tech_vs_comm_query = (
        (any(k in uq_low_comp for k in ["kỹ thuật", "tech"]) and any(k in uq_low_comp for k in ["kinh doanh", "commercial", "sales"]))
        or (("development" in uq_low_comp or "research" in uq_low_comp) and ("sales" in uq_low_comp or "marketing" in uq_low_comp))
    ) and any(k in uq_low_comp for k in ["so sánh", "đối chiếu", "compare", "vs"])

    is_dept_group_comp = (
        (len(group_col_cand) > 0 or is_tech_vs_comm_query)
        and any(any(k in str(c).lower() for k in ["salary", "lương", "thu nhập", "amount", "budget"]) for c in measure_cols)
        and total_rows >= 2
    )
    if is_dept_group_comp:
        sal_cols = [c for c in measure_cols if any(k in str(c).lower() for k in ["salary", "lương", "thu nhập", "amount", "budget"])]
        sal_col = sal_cols[0] if sal_cols else measure_cols[0]
        hc_cols = [c for c in measure_cols if any(k in str(c).lower() for k in ["headcount", "totalemployees", "nhân sự", "nhân viên", "emp"])]
        hc_col = hc_cols[0] if hc_cols else None

        df_work = df.copy()
        if group_col_cand:
            grp_col = group_col_cand[0]
        else:
            dim_candidate = label_cols[0] if label_cols else df.columns[0]
            def _assign_group(val):
                v_low = str(val).lower()
                if any(k in v_low for k in ["sale", "market", "kinh doanh"]):
                    return "Kinh doanh"
                elif any(k in v_low for k in ["develop", "research", "kỹ thuật", "tech"]):
                    return "Kỹ thuật"
                return "Khác"
            df_work["_DeptGroup"] = df_work[dim_candidate].apply(_assign_group)
            grp_col = "_DeptGroup"

        groups = [g for g in df_work[grp_col].dropna().unique() if str(g).lower() != "khác"]
        if len(groups) >= 2:
            group_stats = []
            for g in groups:
                sub = df_work[df_work[grp_col] == g]
                sub_sal = pd.to_numeric(sub[sal_col], errors="coerce").dropna()
                if hc_col and hc_col in sub.columns:
                    sub_hc = pd.to_numeric(sub[hc_col], errors="coerce").fillna(0)
                    tot_hc = int(sub_hc.sum())
                    tot_prod = (sub_sal * sub_hc).sum()
                    avg_sal = float(tot_prod / tot_hc) if tot_hc > 0 else float(sub_sal.mean() or 0)
                else:
                    tot_hc = len(sub)
                    avg_sal = float(sub_sal.mean() or 0)

                g_str = str(g)
                # Tách tên ngắn gọn hiển thị
                g_short = g_str.split("(")[0].strip()
                group_stats.append({
                    "raw_name": g_str,
                    "short_name": g_short,
                    "avg_sal": avg_sal,
                    "tot_hc": tot_hc,
                    "count": len(sub)
                })

            group_stats.sort(key=lambda x: x["avg_sal"], reverse=True)
            g_high = group_stats[0]
            g_low = group_stats[1]

            diff_val = g_high["avg_sal"] - g_low["avg_sal"]
            diff_pct = (diff_val / g_low["avg_sal"] * 100.0) if g_low["avg_sal"] > 0 else 0.0

            # Tìm phòng ban cao nhất trong bảng
            detail_dim_cols = [c for c in label_cols if c != grp_col and c in df.columns]
            detail_col = detail_dim_cols[0] if detail_dim_cols else grp_col
            max_idx = pd.to_numeric(df[sal_col], errors="coerce").idxmax()
            min_idx = pd.to_numeric(df[sal_col], errors="coerce").idxmin()
            max_dept = str(df.loc[max_idx, detail_col]) if max_idx in df.index else "N/A"
            max_val = float(df.loc[max_idx, sal_col]) if max_idx in df.index else 0
            min_dept = str(df.loc[min_idx, detail_col]) if min_idx in df.index else "N/A"
            min_val = float(df.loc[min_idx, sal_col]) if min_idx in df.index else 0

            icon_high = "💼" if any(k in g_high["short_name"].lower() for k in ["kinh doanh", "sales", "commercial"]) else "💻"
            icon_low = "💻" if any(k in g_low["short_name"].lower() for k in ["kỹ thuật", "tech", "dev"]) else "🏢"

            delta_high = f"{g_high['tot_hc']:,} nhân sự" if hc_col else f"{g_high['count']} phòng ban"
            delta_low = f"{g_low['tot_hc']:,} nhân sự" if hc_col else f"{g_low['count']} phòng ban"

            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.metric(
                    f"{icon_high} " + (f"TB Khối {g_high['short_name']}" if not is_en else f"Avg {g_high['short_name']}"),
                    f"${g_high['avg_sal']:,.0f}",
                    delta=delta_high
                )
            with c2:
                st.metric(
                    f"{icon_low} " + (f"TB Khối {g_low['short_name']}" if not is_en else f"Avg {g_low['short_name']}"),
                    f"${g_low['avg_sal']:,.0f}",
                    delta=delta_low
                )
            with c3:
                st.metric(
                    "⚖️ " + ("Chênh lệch Thu nhập" if not is_en else "Pay Difference"),
                    f"+${diff_val:,.0f}",
                    delta=f"+{diff_pct:.1f}% nghiêng về {g_high['short_name']}" if not is_en else f"+{diff_pct:.1f}% higher in {g_high['short_name']}"
                )
            with c4:
                st.metric(
                    "🏆 " + (f"Cao nhất ({max_dept})" if not is_en else f"Top Entity ({max_dept})"),
                    f"${max_val:,.0f}",
                    delta=f"Thấp nhất: {min_dept} (${min_val:,.0f})" if not is_en else f"Lowest: {min_dept} (${min_val:,.0f})"
                )

            st.caption(
                f"ℹ️ **Đối chiếu Thu nhập Khối {g_high['short_name']} vs Khối {g_low['short_name']}**: "
                f"Khối {g_high['short_name']} có mức thu nhập trung bình cao hơn Khối {g_low['short_name']} **${diff_val:,.0f} (+{diff_pct:.1f}%)**, "
                f"trong đó phòng ban **{max_dept}** dẫn đầu với **${max_val:,.0f}**."
                if not is_en else
                f"ℹ️ **Compensation Comparison: {g_high['short_name']} vs {g_low['short_name']}**: "
                f"{g_high['short_name']} averages **${diff_val:,.0f} (+{diff_pct:.1f}%)** higher than {g_low['short_name']}, "
                f"led by **{max_dept}** at **${max_val:,.0f}**."
            )
            st.write("")
            return

    # KIỂM TRA BÀI TOÁN SO SÁNH ĐA CHIỀU: QUY MÔ NHÂN SỰ & MỨC LƯƠNG TRUNG BÌNH
    is_hc_sal_comp = (
        any(any(k in str(c).lower() for k in ["headcount", "totalemployees", "số lượng nhân sự", "nhân sự", "nhân viên"]) for c in measure_cols) and
        any(any(k in str(c).lower() for k in ["salary", "lương", "thu nhập"]) for c in measure_cols) and
        total_rows > 1
    )
    if is_hc_sal_comp:
        hc_col = [c for c in measure_cols if any(k in str(c).lower() for k in ["headcount", "totalemployees", "nhân sự", "nhân viên", "emp"])][0]
        sal_col = [c for c in measure_cols if any(k in str(c).lower() for k in ["salary", "lương", "thu nhập"])][0]
        dim_col = label_cols[0] if label_cols else "Department"

        total_hc = int(pd.to_numeric(df[hc_col], errors="coerce").fillna(0).sum())
        avg_sal = float(pd.to_numeric(df[sal_col], errors="coerce").dropna().mean() or 0)

        max_hc_idx = pd.to_numeric(df[hc_col], errors="coerce").idxmax()
        max_sal_idx = pd.to_numeric(df[sal_col], errors="coerce").idxmax()

        max_hc_dept = str(df.loc[max_hc_idx, dim_col]) if max_hc_idx in df.index else "N/A"
        max_hc_val = int(df.loc[max_hc_idx, hc_col]) if max_hc_idx in df.index else 0
        hc_pct = (max_hc_val / total_hc * 100.0) if total_hc > 0 else 0.0

        max_sal_dept = str(df.loc[max_sal_idx, dim_col]) if max_sal_idx in df.index else "N/A"
        max_sal_val = float(df.loc[max_sal_idx, sal_col]) if max_sal_idx in df.index else 0
        sal_diff = max_sal_val - avg_sal
        sal_diff_pct = (sal_diff / avg_sal * 100.0) if avg_sal > 0 else 0.0
        sign = "+" if sal_diff >= 0 else ""

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric(
                "👥 " + ("Tổng quy mô nhân sự" if not is_en else "Total Headcount"),
                f"{total_hc:,} Người",
                delta=f"{total_rows} Phòng ban" if not is_en else f"{total_rows} Depts"
            )
        with c2:
            st.metric(
                "💰 " + ("Mức lương TB chuẩn" if not is_en else "Benchmark Avg Salary"),
                f"${avg_sal:,.0f}",
                delta="Mặt bằng chung" if not is_en else "Company Benchmark"
            )
        with c3:
            st.metric(
                "🏢 " + ("Quy mô lớn nhất" if not is_en else "Largest Department"),
                max_hc_dept,
                delta=f"{max_hc_val:,} người ({hc_pct:.1f}%)"
            )
        with c4:
            st.metric(
                "🏆 " + ("Lương TB cao nhất" if not is_en else "Highest Avg Salary"),
                max_sal_dept,
                delta=f"${max_sal_val:,.0f} ({sign}{sal_diff_pct:.1f}% vs TB)"
            )

        st.caption(
            f"ℹ️ **So sánh Đa chiều (Headcount & Salary)**: Đối chiếu giữa quy mô nhân sự ({total_hc:,} người) và mức lương trung bình (${avg_sal:,.0f}) trên {total_rows} phòng ban để đánh giá cơ cấu chi phí và phân bổ nguồn lực."
            if not is_en else
            f"ℹ️ **Multi-dimensional Comparison**: Cross-analyzing headcount ({total_hc:,} employees) and average salary (${avg_sal:,.0f}) across {total_rows} departments."
        )
        st.write("")
        return

    if measure_cols and total_rows > 1:
        # Ưu tiên cột đo lường tuyệt đối (Count/Amount/Salary/YearsOfService) hơn cột % khi hiển thị trên thẻ KPI
        _uq_low = (user_query or "").lower()
        user_asked_efficiency = any(k in _uq_low for k in [
            "hiệu quả", "efficiency", "effectiveness", "năng suất", 
            "giá trị đơn hàng trung bình", "đơn hàng trung bình", "trung bình mỗi đơn", 
            "trung bình mỗi hộp", "order value", "per box", "per order", "aov", "performance", "profit per box",
            "lợi nhuận", "profit", "margin", "tỷ suất", "tỉ suất", "tỷ suất lợi nhuận", "tỉ suất lợi nhuận"
        ])
        eff_like_cols = [c for c in measure_cols if (any(k in str(c).lower() for k in [
            "avg", "ordervalue", "order_value", "profit", "margin", "lợi nhuận", "trung bình", "hiệu quả", "revenueperbox", "revenue_per_box"
        ]) or any(k in str(c).lower() for k in ["perbox", "per_box"])) and not any(k in str(c).lower() for k in ["cost", "giá vốn", "gia_von"])]

        if user_asked_efficiency and eff_like_cols:
            if any(k in _uq_low for k in ["tỷ suất", "tỉ suất", "margin", "%"]):
                m_candidates = [c for c in eff_like_cols if any(k in str(c).lower() for k in ["margin", "tỷ suất", "tỉ suất"])]
                m_col = m_candidates[0] if m_candidates else eff_like_cols[0]
            elif any(k in _uq_low for k in ["mỗi hộp", "per box", "hộp", "thùng"]):
                m_candidates = [c for c in eff_like_cols if any(k in str(c).lower() for k in ["perbox", "per_box"])]
                m_col = m_candidates[0] if m_candidates else eff_like_cols[0]
            else:
                m_col = eff_like_cols[0]
        else:
            count_like_cols = [c for c in measure_cols if not any(k in str(c).lower() for k in ["percent", "percentage", "pct", "tỷ lệ", "phan_tram", "rate", "ratio"])]
            # Ưu tiên cột tổng thể (Total/Tổng/All) nếu có
            total_like_cols = [c for c in count_like_cols if any(k in str(c).lower() for k in ["total", "tổng", "count_all", "all"])]
            m_col = total_like_cols[0] if total_like_cols else (count_like_cols[0] if count_like_cols else measure_cols[0])
        
        # Tách camelCase và chuẩn hóa tên chỉ số hiển thị chuyên nghiệp
        try:
            import re
            raw_m = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(m_col)).replace("_", " ").strip()
        except Exception:
            raw_m = str(m_col).replace("_", " ").strip()
        m_low = raw_m.lower()
        if not is_en:
            if any(k in m_low for k in ["totalsalarybudget", "total salary budget", "total_salary_budget", "salarybudget", "salary_budget", "quỹ lương"]):
                m_clean = "Quỹ Lương"
            elif any(k in m_low for k in ["current salary", "currentsalary", "lương mới nhất", "lương hiện tại"]):
                m_clean = "Lương Hiện Tại"
            elif any(k in m_low for k in ["avg order value", "avgordervalue", "order value", "ordervalue", "giá trị đơn hàng"]):
                m_clean = "Giá Trị Đơn Hàng TB"
            elif any(k in m_low for k in ["revenue per box", "revenueperbox", "sales per box", "salesperbox"]):
                m_clean = "Doanh Thu Mỗi Thùng"
            elif any(k in m_low for k in ["profit per box", "profitperbox"]):
                m_clean = "Lợi Nhuận Mỗi Hộp"
            elif any(k in m_low for k in ["profit margin", "profitmargin"]):
                m_clean = "Tỷ Suất Lợi Nhuận"
            elif any(k in m_low for k in ["avg salary", "avgsalary", "average salary"]):
                m_clean = "Lương Trung Bình"
            elif "salary" in m_low or "lương" in m_low:
                m_clean = "Mức Lương"
            elif any(k in m_low for k in ["headcount", "head count", "totalemployees", "total employees", "emp count", "empcount", "employee count", "employeecount", "số lượng nhân sự", "quy mô nhân sự"]):
                m_clean = "Quy Mô Nhân Sự"
            elif any(k in m_low for k in ["totalmanagers", "total managers", "quản lý"]):
                m_clean = "Số Lượng Quản Lý"
            elif any(k in m_low for k in ["years as manager", "yearsasmanager", "manager tenure", "managertenure", "manager years", "manageryears"]):
                m_clean = "Thâm Niên Quản Lý (Năm)"
            elif any(k in m_low for k in ["yearsofservice", "years of service", "thâm niên", "tenure"]):
                m_clean = "Thâm Niên (Năm)"
            elif any(k in m_low for k in ["boxes", "boxessold", "totalboxessold", "total_boxes", "hộp", "thùng"]):
                m_clean = "Tổng Số Hộp Bán Ra"
            elif "raisecount" in m_low:
                m_clean = "Số Lần Tăng Lương"
            else:
                m_clean = raw_m.title()
        else:
            m_clean = raw_m.title()

        # Kiểm tra truy vấn xếp hạng Top N / Ranking / So sánh
        is_top_query = any(k in (user_query or "").lower() for k in [
            "top", "danh sách", "hàng đầu", "cao nhất", "thấp nhất",
            "lâu nhất", "lịch sử", "xếp hạng", "nhiều nhất", "ít nhất",
            "dẫn đầu", "nổi bật", "ranking", "longest", "shortest",
            "lớn nhất", "nhỏ nhất", "so sánh", "bao nhiêu",
        ])
        # Phát hiện truy vấn so sánh cực trị (lớn nhất VÀ nhỏ nhất, highest AND lowest)
        _uq_low = (user_query or "").lower()
        is_comparison_query = (
            (any(k in _uq_low for k in ["lớn nhất", "cao nhất", "nhiều nhất", "highest", "largest", "most"])
             and any(k in _uq_low for k in ["nhỏ nhất", "thấp nhất", "ít nhất", "lowest", "smallest", "least"]))
            or ("và" in _uq_low and any(k in _uq_low for k in ["lớn nhất", "nhỏ nhất", "cao nhất", "thấp nhất"]))
        )
        scope_suffix = f" (Top {total_rows})" if is_top_query and total_rows <= 30 else ""

        # Ký hiệu tiền tệ và tỷ lệ phần trăm
        _m_col_lower = str(m_col).lower()
        _is_pct_measure = any(k in _m_col_lower for k in ["margin", "pct", "percent", "tỷ lệ", "tỉ lệ", "tỉ trọng", "tỷ trọng", "phần trăm"])
        is_currency = (not _is_pct_measure) and (any(k in _m_col_lower for k in ["salary", "lương", "budget", "quỹ", "tiền", "cost", "revenue", "chi phí", "thu nhập"]) or "profitperbox" in _m_col_lower or "ordervalue" in _m_col_lower)
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
            if label_series is None:
                # Nếu không có cột nhãn text/danh mục, tìm cột thời gian/chiều còn lại (Year, Date...)
                other_cols = [c for c in df.columns if c != m_col]
                if other_cols:
                    label_series = df[other_cols[0]]

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

            def _fmt_kpi_val(v, compact=True):
                try:
                    fv = float(v)
                    if _is_pct_measure:
                        return f"{fv:,.2f}%"
                    if compact:
                        if abs(fv) >= 1_000_000_000:
                            unit = " Tỷ" if not is_en else "B"
                            return f"{curr_symbol}{fv / 1_000_000_000:,.2f}{unit}"
                        elif abs(fv) >= 10_000_000 or (abs(fv) >= 1_000_000 and is_currency):
                            unit = " Tr" if not is_en else "M"
                            return f"{curr_symbol}{fv / 1_000_000:,.2f}{unit}"
                    if fv.is_integer() or fv > 100:
                        return f"{curr_symbol}{fv:,.0f}"
                    return f"{curr_symbol}{fv:,.2f}"
                except Exception:
                    return str(v)

            def _fmt_kpi_val_full(v):
                try:
                    fv = float(v)
                    if _is_pct_measure:
                        return f"{fv:,.2f}%"
                    if fv.is_integer() or fv > 100:
                        return f"{curr_symbol}{fv:,.0f}"
                    return f"{curr_symbol}{fv:,.2f}"
                except Exception:
                    return str(v)

            # Phát hiện measure là duration (years/tenure/thâm niên) để thêm đơn vị " Năm"
            _is_years_measure = any(k in _m_col_lower for k in [
                "years", "year_as", "yearsas", "tenure", "thâm niên", "tham_nien",
                "service", "thamnien",
            ])
            _year_unit = " Năm" if _is_years_measure else ""

            fmt_avg = _fmt_kpi_val(avg_val) + _year_unit
            fmt_peak = _fmt_kpi_val(peak_val) + _year_unit
            fmt_min = _fmt_kpi_val(min_val) + _year_unit

            # Kiểm tra xem m_col có phải là giá trị trung bình/tỷ lệ/min/max hoặc duration (để tránh lỗi cộng dồn thống kê)
            is_avg_or_rate = any(k in m_col.lower() for k in [
                "avg", "average", "mean", "trung_bình", "rate", "ratio", "pct", "percent", "tỷ_lệ", "max", "min",
                "profitmargin", "profit_margin", "profitperbox", "profit_per_box", "margin", "revenueperbox",
                # Duration/Tenure measures — KHÔNG nên cộng tổng
                "years", "yearsas", "year_as", "tenure", "thâm niên", "tham_nien",
                "service", "duration", "thamnien",
            ])

            # Kiểm tra xem có phải là chuỗi thời gian (Time-series: Year, Month, Date...)
            dim_cols = [c for c in df.columns if c != m_col]
            # Các cột phụ trợ ngày tháng (StartDate, EndDate, from_date, to_date...) KHÔNG nên trigger time-series
            _auxiliary_date_keywords = {"startdate", "enddate", "start_date", "end_date",
                                        "fromdate", "from_date", "todate", "to_date",
                                        "hire_date", "hiredate", "birth_date", "birthdate",
                                        "termination_date", "terminationdate"}
            # Các cột tên/nhãn cũng KHÔNG nên trigger time-series
            _name_like_keywords = {"managername", "manager_name", "fullname", "full_name",
                                   "empname", "emp_name", "employeename", "employee_name",
                                   "deptname", "dept_name", "departmentname", "department_name",
                                   "department", "gender", "title", "empno", "emp_no"}
            _exclude_keywords = _auxiliary_date_keywords | _name_like_keywords
            # Từ khoá thời gian dài (an toàn cho substring match)
            _time_long_keywords = ["year", "thang", "month", "quarter", "date"]
            # Từ khoá thời gian ngắn (cần exact match hoặc word-boundary để tránh false positive)
            _time_exact_keywords = {"nam", "quy"}
            is_time_dim = False
            for c in dim_cols:
                c_lower = str(c).lower().replace(" ", "")
                c_norm = re.sub(r"[^a-z0-9]", "", c_lower)
                # Bỏ qua các cột phụ trợ ngày tháng và cột tên/nhãn
                if c_norm in _exclude_keywords or c_lower in _exclude_keywords:
                    continue
                # Check từ khoá dài (substring match OK)
                if any(k in c_lower for k in _time_long_keywords):
                    is_time_dim = True
                    break
                # Check từ khoá ngắn (exact match trên c_norm)
                if c_norm in _time_exact_keywords:
                    is_time_dim = True
                    break

            # Nếu measure là duration/thâm niên/tenure VÀ truy vấn là ranking → KHÔNG phải time-series
            _is_duration_measure = any(k in str(m_col).lower() for k in [
                "years", "year_as", "yearsas", "tenure", "thâm niên", "tham_nien",
                "service", "duration", "months_as", "monthsas",
            ])
            if _is_duration_measure and (is_top_query or total_rows <= 30):
                is_time_dim = False

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

            # --- LAYOUT SO SÁNH CỰC TRỊ (lớn nhất VÀ nhỏ nhất, chỉ 2-3 dòng) ---
            if is_comparison_query and total_rows <= 3 and not is_time_dim:
                # Chọn icon phù hợp theo ngữ cảnh
                if is_currency:
                    _cmp_icon = "💰"
                elif any(k in m_low for k in ["manager", "quản lý"]):
                    _cmp_icon = "👔"
                elif any(k in m_low for k in ["employee", "headcount", "nhân sự", "nhân viên", "quy mô"]):
                    _cmp_icon = "👥"
                else:
                    _cmp_icon = "📊"

                # Tính chênh lệch
                try:
                    _diff = float(peak_val) - float(min_val)
                    _ratio = float(peak_val) / float(min_val) if float(min_val) > 0 else 0
                    _fmt_diff = _fmt_kpi_val(_diff) + _year_unit
                    _fmt_ratio = f"{_ratio:.1f}x"
                except Exception:
                    _fmt_diff = "N/A"
                    _fmt_ratio = "N/A"

                with col1:
                    st.metric(f"🏆 " + ("Lớn nhất" if not is_en else "Largest"), peak_label, delta=fmt_peak)
                with col2:
                    st.metric(f"📉 " + ("Nhỏ nhất" if not is_en else "Smallest"), min_label, delta=fmt_min)
                with col3:
                    st.metric(f"📊 " + ("Chênh lệch" if not is_en else "Difference"), _fmt_diff, delta=_fmt_ratio)
                with col4:
                    st.metric(f"{_cmp_icon} " + (f"TB {m_clean}" if not is_en else f"Avg {m_clean}"), fmt_avg)

            elif is_time_dim:
                # CHUỖI THỜI GIAN THEO NĂM/THÁNG:
                dim_c = dim_cols[0] if dim_cols else "Year"
                dim_vals = df[dim_c].dropna()
                min_dim = str(dim_vals.min()) if not dim_vals.empty else ""
                max_dim = str(dim_vals.max()) if not dim_vals.empty else ""
                is_year_unit = any(k in str(dim_c).lower() for k in ["year", "nam"])
                is_month_unit = any(k in str(dim_c).lower() for k in ["month", "thang", "tháng"])
                dim_unit = ("Năm" if not is_en else "Years") if is_year_unit else (("Tháng" if not is_en else "Months") if is_month_unit else ("Kỳ" if not is_en else "Periods"))
                with col1:
                    st.metric("📅 " + ("Giai đoạn theo dõi" if not is_en else "Tracking Period"), f"{total_rows} {dim_unit}" + (f" ({min_dim} – {max_dim})" if min_dim != max_dim else ""))
                with col2:
                    st.metric("📈 " + ("Mức trung bình chuẩn" if not is_en else "Benchmark Average"), fmt_avg, help=_fmt_kpi_val_full(avg_val))
                with col3:
                    delta_p = _fmt_kpi_val_full(peak_val) if fmt_peak != _fmt_kpi_val_full(peak_val) else None
                    st.metric(f"🏆 " + (f"Đỉnh cao nhất ({dim_unit} {peak_label})" if not is_en else f"Peak ({peak_label})"), fmt_peak, delta=delta_p)
                with col4:
                    delta_m = _fmt_kpi_val_full(min_val) if fmt_min != _fmt_kpi_val_full(min_val) else None
                    st.metric(f"📉 " + (f"Thấp nhất ({dim_unit} {min_label})" if not is_en else f"Lowest ({min_label})"), fmt_min, delta=delta_m)

                # Kiểm tra năm 2002 có bị sụt giảm tự nhiên do dữ liệu ghi nhận 8 tháng không
                if any(str(v) == "2002" for v in dim_vals):
                    try:
                        row_2002 = df[df[dim_c].astype(str) == "2002"]
                        row_2001 = df[df[dim_c].astype(str) == "2001"]
                        if not row_2002.empty and not row_2001.empty:
                            v02 = float(row_2002[m_col].iloc[0])
                            v01 = float(row_2001[m_col].iloc[0])
                            if v01 > 0 and v02 < v01 * 0.8:
                                st.caption(
                                    "ℹ️ **Lưu ý dữ liệu tài chính**: Năm 2002 cơ sở dữ liệu chỉ ghi nhận đến tháng 08/2002 (8 tháng) "
                                    "nên tổng quỹ lương bị hụt tự nhiên so với các năm đủ 12 tháng, không phản ánh sự suy thoái kinh doanh."
                                    if not is_en else
                                    "ℹ️ **Financial Data Note**: Year 2002 records only contain data up to August 2002 (8 months), "
                                    "causing an apparent drop compared to full 12-month years, not an actual operational decline."
                                )
                    except Exception:
                        pass
            elif is_avg_or_rate:
                # CỘT TRUNG BÌNH/TỶ LỆ/DURATION: Hiển thị Thống kê tổng hợp khoa học, KHÔNG cộng dồn!
                if is_top_query and total_rows <= 30:
                    # --- LAYOUT ĐẶC BIỆT: XẾP HẠNG TOP N (Chức danh / Quản lý / Phòng ban / Nhân sự) ---
                    _dim_col = label_cols[0] if label_cols else (dim_cols[0] if dim_cols else "")
                    _dim_low = str(_dim_col).lower()
                    if any(k in _dim_low for k in ["title", "chức danh", "job"]):
                        entity_name = "Chức danh" if not is_en else "Job Titles"
                    elif any(k in _dim_low for k in ["dept", "phòng", "department"]):
                        entity_name = "Phòng ban" if not is_en else "Departments"
                    elif any(k in _dim_low for k in ["manager", "quản lý", "trưởng phòng"]):
                        entity_name = "Quản lý" if not is_en else "Managers"
                    elif any(k in _dim_low for k in ["employee", "nhân sự", "nhân viên", "emp", "name"]):
                        entity_name = "Nhân sự" if not is_en else "Employees"
                    else:
                        entity_name = ""

                    card1_title = "🏆 " + ("Xếp hạng" if not is_en else "Ranking")
                    card1_val = f"Top {total_rows}" + (f" {entity_name}" if entity_name else "")

                    # Tính delta so với giá trị trung bình chuẩn của Top N
                    try:
                        diff_peak = float(peak_val) - float(avg_val)
                        pct_peak = (diff_peak / float(avg_val) * 100) if float(avg_val) > 0 else 0
                        sign_p = "+" if diff_peak >= 0 else ""
                        delta_peak = f"{sign_p}{pct_peak:.1f}% vs TB"
                    except Exception:
                        delta_peak = None

                    try:
                        diff_min = float(min_val) - float(avg_val)
                        pct_min = (diff_min / float(avg_val) * 100) if float(avg_val) > 0 else 0
                        sign_m = "+" if diff_min >= 0 else ""
                        delta_min = f"{sign_m}{pct_min:.1f}% vs TB"
                    except Exception:
                        delta_min = None

                    with col1:
                        st.metric(card1_title, card1_val)
                    with col2:
                        st.metric("📊 " + (f"TB Top {total_rows}" if not is_en else f"Avg Top {total_rows}"), fmt_avg)
                    with col3:
                        st.metric(f"🥇 " + (f"#1 {peak_label}" if not is_en else f"#1 {peak_label}"), fmt_peak, delta=delta_peak)
                    with col4:
                        st.metric(f"🏅 " + (f"#{total_rows} {min_label}" if not is_en else f"#{total_rows} {min_label}"), fmt_min, delta=delta_min)
                elif target_idx is not None and target_idx in valid_vals.index:
                    # --- LAYOUT ĐẶC BIỆT: ĐỐI TƯỢNG MỤC TIÊU VS CÁC ĐỐI TƯỢNG KHÁC ---
                    t_val = df.loc[target_idx, m_col]
                    fmt_t_val = _fmt_kpi_val(t_val) + _year_unit
                    rank = int((valid_vals > t_val).sum()) + 1
                    diff_vs_avg = float(t_val) - float(avg_val)
                    pct_vs_avg = ((float(t_val) - float(avg_val)) / float(avg_val) * 100) if float(avg_val) > 0 else 0
                    sign = "+" if diff_vs_avg >= 0 else ""
                    delta_vs_avg = f"{sign}{pct_vs_avg:.1f}% vs TB"

                    with col1:
                        st.metric(f"🎯 {target_name}", fmt_t_val, delta=f"Hạng {rank}/{total_rows}")
                    with col2:
                        st.metric(f"📈 " + ("Mức trung bình chuẩn" if not is_en else "Benchmark Average"), fmt_avg, delta=delta_vs_avg)
                    with col3:
                        st.metric(f"🏆 " + ("Dẫn đầu (Cao nhất)" if not is_en else "Highest"), peak_label, delta=f"{fmt_peak}")
                    with col4:
                        st.metric(f"📉 " + ("Thấp nhất" if not is_en else "Lowest"), min_label, delta=f"{fmt_min}")
                else:
                    _dim_col = label_cols[0] if label_cols else (dim_cols[0] if dim_cols else "")
                    _dim_low = str(_dim_col).lower()
                    if any(k in _dim_low for k in ["dept", "phòng", "department"]):
                        _card1_title = "🏢 " + ("Số phòng ban" if not is_en else "Departments")
                        _card1_val = f"{total_rows} Phòng"
                    elif any(k in _dim_low for k in ["title", "chức danh", "job"]):
                        _card1_title = "💼 " + ("Số chức danh" if not is_en else "Job Titles")
                        _card1_val = f"{total_rows} Chức danh"
                    elif any(k in _dim_low for k in ["manager", "quản lý", "trưởng phòng"]):
                        _card1_title = "👔 " + ("Số quản lý" if not is_en else "Managers")
                        _card1_val = f"{total_rows:,} Người"
                    elif any(k in _dim_low for k in ["employee", "nhân sự", "nhân viên", "emp", "name"]):
                        _card1_title = "👥 " + ("Số nhân sự" if not is_en else "Employees")
                        _card1_val = f"{total_rows:,} Người"
                    else:
                        _card1_title = "📋 " + ("Số đối tượng so sánh" if not is_en else "Comparing Entities")
                        _card1_val = f"{total_rows:,}"

                    with col1:
                        st.metric(_card1_title, _card1_val)
                    with col2:
                        st.metric(f"📈 " + ("Mức trung bình chuẩn" if not is_en else "Benchmark Average"), fmt_avg)
                    with col3:
                        st.metric(f"🏆 " + ("Dẫn đầu (Cao nhất)" if not is_en else "Highest"), peak_label, delta=f"{fmt_peak}")
                    with col4:
                        st.metric(f"📉 " + ("Thấp nhất" if not is_en else "Lowest"), min_label, delta=f"{fmt_min}")
            else:
                # CỘT SỐ LƯỢNG/TỔNG QUỸ/TIỀN TỆ TUYỆT ĐỐI: Hiển thị Tổng cộng
                total_val = valid_vals.sum()
                fmt_total = _fmt_kpi_val(total_val)

                # Tránh lặp từ "Tổng Total ..."
                prefix = "Tổng " if not is_en else "Total "
                if m_clean.lower().startswith("total ") or m_clean.lower().startswith("tổng ") or m_clean.lower().startswith("số lượng "):
                    clean_card_title = m_clean
                else:
                    clean_card_title = prefix + m_clean

                # Chọn icon phù hợp theo ngữ cảnh dữ liệu
                if is_currency:
                    card_icon = "💰 "
                elif any(k in m_low for k in ["manager", "quản lý", "trưởng phòng"]):
                    card_icon = "👔 "
                elif any(k in m_low for k in ["employee", "headcount", "nhân sự", "nhân viên", "hires", "tuyển dụng", "quy mô"]):
                    card_icon = "👥 "
                elif any(k in m_low for k in ["raisecount", "lần tăng", "raise"]):
                    card_icon = "📈 "
                else:
                    card_icon = "📊 "

                if target_idx is not None and target_idx in valid_vals.index:
                    t_val = df.loc[target_idx, m_col]
                    fmt_t_val = _fmt_kpi_val(t_val)
                    rank = int((valid_vals > t_val).sum()) + 1
                    diff_vs_avg = float(t_val) - float(avg_val)
                    pct_vs_avg = ((float(t_val) - float(avg_val)) / float(avg_val) * 100) if float(avg_val) > 0 else 0
                    sign = "+" if diff_vs_avg >= 0 else ""
                    delta_vs_avg = f"{sign}{pct_vs_avg:.1f}% vs TB"

                    with col1:
                        st.metric(f"🎯 {target_name}", fmt_t_val, delta=f"Hạng {rank}/{total_rows}")
                    with col2:
                        st.metric(f"📈 " + ("Trung bình" if not is_en else "Average"), fmt_avg, delta=delta_vs_avg)
                    with col3:
                        st.metric(f"{card_icon}{clean_card_title}{scope_suffix}", fmt_total)
                    with col4:
                        st.metric(f"🏆 " + ("Đỉnh cao nhất" if not is_en else "Peak Record"), peak_label, delta=f"{fmt_peak}")
                else:
                    with col1:
                        if is_top_query and total_rows <= 30:
                            _dim_col = label_cols[0] if label_cols else "Department"
                            _dim_low = str(_dim_col).lower()
                            if any(k in _dim_low for k in ["dept", "phòng", "department"]):
                                _entity_top = " Phòng ban" if not is_en else " Departments"
                            elif any(k in _dim_low for k in ["title", "chức danh", "job"]):
                                _entity_top = " Chức danh" if not is_en else " Job Titles"
                            elif any(k in _dim_low for k in ["manager", "quản lý"]):
                                _entity_top = " Quản lý" if not is_en else " Managers"
                            elif any(k in _dim_low for k in ["employee", "nhân sự", "nhân viên", "name", "tên"]):
                                _entity_top = " Nhân sự" if not is_en else " Employees"
                            else:
                                _entity_top = ""
                            st.metric("🏆 " + ("Xếp hạng" if not is_en else "Ranking"), f"Top {total_rows}{_entity_top}")
                        else:
                            _dim_col = label_cols[0] if label_cols else "Department"
                            _dim_low = str(_dim_col).lower()
                            if any(k in _dim_low for k in ["dept", "phòng", "department"]):
                                _card1_title = "🏢 " + ("Số phòng ban" if not is_en else "Departments")
                                _card1_val = f"{total_rows} Phòng"
                            elif any(k in _dim_low for k in ["title", "chức danh", "job"]):
                                _card1_title = "💼 " + ("Số chức danh" if not is_en else "Job Titles")
                                _card1_val = f"{total_rows} Chức danh"
                            elif any(k in _dim_low for k in ["year", "năm", "hireyear"]):
                                _card1_title = "📅 " + ("Giai đoạn" if not is_en else "Period")
                                _card1_val = f"{total_rows} Năm"
                            elif any(k in _dim_low for k in ["name", "tên", "employee", "nhân viên"]):
                                _card1_title = "👥 " + ("Số nhân sự" if not is_en else "Employees")
                                _card1_val = f"{total_rows:,} Người"
                            else:
                                _card1_title = "📋 " + ("Tổng số đối tượng" if not is_en else "Total Entities")
                                _card1_val = f"{total_rows:,}"
                            st.metric(_card1_title, _card1_val)
                    with col2:
                        st.metric(f"{card_icon}{clean_card_title}{scope_suffix}", fmt_total)
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


def render_insight_cards(insights_raw: str, df: pd.DataFrame = None, is_en: bool = False, user_query: str = ""):
    """Render 3 Thẻ Giao Diện Độc Lập (Cards) cho Insight: Bất thường, Nguyên nhân, Đề xuất chiến lược phân cấp 3 bậc."""
    if not insights_raw and (df is None or df.empty):
        return

    sections = split_insight_sections(insights_raw or "", df=df, user_query=user_query, is_en=is_en)
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

    try:
        # Tự động gắn nhãn huy chương cho bảng xếp hạng Top N
        is_ranking = any(k in (user_query or "").lower() for k in ["top", "cao nhất", "thấp nhất", "xếp hạng", "danh sách", "lâu nhất", "nhiều nhất"])
        if is_ranking and len(display_df) <= 50:
            medals = {0: "🥇 #1", 1: "🥈 #2", 2: "🥉 #3"}
            display_df.index = [medals.get(i, f"#{i+1}") for i in range(len(display_df))]
            display_df.index.name = "Xếp hạng" if not is_en else "Rank"

        column_config = {}
        for col in display_df.columns:
            c_low = str(col).lower()
            col_label = format_col_title(col) if not is_en else col
            if is_id_like(col):
                column_config[col] = st.column_config.NumberColumn(col_label, format="%d")
            elif any(k in c_low for k in ["pct", "percent", "percentage", "tỷ lệ", "tỉ lệ", "tỉ trọng", "tỷ trọng", "phần trăm", "share", "rate", "ratio", "margin"]):
                column_config[col] = st.column_config.NumberColumn(
                    col_label,
                    format="%.2f%%"
                )
            elif any(k in c_low for k in ["salary", "lương", "thu nhập", "budget", "quỹ", "tiền", "cost", "revenue", "chi phí", "sales", "amount", "profit", "ordervalue"]):
                has_decimals = False
                try:
                    numeric_vals = pd.to_numeric(display_df[col], errors="coerce").dropna()
                    has_decimals = any(not float(v).is_integer() for v in numeric_vals)
                except Exception:
                    pass
                column_config[col] = st.column_config.NumberColumn(
                    col_label,
                    format="$%,.2f" if has_decimals else "$%,d"
                )
            elif any(k in c_low for k in ["headcount", "hires", "raise", "count", "số lượng", "tổng số", "boxes", "thùng", "hộp"]):
                column_config[col] = st.column_config.NumberColumn(
                    col_label,
                    format="%,d"
                )
            else:
                column_config[col] = st.column_config.Column(col_label)

        st.dataframe(display_df, column_config=column_config, width='stretch')
    except Exception:
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
            render_insight_cards(insights, df=df, is_en=is_en, user_query=result.get("query", ""))
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
                        render_insight_cards(clean_gen, df=df, is_en=is_en, user_query=result.get("query", ""))

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
