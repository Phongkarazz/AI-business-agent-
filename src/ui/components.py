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


def render_voice_input_button(key: str = "voice_input_widget", compact: bool = True):
    """Tích hợp nút Micro nhập liệu bằng giọng nói tiếng Việt thời gian thực (Web Speech API)
    trực tiếp vào bên trong thanh tìm kiếm Hero Search (và Chat Input).

    Quy tắc UX theo yêu cầu người dùng:
    - Nút micro nằm ngay bên trong mép phải của thanh tìm kiếm (không nằm rời rạc ở cột riêng).
    - Khi ô tìm kiếm rỗng: hiển thị icon micro 🎙️ trực quan.
    - Khi người dùng gõ bất kỳ ký tự nào vào ô: nút micro TỰ ĐỘNG BIẾN MẤT ngay lập tức.
    - Khi người dùng xóa hết chữ: nút micro TỰ ĐỘNG XUẤT HIỆN trở lại.
    - Khi nói xong: tự động điền câu hỏi vào ô tìm kiếm và ẩn micro để người dùng sẵn sàng gửi.
    """
    voice_html = """
    <body style="margin: 0; padding: 0; overflow: hidden; background: transparent;">
    <script>
    (function() {
        const parentDoc = window.parent.document;
        const parentWin = window.parent;
        if (!parentDoc || !parentWin) return;

        // 1. Ẩn iframe container này để không chiếm diện tích trên giao diện
        try {
            if (window.frameElement) {
                const f = window.frameElement;
                f.style.cssText = "position:absolute !important; width:0px !important; height:0px !important; min-height:0px !important; max-height:0px !important; border:none !important; margin:0px !important; padding:0px !important; opacity:0 !important; pointer-events:none !important; z-index:-9999 !important;";
                if (f.parentElement) {
                    f.parentElement.style.cssText = "height:0px !important; min-height:0px !important; margin:0px !important; padding:0px !important; overflow:hidden !important;";
                }
            }
        } catch(e) {}

        // 2. Chèn CSS dùng chung cho Micro và Animation vào parent document nếu chưa có
        if (!parentDoc.getElementById('integrated-voice-mic-styles')) {
            const style = parentDoc.createElement('style');
            style.id = 'integrated-voice-mic-styles';
            style.textContent = `
                @keyframes micWavePulse {
                    0% { transform: translateY(-50%) scale(1); box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.45); }
                    70% { transform: translateY(-50%) scale(1.1); box-shadow: 0 0 0 8px rgba(239, 68, 68, 0); }
                    100% { transform: translateY(-50%) scale(1); box-shadow: 0 0 0 0 rgba(239, 68, 68, 0); }
                }
                .integrated-hero-mic-btn {
                    position: absolute !important;
                    right: 12px !important;
                    top: 50% !important;
                    transform: translateY(-50%) !important;
                    z-index: 10 !important;
                    width: 32px !important;
                    height: 32px !important;
                    border-radius: 8px !important;
                    border: 1px solid transparent !important;
                    background: transparent !important;
                    color: #64748B !important;
                    cursor: pointer !important;
                    display: inline-flex !important;
                    align-items: center !important;
                    justify-content: center !important;
                    font-size: 17px !important;
                    padding: 0 !important;
                    margin: 0 !important;
                    transition: all 0.15s ease !important;
                    outline: none !important;
                    user-select: none !important;
                }
                .integrated-hero-mic-btn:hover {
                    background: #F1F5F9 !important;
                    color: #2563EB !important;
                    border-color: #CBD5E1 !important;
                }
                .integrated-hero-mic-btn.recording {
                    background: #FEF2F2 !important;
                    color: #DC2626 !important;
                    border-color: #F87171 !important;
                    animation: micWavePulse 1.2s infinite ease-in-out !important;
                }
                .integrated-chat-mic-btn {
                    border: none !important;
                    background: transparent !important;
                    color: #64748B !important;
                    cursor: pointer !important;
                    display: inline-flex !important;
                    align-items: center !important;
                    justify-content: center !important;
                    font-size: 18px !important;
                    padding: 6px !important;
                    margin-right: 4px !important;
                    border-radius: 6px !important;
                    transition: all 0.15s ease !important;
                    outline: none !important;
                }
                .integrated-chat-mic-btn:hover {
                    background: #F1F5F9 !important;
                    color: #2563EB !important;
                }
                .integrated-chat-mic-btn.recording {
                    background: #FEF2F2 !important;
                    color: #DC2626 !important;
                    border-radius: 50% !important;
                    animation: micWavePulse 1.2s infinite ease-in-out !important;
                }
            `;
            parentDoc.head.appendChild(style);
        }

        let globalRecognition = null;
        let isListening = false;

        function startVoiceCapture(targetInput, micBtn, isChatArea) {
            const SpeechRec = parentWin.SpeechRecognition || parentWin.webkitSpeechRecognition || window.SpeechRecognition || window.webkitSpeechRecognition;
            if (!SpeechRec) {
                alert('Trình duyệt của bạn chưa hỗ trợ nhận diện giọng nói (Web Speech API). Vui lòng dùng Chrome, Edge hoặc Safari.');
                return;
            }

            if (isListening) {
                if (globalRecognition) {
                    try { globalRecognition.stop(); } catch(e) {}
                }
                isListening = false;
                stopButtonUI(micBtn, targetInput);
                return;
            }

            try {
                globalRecognition = new SpeechRec();
                globalRecognition.lang = 'vi-VN';
                globalRecognition.continuous = false;
                globalRecognition.interimResults = false;

                globalRecognition.onstart = function() {
                    isListening = true;
                    micBtn.classList.add('recording');
                    micBtn.innerHTML = '🔴';
                    micBtn.title = 'Đang lắng nghe tiếng Việt... Bấm để dừng';
                    micBtn.style.display = 'inline-flex';
                };

                globalRecognition.onresult = function(event) {
                    isListening = false;
                    const transcript = event.results[0][0].transcript.trim();
                    if (transcript && targetInput) {
                        const proto = isChatArea 
                            ? parentWin.HTMLTextAreaElement.prototype 
                            : parentWin.HTMLInputElement.prototype;
                        const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
                        if (setter) {
                            setter.call(targetInput, transcript);
                        } else {
                            targetInput.value = transcript;
                        }
                        targetInput.dispatchEvent(new parentWin.Event('input', { bubbles: true }));
                        targetInput.dispatchEvent(new parentWin.Event('change', { bubbles: true }));

                        targetInput.focus();
                        try {
                            targetInput.setSelectionRange(targetInput.value.length, targetInput.value.length);
                        } catch(e) {}
                    }
                    stopButtonUI(micBtn, targetInput);
                };

                globalRecognition.onerror = function(event) {
                    isListening = false;
                    stopButtonUI(micBtn, targetInput);
                };

                globalRecognition.onend = function() {
                    isListening = false;
                    stopButtonUI(micBtn, targetInput);
                };

                globalRecognition.start();
            } catch(err) {
                isListening = false;
                stopButtonUI(micBtn, targetInput);
            }
        }

        function stopButtonUI(micBtn, targetInput) {
            if (!micBtn) return;
            micBtn.classList.remove('recording');
            micBtn.innerHTML = '🎙️';
            micBtn.title = 'Nói câu hỏi bằng Tiếng Việt (Voice Input)';

            if (targetInput) {
                const hasVal = targetInput.value && targetInput.value.trim().length > 0;
                micBtn.style.display = hasVal ? 'none' : 'inline-flex';
            }
        }

        // 3. Tích hợp trực tiếp vào Hero Search Bar
        function attachHeroSearchMic() {
            const heroInput = parentDoc.querySelector('form[data-testid="stForm"] input[type="text"]') || 
                              parentDoc.querySelector('div[data-testid="stTextInput"] input[type="text"]') ||
                              parentDoc.querySelector('input[aria-label="Search"]');
            if (!heroInput) return;

            const container = heroInput.parentElement;
            if (!container) return;

            // Đảm bảo container relative và input có padding-right chống đè icon
            container.style.position = 'relative';
            heroInput.style.paddingRight = '46px';

            let micBtn = container.querySelector('#integratedHeroMicBtn');
            if (!micBtn) {
                micBtn = parentDoc.createElement('button');
                micBtn.id = 'integratedHeroMicBtn';
                micBtn.type = 'button';
                micBtn.className = 'integrated-hero-mic-btn';
                micBtn.innerHTML = '🎙️';
                micBtn.title = 'Nói câu hỏi bằng Tiếng Việt (Voice Input)';

                micBtn.onclick = function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    startVoiceCapture(heroInput, micBtn, false);
                };

                container.appendChild(micBtn);
            }

            // Tự động biến mất khi nhập câu hỏi, tự động xuất hiện khi rỗng
            function checkHeroVisibility() {
                if (!micBtn) return;
                if (micBtn.classList.contains('recording')) {
                    micBtn.style.display = 'inline-flex';
                    return;
                }
                const hasText = heroInput.value && heroInput.value.trim().length > 0;
                micBtn.style.display = hasText ? 'none' : 'inline-flex';
            }

            ['input', 'keyup', 'keydown', 'change', 'paste', 'cut'].forEach(evt => {
                heroInput.removeEventListener(evt, checkHeroVisibility);
                heroInput.addEventListener(evt, checkHeroVisibility);
            });

            checkHeroVisibility();
        }

        // 4. Tích hợp vào Chat Input ở chân trang (khi đang trong hội thoại)
        function attachChatInputMic() {
            const chatInputContainer = parentDoc.querySelector('div[data-testid="stChatInput"]');
            if (!chatInputContainer) return;

            const chatTextArea = chatInputContainer.querySelector('textarea');
            const submitBtn = chatInputContainer.querySelector('button[data-testid="stChatInputSubmitButton"]');
            if (!chatTextArea) return;

            let chatMicBtn = chatInputContainer.querySelector('#integratedChatMicBtn');
            if (!chatMicBtn) {
                chatMicBtn = parentDoc.createElement('button');
                chatMicBtn.id = 'integratedChatMicBtn';
                chatMicBtn.type = 'button';
                chatMicBtn.className = 'integrated-chat-mic-btn';
                chatMicBtn.innerHTML = '🎙️';
                chatMicBtn.title = 'Nói câu hỏi bằng Tiếng Việt (Voice Input)';

                chatMicBtn.onclick = function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    startVoiceCapture(chatTextArea, chatMicBtn, true);
                };

                if (submitBtn && submitBtn.parentElement) {
                    submitBtn.parentElement.insertBefore(chatMicBtn, submitBtn);
                } else {
                    chatInputContainer.appendChild(chatMicBtn);
                }
            }

            function checkChatVisibility() {
                if (!chatMicBtn) return;
                if (chatMicBtn.classList.contains('recording')) {
                    chatMicBtn.style.display = 'inline-flex';
                    return;
                }
                const hasText = chatTextArea.value && chatTextArea.value.trim().length > 0;
                chatMicBtn.style.display = hasText ? 'none' : 'inline-flex';
            }

            ['input', 'keyup', 'keydown', 'change', 'paste', 'cut'].forEach(evt => {
                chatTextArea.removeEventListener(evt, checkChatVisibility);
                chatTextArea.addEventListener(evt, checkChatVisibility);
            });

            checkChatVisibility();
        }

        function init() {
            attachHeroSearchMic();
            attachChatInputMic();
        }

        init();

        let count = 0;
        const intervalId = setInterval(() => {
            init();
            count++;
            if (count >= 10) clearInterval(intervalId);
        }, 300);
    })();
    </script>
    </body>
    """
    st.components.v1.html(voice_html, height=0)


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

    # 0.0 KIỂM TRA BÀI TOÁN PHÂN TÍCH PARETO 80/20 (CUMULATIVE PERCENTAGE / TOP CONTRIBUTORS)
    cum_cols = [c for c in df.columns if any(k in str(c).lower() for k in ["cumulative", "tích lũy", "tich_luy"])]
    if cum_cols:
        cum_col = cum_cols[0]
        meas = [c for c in measure_cols if c != cum_col and not any(k in str(c).lower() for k in ["pct", "percent", "tỷ lệ", "tỉ lệ", "%"])]
        if meas:
            m_col = meas[0]
            total_pareto_val = float(pd.to_numeric(df[m_col], errors="coerce").sum())
            max_cum_pct = float(pd.to_numeric(df[cum_col], errors="coerce").max() or 80.0)
            top_row = df.iloc[0]
            top_entity = str(top_row[label_cols[0]]) if label_cols else "N/A"
            top_val = float(top_row[m_col]) if m_col in top_row else 0.0
            avg_per_item = total_pareto_val / total_rows if total_rows > 0 else 0.0

            lbl_col_low = (label_cols[0] if label_cols else "").lower()
            lbl_type = "Sản phẩm" if "product" in lbl_col_low else (
                "Nhân sự" if "person" in lbl_col_low else (
                    "Quốc gia" if any(k in lbl_col_low for k in ["country", "geo"]) else (
                        "Phòng ban" if "dept" in lbl_col_low else "Đối tượng"
                    )
                )
            )

            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.metric("🎯 " + ("Tổng Doanh Thu Nhóm 80%" if not is_en else "Top 80% Total"), f"${total_pareto_val:,.0f}", delta=f"Tích lũy {max_cum_pct:.1f}% tổng số")
            with c2:
                st.metric("📦 " + (f"Số Lượng {lbl_type}" if not is_en else "Key Items Count"), f"{total_rows} {lbl_type}", delta="Chiếm 80% tổng số")
            with c3:
                st.metric("🏆 " + (f"{lbl_type} Dẫn Đầu" if not is_en else "Top Contributor"), top_entity, delta=f"${top_val:,.0f}")
            with c4:
                st.metric("📈 " + ("Đóng Góp Bình Quân" if not is_en else "Avg per Item"), f"${avg_per_item:,.0f}", delta=f"Mỗi {lbl_type.lower()}")

            st.caption(
                f"ℹ️ **Phân tích Nguyên lý Pareto (Quy luật 80/20)**: Danh sách {total_rows} {lbl_type.lower()} chủ lực đóng góp đến {max_cum_pct:.1f}% tổng doanh số toàn hệ thống."
                if not is_en else
                f"ℹ️ **Pareto 80/20 Analysis**: Top {total_rows} key items contributing {max_cum_pct:.1f}% of total revenue."
            )
            st.write("")
            return

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

        # Kiểm tra xem male_cols và female_cols là CỘT TỶ LỆ (%) hay CỘT SỐ LƯỢNG NGƯỜI (Count)
        is_pct_data = any(any(k in str(c).lower() for k in ["pct", "percent", "rate", "tỷ lệ", "tỉ lệ", "%"]) for c in [m_c, f_c])
        if not is_pct_data and s_male.max() <= 100 and s_female.max() <= 100 and abs((s_male + s_female).mean() - 100.0) < 2.5:
            is_pct_data = True

        # Tìm cột Tổng số nhân sự thực tế trong bảng (nếu có)
        total_emp_cols = [
            c for c in df.columns
            if any(k in str(c).lower() for k in ["totalemployees", "total_emp", "headcount", "tổng số", "total", "slngnhnvin", "count"])
            and not any(k in str(c).lower() for k in ["male", "female", "nam", "nữ", "pct", "%"])
            and pd.api.types.is_numeric_dtype(df[c])
        ]

        is_mgr = any(k in (user_query or "").lower() for k in ["manager", "quản lý", "trưởng phòng"]) or any("manager" in str(c).lower() for c in df.columns)
        entity_name = "Quản lý" if is_mgr else ("Nhân sự" if not is_en else "Workforce")

        if is_pct_data:
            if total_emp_cols:
                tot_col = total_emp_cols[0]
                s_tot = pd.to_numeric(df[tot_col], errors="coerce").fillna(0)
                tot_all = float(s_tot.sum())
                s_male_real = (s_male * s_tot / 100.0).round()
                s_female_real = (s_female * s_tot / 100.0).round()
                tot_m = float(s_male_real.sum())
                tot_f = float(s_female_real.sum())
                pct_m = (tot_m / tot_all * 100.0) if tot_all > 0 else 0.0
                pct_f = (tot_f / tot_all * 100.0) if tot_all > 0 else 0.0
            else:
                tot_all = None
                tot_m = None
                tot_f = None
                pct_m = float(s_male.mean())
                pct_f = float(s_female.mean())
        else:
            tot_m = float(s_male.sum())
            tot_f = float(s_female.sum())
            tot_all = tot_m + tot_f
            pct_f = (tot_f / tot_all * 100.0) if tot_all > 0 else 0.0
            pct_m = (tot_m / tot_all * 100.0) if tot_all > 0 else 0.0

        balanced_depts = int((s_male == s_female).sum())
        if balanced_depts == total_rows:
            balance_delta = "Cân bằng tuyệt đối 50-50"
        elif balanced_depts > 0:
            balance_delta = f"{balanced_depts}/{total_rows} {dim_name} đạt 50-50"
        else:
            diff_avg = abs(pct_m - pct_f)
            who_more = "Nam" if pct_m > pct_f else "Nữ"
            balance_delta = f"{who_more} chiếm đa số (+{diff_avg:.1f}%)"

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            if tot_all is not None:
                st.metric("👔 " + (f"Tổng số {entity_name}" if not is_en else f"Total {entity_name}"), f"{int(tot_all):,}", delta=f"{total_rows} {dim_name}")
            else:
                st.metric("🏢 " + ("Quy mô phân tích" if not is_en else "Analyzed Entities"), f"{total_rows} {dim_name}", delta="Cơ cấu theo tỷ lệ")
        with c2:
            delta_f = f"{int(tot_f):,} người" if tot_f is not None else ("Bình quân toàn công ty" if not is_en else "Company Average")
            st.metric("👩 " + ("Tỷ lệ Nữ (Female)" if not is_en else "Female Ratio"), f"{pct_f:.1f}%", delta=delta_f)
        with c3:
            delta_m = f"{int(tot_m):,} người" if tot_m is not None else ("Bình quân toàn công ty" if not is_en else "Company Average")
            st.metric("👨 " + ("Tỷ lệ Nam (Male)" if not is_en else "Male Ratio"), f"{pct_m:.1f}%", delta=delta_m)
        with c4:
            st.metric("⚖️ " + ("Cân bằng 50-50" if not is_en else "Gender Parity"), f"{balanced_depts}/{total_rows} {dim_name}", delta=balance_delta)
            
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

    # KIỂM TRA BÀI TOÁN PHÂN TÍCH CHÊNH LỆCH LƯƠNG NỘI BỘ PHÒNG BAN (SALARY SPREAD / GAP)
    is_salary_spread_analysis = (
        any(any(k in str(c).lower() for k in ["salaryspread", "salary_spread", "chênh lệch lương", "khoảng cách lương"]) for c in df.columns)
        or (any(k in (user_query or "").lower() for k in ["chênh lệch lương", "khoảng cách lương", "phân hóa lương", "salary spread"])
            and any(any(k in str(c).lower() for k in ["maxsalary", "minsalary", "spread", "salary"]) for c in df.columns))
    )
    if is_salary_spread_analysis:
        spread_col = next((c for c in df.columns if any(k in str(c).lower() for k in ["salaryspread", "salary_spread", "chênh lệch lương", "khoảng cách lương"])), None)
        max_s_col = next((c for c in df.columns if any(k in str(c).lower() for k in ["maxsalary", "max_salary", "cao nhất"])), None)
        min_s_col = next((c for c in df.columns if any(k in str(c).lower() for k in ["minsalary", "min_salary", "thấp nhất"])), None)
        dept_col = next((c for c in df.columns if any(k in str(c).lower() for k in ["department", "dept_name", "phòng ban", "phòng"])), label_cols[0] if label_cols else "Department")

        if total_rows == 1:
            row0 = df.iloc[0]
            dept_name = str(row0[dept_col]) if dept_col in df.columns else "N/A"
            s_val = float(row0[spread_col]) if spread_col and spread_col in df.columns else 0.0
            max_val = float(row0[max_s_col]) if max_s_col and max_s_col in df.columns else 0.0
            min_val = float(row0[min_s_col]) if min_s_col and min_s_col in df.columns else 0.0

            ratio_max_min = (max_val / min_val) if min_val > 0 else 1.0

            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.metric(
                    "🏢 " + ("Phòng ban dẫn đầu" if not is_en else "Leading Department"),
                    dept_name,
                    delta="Chênh lệch lớn nhất" if not is_en else "Largest Spread"
                )
            with c2:
                st.metric(
                    "⚖️ " + ("Chênh lệch lương" if not is_en else "Salary Spread"),
                    f"${s_val:,.0f}",
                    delta=f"Gấp {ratio_max_min:.1f} lần mức sàn" if not is_en else f"{ratio_max_min:.1f}x floor salary"
                )
            with c3:
                st.metric(
                    "🏆 " + ("Lương cao nhất" if not is_en else "Max Salary"),
                    f"${max_val:,.0f}",
                    delta=f"Đỉnh phòng {dept_name}" if not is_en else f"Peak at {dept_name}"
                )
            with c4:
                st.metric(
                    "📉 " + ("Lương thấp nhất" if not is_en else "Min Salary"),
                    f"${min_val:,.0f}",
                    delta=f"Sàn phòng {dept_name}" if not is_en else f"Floor at {dept_name}"
                )

            st.caption(
                f"ℹ️ **Phân tích Chênh lệch Lương**: Phòng ban **{dept_name}** có mức chênh lệch lương nội bộ lớn nhất toàn tổ chức là **${s_val:,.0f}** "
                f"(Lương cao nhất **${max_val:,.0f}** gấp **{ratio_max_min:.1f} lần** mức thấp nhất **${min_val:,.0f}**)."
                if not is_en else
                f"ℹ️ **Salary Spread Analysis**: Department **{dept_name}** exhibits the organization's largest internal salary gap of **${s_val:,.0f}** "
                f"(Max salary of **${max_val:,.0f}** is **{ratio_max_min:.1f}x** the base salary of **${min_val:,.0f}**)."
            )
            st.write("")
            return

        elif total_rows == 2 and spread_col:
            s_series = pd.to_numeric(df[spread_col], errors="coerce").fillna(0)
            max_idx = s_series.idxmax()
            min_idx = s_series.idxmin()

            max_d = str(df.loc[max_idx, dept_col])
            max_v = float(s_series.loc[max_idx])
            min_d = str(df.loc[min_idx, dept_col])
            min_v = float(s_series.loc[min_idx])
            gap_ext = max_v - min_v
            gap_pct = (gap_ext / min_v * 100.0) if min_v > 0 else 0.0

            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.metric(
                    "🏆 " + ("Chênh lệch lớn nhất" if not is_en else "Largest Spread"),
                    max_d,
                    delta=f"${max_v:,.0f}"
                )
            with c2:
                st.metric(
                    "📉 " + ("Chênh lệch nhỏ nhất" if not is_en else "Narrowest Spread"),
                    min_d,
                    delta=f"${min_v:,.0f}"
                )
            with c3:
                st.metric(
                    "⚖️ " + ("Khoảng cách cực trị" if not is_en else "Variance Range"),
                    f"${gap_ext:,.0f}",
                    delta=f"+{gap_pct:.1f}% chênh lệch" if not is_en else f"+{gap_pct:.1f}% difference"
                )
            with c4:
                st.metric(
                    "📊 " + ("Chênh lệch bình quân" if not is_en else "Average Spread"),
                    f"${s_series.mean():,.0f}",
                    delta="2 cực trị đối chiếu" if not is_en else "2 extreme benchmarks"
                )

            st.caption(
                f"ℹ️ **Đối chiếu 2 Cực trị Chênh lệch Lương**: Phòng ban **{max_d}** có mức phân hóa lớn nhất (**${max_v:,.0f}**), "
                f"trong khi phòng ban **{min_d}** có độ lệch hẹp nhất (**${min_v:,.0f}**, thấp hơn **${gap_ext:,.0f} (-{gap_pct:.1f}%)**)."
                if not is_en else
                f"ℹ️ **Extreme Benchmark Comparison**: **{max_d}** has the widest internal gap (**${max_v:,.0f}**), "
                f"while **{min_d}** has the narrowest gap (**${min_v:,.0f}**, difference of **${gap_ext:,.0f} (-{gap_pct:.1f}%)**)."
            )
            st.write("")
            return

        elif total_rows > 2 and spread_col:
            s_series = pd.to_numeric(df[spread_col], errors="coerce").fillna(0)
            max_idx = s_series.idxmax()
            min_idx = s_series.idxmin()
            top_d = str(df.loc[max_idx, dept_col])
            top_v = float(s_series.loc[max_idx])
            bot_d = str(df.loc[min_idx, dept_col])
            bot_v = float(s_series.loc[min_idx])
            avg_spread = float(s_series.mean())
            range_val = top_v - bot_v

            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.metric(
                    "🏆 " + ("Chênh lệch lớn nhất" if not is_en else "Largest Spread"),
                    top_d,
                    delta=f"${top_v:,.0f}"
                )
            with c2:
                st.metric(
                    "📉 " + ("Chênh lệch nhỏ nhất" if not is_en else "Narrowest Spread"),
                    bot_d,
                    delta=f"${bot_v:,.0f}"
                )
            with c3:
                st.metric(
                    "📊 " + ("Mức chênh lệch TB" if not is_en else "Avg Spread"),
                    f"${avg_spread:,.0f}",
                    delta=f"{total_rows} phòng ban" if not is_en else f"{total_rows} departments"
                )
            with c4:
                st.metric(
                    "⚖️ " + ("Biên độ phân hóa" if not is_en else "Spread Dispersion"),
                    f"${range_val:,.0f}",
                    delta="Khoảng cách Max - Min" if not is_en else "Max - Min gap"
                )

            st.caption(
                f"ℹ️ **Khảo sát Chênh lệch Lương {total_rows} Phòng Ban**: Phòng ban **{top_d}** có độ phân hóa cao nhất (**${top_v:,.0f}**), "
                f"phòng ban **{bot_d}** có độ đồng đều cao nhất (**${bot_v:,.0f}**); mức chênh lệch trung bình toàn tổ chức là **${avg_spread:,.0f}**."
                if not is_en else
                f"ℹ️ **Salary Spread Overview across {total_rows} Departments**: **{top_d}** shows greatest disparity (**${top_v:,.0f}**), "
                f"**{bot_d}** shows highest parity (**${bot_v:,.0f}**); average organizational spread is **${avg_spread:,.0f}**."
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

        user_asked_pnl = any(k in _uq_low for k in ["lãi", "lỗ", "lãi, lỗ", "lãi lỗ", "lợi nhuận", "profit", "p&l", "pnl", "cost_per_box"])
        if user_asked_pnl:
            p_candidates = [c for c in measure_cols if any(k in str(c).lower() for k in ["lợi nhuận", "profit", "lãi"]) and not any(k in str(c).lower() for k in ["margin", "tỷ suất", "tỉ suất", "%"])]
            if p_candidates:
                m_col = p_candidates[0]
            elif any(k in _uq_low for k in ["tỷ suất", "tỉ suất", "margin", "%"]):
                m_candidates = [c for c in measure_cols if any(k in str(c).lower() for k in ["margin", "tỷ suất", "tỉ suất", "%"])]
                m_col = m_candidates[0] if m_candidates else (eff_like_cols[0] if eff_like_cols else measure_cols[0])
            elif eff_like_cols:
                m_col = eff_like_cols[0]
            else:
                m_col = measure_cols[0]
        elif user_asked_efficiency and eff_like_cols:
            if any(k in _uq_low for k in ["tỷ suất", "tỉ suất", "margin", "%"]):
                m_candidates = [c for c in eff_like_cols if any(k in str(c).lower() for k in ["margin", "tỷ suất", "tỉ suất"])]
                m_col = m_candidates[0] if m_candidates else eff_like_cols[0]
            elif any(k in _uq_low for k in ["mỗi hộp", "per box", "hộp", "thùng"]):
                m_candidates = [c for c in eff_like_cols if any(k in str(c).lower() for k in ["perbox", "per_box"])]
                m_col = m_candidates[0] if m_candidates else eff_like_cols[0]
            else:
                m_col = eff_like_cols[0]
        elif any(k in _uq_low for k in ["tăng lương", "lần tăng", "số lần", "được tăng"]):
            raises_candidates = [c for c in measure_cols if any(k in str(c).lower() for k in ["raisecount", "raise_count", "numberofincreases", "salaryincreases", "salary_increases", "lần tăng", "số lần", "raises", "num_raises"])]
            if raises_candidates:
                m_col = raises_candidates[0]
            else:
                count_like_cols = [c for c in measure_cols if not any(k in str(c).lower() for k in ["percent", "percentage", "pct", "tỷ lệ", "phan_tram", "rate", "ratio"])]
                total_like_cols = [c for c in count_like_cols if any(k in str(c).lower() for k in ["total", "tổng", "count_all", "all"])]
                m_col = total_like_cols[0] if total_like_cols else (count_like_cols[0] if count_like_cols else measure_cols[0])
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
            if any(k in m_low for k in ["lợi nhuận", "profit", "net profit", "netprofit", "lãi"]) and not any(k in m_low for k in ["margin", "tỷ suất", "tỉ suất"]):
                m_clean = "Lợi Nhuận"
            elif any(k in m_low for k in ["chi phí", "cost", "tổng chi phí", "giá vốn", "cogs"]):
                m_clean = "Tổng Chi Phí"
            elif any(k in m_low for k in ["totalsalarybudget", "total salary budget", "total_salary_budget", "salarybudget", "salary_budget", "quỹ lương"]):
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
            elif any(k in m_low for k in ["newtitleappointments", "new title appointments", "new_title_appointments", "titleappointments", "title appointments", "title_appointments", "titleassignments", "title assignments", "bổ nhiệm", "chức danh mới", "appointedemployees", "appointed employees"]):
                m_clean = "Số Lượng Bổ Nhiệm Chức Danh Mới"
            elif any(k in m_low for k in ["headcount", "head count", "totalemployees", "total employees", "emp count", "empcount", "employee count", "employeecount", "số lượng nhân sự", "quy mô nhân sự", "số lượng nhân viên", "slngnhnvin", "soluongnhanvien"]):
                m_clean = "Số Lượng Nhân Viên"
            elif any(k in m_low for k in ["totalmanagers", "total managers", "quản lý"]):
                m_clean = "Số Lượng Quản Lý"
            elif any(k in m_low for k in ["years as manager", "yearsasmanager", "manager tenure", "managertenure", "manager years", "manageryears"]):
                m_clean = "Thâm Niên Quản Lý (Năm)"
            elif any(k in m_low for k in ["yearsofservice", "years of service", "thâm niên", "tenure"]):
                m_clean = "Thâm Niên (Năm)"
            elif any(k in m_low for k in ["boxes", "boxessold", "totalboxessold", "total_boxes", "hộp", "thùng"]):
                m_clean = "Tổng Số Hộp Bán Ra"
            elif any(k in m_low for k in ["raisecount", "raise count", "numberofincreases", "salaryincreases", "salary increases", "lần tăng", "số lần", "num raises"]):
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
        if is_comparison_query and total_rows == 2:
            scope_suffix = " (2 đơn vị)" if not is_en else " (2 entities)"
        else:
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
            _is_raises_measure = any(k in _m_col_lower for k in [
                "raisecount", "raise_count", "numberofincreases", "salaryincreases", "salary_increases",
                "lần tăng", "số lần", "raises", "num_raises",
            ])
            _is_appointment_measure = any(k in _m_col_lower for k in [
                "newtitleappointments", "new_title_appointments", "titleappointments", "title_appointments",
                "titleassignments", "title_assignments", "appointedemployees", "appointed_employees",
                "bổ nhiệm", "chức danh mới",
            ])
            _year_unit = " Năm" if _is_years_measure else (
                (" Lần" if not is_en else " times") if _is_raises_measure else (
                    (" Lượt" if not is_en else " turns") if _is_appointment_measure else ""
                )
            )

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
            _time_long_keywords = ["year", "thang", "tháng", "month", "quarter", "date", "thời gian", "thoi gian", "ngày"]
            # Từ khoá thời gian ngắn (cần exact match hoặc word-boundary để tránh false positive)
            _time_exact_keywords = {"nam", "năm", "quy", "quý"}
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
                n_periods = dim_vals.nunique()
                period_display = f"{n_periods} {dim_unit}" if (n_periods < total_rows and n_periods > 0) else f"{total_rows} {dim_unit}"
                with col1:
                    st.metric("📅 " + ("Giai đoạn theo dõi" if not is_en else "Tracking Period"), f"{period_display}" + (f" ({min_dim} – {max_dim})" if min_dim != max_dim else ""))
                with col2:
                    st.metric("📈 " + ("Mức trung bình chuẩn" if not is_en else "Benchmark Average"), fmt_avg, help=_fmt_kpi_val_full(avg_val))
                time_c = None
                for c in df.columns:
                    if c != m_col and any(k in str(c).lower() for k in ["tháng", "thang", "month", "năm", "nam", "year", "quý", "quy", "quarter", "ngày", "date"]):
                        time_c = c
                        break

                entity_col = None
                for c in df.columns:
                    if c != m_col and c != time_c and not pd.api.types.is_numeric_dtype(df[c]):
                        entity_col = c
                        break

                if time_c and entity_col and max_idx in df.index:
                    ent_p = str(df.loc[max_idx, entity_col]).strip()
                    t_p = str(df.loc[max_idx, time_c]).strip()
                    p_disp = f"{ent_p} - {t_p}" if ent_p != t_p else t_p
                else:
                    p_str = str(peak_label).strip()
                    if p_str.lower().startswith(dim_unit.lower()) or len(p_str) == 4 or "-" in p_str:
                        p_disp = p_str
                    else:
                        p_disp = f"{dim_unit} {p_str}"

                if time_c and entity_col and min_idx in df.index:
                    ent_m = str(df.loc[min_idx, entity_col]).strip()
                    t_m = str(df.loc[min_idx, time_c]).strip()
                    m_disp = f"{ent_m} - {t_m}" if ent_m != t_m else t_m
                else:
                    m_str = str(min_label).strip()
                    if m_str.lower().startswith(dim_unit.lower()) or len(m_str) == 4 or "-" in m_str:
                        m_disp = m_str
                    else:
                        m_disp = f"{dim_unit} {m_str}"

                with col3:
                    full_p = _fmt_kpi_val_full(peak_val) + _year_unit
                    delta_p = full_p if fmt_peak != full_p else None
                    st.metric(f"🏆 " + (f"Đỉnh cao nhất ({p_disp})" if not is_en else f"Peak ({p_disp})"), fmt_peak, delta=delta_p)
                with col4:
                    full_m = _fmt_kpi_val_full(min_val) + _year_unit
                    delta_m = full_m if fmt_min != full_m else None
                    st.metric(f"📉 " + (f"Thấp nhất ({m_disp})" if not is_en else f"Lowest ({m_disp})"), fmt_min, delta=delta_m)

                # Kiểm tra năm 2002 có bị sụt giảm tự nhiên do dữ liệu ghi nhận 8 tháng không
                if any(str(v) == "2002" for v in dim_vals):
                    try:
                        row_2002 = df[df[dim_c].astype(str) == "2002"]
                        row_2001 = df[df[dim_c].astype(str) == "2001"]
                        if not row_2002.empty and not row_2001.empty:
                            v02 = float(row_2002[m_col].iloc[0])
                            v01 = float(row_2001[m_col].iloc[0])
                            if v01 > 0 and v02 < v01 * 0.8:
                                if _is_appointment_measure:
                                    note_msg = (
                                        "ℹ️ **Lưu ý dữ liệu**: Năm 2002 cơ sở dữ liệu chỉ ghi nhận đến tháng 08/2002 (8 tháng) "
                                        "nên số lượt bổ nhiệm ghi nhận thấp hơn tự nhiên so với các năm đủ 12 tháng, không phản ánh sự suy thoái vận hành."
                                        if not is_en else
                                        "ℹ️ **Data Note**: Year 2002 records only contain data up to August 2002 (8 months), "
                                        "causing recorded appointments to appear lower than full 12-month years, not an operational decline."
                                    )
                                elif any(k in m_low for k in ["salary", "lương", "budget", "quỹ"]):
                                    note_msg = (
                                        "ℹ️ **Lưu ý dữ liệu tài chính**: Năm 2002 cơ sở dữ liệu chỉ ghi nhận đến tháng 08/2002 (8 tháng) "
                                        "nên tổng quỹ lương bị hụt tự nhiên so với các năm đủ 12 tháng, không phản ánh sự suy thoái kinh doanh."
                                        if not is_en else
                                        "ℹ️ **Financial Data Note**: Year 2002 records only contain data up to August 2002 (8 months), "
                                        "causing an apparent drop compared to full 12-month years, not an actual operational decline."
                                    )
                                else:
                                    note_msg = (
                                        "ℹ️ **Lưu ý dữ liệu**: Năm 2002 cơ sở dữ liệu chỉ ghi nhận đến tháng 08/2002 (8 tháng) "
                                        "nên chỉ số ghi nhận bị hụt tự nhiên so với các năm đủ 12 tháng, không phản ánh sự suy thoái vận hành."
                                        if not is_en else
                                        "ℹ️ **Data Note**: Year 2002 records only contain data up to August 2002 (8 months), "
                                        "causing recorded metrics to appear lower than full 12-month years, not an operational decline."
                                    )
                                st.caption(note_msg)
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
                    elif any(k in _dim_low for k in ["employee", "nhân sự", "nhân viên", "emp", "name", "salesperson"]):
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
                _unassigned_keywords = ["(chưa phân nhóm)", "(chưa xác định)", "(unassigned)", "chưa phân nhóm", "chưa xác định", "unassigned", "(trống)", "none", "n/a", ""]
                _dim_col = label_cols[0] if label_cols else "Department"
                if _dim_col in df.columns:
                    is_unassigned_mask = df[_dim_col].astype(str).str.strip().str.lower().isin(_unassigned_keywords)
                else:
                    is_unassigned_mask = pd.Series([False] * len(df), index=df.index)

                has_unassigned = bool(is_unassigned_mask.any())
                real_rows_count = int((~is_unassigned_mask).sum())
                unassigned_measure_sum = float(valid_vals[is_unassigned_mask].sum()) if has_unassigned else 0

                total_val = valid_vals.sum()
                fmt_total = _fmt_kpi_val(total_val)

                is_hc_measure = any(k in m_low for k in ["employee", "headcount", "nhân sự", "nhân viên", "hires", "tuyển dụng", "quy mô", "slngnhnvin", "totalemployees"]) and not is_currency
                if is_hc_measure:
                    fmt_total = f"{int(total_val):,} Người"
                    dim_first = str(label_cols[0] if label_cols else "").lower()
                    if has_unassigned and real_rows_count > 0:
                        real_team_vals = valid_vals[~is_unassigned_mask]
                        real_avg = float(real_team_vals.mean()) if not real_team_vals.empty else avg_val
                        fmt_avg = f"{real_avg:.1f} Người/Đội" if any(k in dim_first for k in ["team", "đội"]) else f"{real_avg:.1f} Người"
                    else:
                        fmt_avg = f"{avg_val:.1f} Người/Đội" if any(k in dim_first for k in ["team", "đội"]) else f"{avg_val:.1f} Người"
                    peak_delta_val = f"{int(peak_val):,} Người"
                elif _is_raises_measure:
                    _u_raise = " Lần" if not is_en else " times"
                    fmt_total = f"{int(total_val):,}{_u_raise}"
                    fmt_avg = f"{avg_val:.1f}{_u_raise}"
                    peak_delta_val = f"{int(peak_val):,}{_u_raise}"
                else:
                    if has_unassigned and real_rows_count > 0:
                        real_vals = valid_vals[~is_unassigned_mask]
                        real_avg = float(real_vals.mean()) if not real_vals.empty else avg_val
                        fmt_avg = _fmt_kpi_val(real_avg)
                    peak_delta_val = f"{fmt_peak}"

                # Nếu đối tượng dẫn đầu vô tình là nhóm Chưa phân bổ, ưu tiên lấy đối tượng chính thức dẫn đầu
                if has_unassigned and max_idx in is_unassigned_mask.index and is_unassigned_mask.loc[max_idx]:
                    real_valid = valid_vals[~is_unassigned_mask]
                    if not real_valid.empty:
                        real_max_idx = real_valid.idxmax()
                        peak_val = df.loc[real_max_idx, m_col]
                        peak_label = str(label_series.loc[real_max_idx]) if (label_series is not None and real_max_idx in label_series.index) else str(df.loc[real_max_idx, label_cols[0]])
                        if is_hc_measure:
                            peak_delta_val = f"{int(peak_val):,} Người"
                        else:
                            peak_delta_val = _fmt_kpi_val(peak_val)

                # Tránh lặp từ "Tổng Total ..."
                prefix = "Tổng " if not is_en else "Total "
                if m_clean.lower().startswith("total ") or m_clean.lower().startswith("tổng ") or m_clean.lower().startswith("số lượng "):
                    clean_card_title = m_clean
                else:
                    clean_card_title = prefix + m_clean

                # Chọn icon phù hợp theo ngữ cảnh dữ liệu
                if is_currency:
                    card_icon = "💰 "
                elif any(k in m_low for k in ["bổ nhiệm", "chức danh", "appointment", "assignment"]):
                    card_icon = "🎖️ "
                elif any(k in m_low for k in ["manager", "quản lý", "trưởng phòng"]):
                    card_icon = "👔 "
                elif any(k in m_low for k in ["employee", "headcount", "nhân sự", "nhân viên", "hires", "tuyển dụng", "quy mô", "slngnhnvin"]):
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
                        st.metric(f"🏆 " + ("Đỉnh cao nhất" if not is_en else "Peak Record"), peak_label, delta=peak_delta_val)
                else:
                    with col1:
                        display_rows_count = real_rows_count if (has_unassigned and real_rows_count > 0) else total_rows
                        card1_delta = f"+ {int(unassigned_measure_sum):,} chưa phân đội" if (is_hc_measure and unassigned_measure_sum > 0) else (f"+ {int(unassigned_measure_sum):,} chưa phân loại" if (has_unassigned and unassigned_measure_sum > 0) else None)

                        if is_top_query and total_rows <= 30:
                            _dim_low = str(_dim_col).lower()
                            if any(k in _dim_low for k in ["dept", "phòng", "department"]):
                                _entity_top = " Phòng ban" if not is_en else " Departments"
                            elif any(k in _dim_low for k in ["team", "đội ngũ", "đội"]):
                                _entity_top = " Đội ngũ" if not is_en else " Teams"
                            elif any(k in _dim_low for k in ["country", "geo", "quốc gia", "thị trường"]):
                                _entity_top = " Quốc gia" if not is_en else " Countries"
                            elif any(k in _dim_low for k in ["product", "sản phẩm"]):
                                _entity_top = " Sản phẩm" if not is_en else " Products"
                            elif any(k in _dim_low for k in ["title", "chức danh", "job"]):
                                _entity_top = " Chức danh" if not is_en else " Job Titles"
                            elif any(k in _dim_low for k in ["manager", "quản lý"]):
                                _entity_top = " Quản lý" if not is_en else " Managers"
                            elif any(k in _dim_low for k in ["employee", "nhân sự", "nhân viên", "name", "tên", "salesperson"]):
                                _entity_top = " Nhân sự" if not is_en else " Employees"
                            else:
                                _entity_top = ""
                            if is_comparison_query and total_rows == 2:
                                st.metric("⚖️ " + ("So sánh Đối chiếu" if not is_en else "Min-Max Comparison"), f"2{_entity_top}")
                            else:
                                st.metric("🏆 " + ("Xếp hạng" if not is_en else "Ranking"), f"Top {display_rows_count}{_entity_top}")
                        else:
                            _dim_low = str(_dim_col).lower()
                            if any(k in _dim_low for k in ["dept", "phòng", "department"]):
                                _card1_title = "🏢 " + ("Số phòng ban" if not is_en else "Departments")
                                _card1_val = f"{display_rows_count} Phòng"
                            elif any(k in _dim_low for k in ["team", "đội ngũ", "đội"]):
                                _card1_title = "👥 " + ("Số đội ngũ" if not is_en else "Teams")
                                _card1_val = f"{display_rows_count} Đội ngũ"
                            elif any(k in _dim_low for k in ["country", "geo", "quốc gia", "thị trường"]):
                                _card1_title = "🌍 " + ("Số thị trường" if not is_en else "Markets")
                                _card1_val = f"{display_rows_count} Quốc gia"
                            elif any(k in _dim_low for k in ["product", "sản phẩm"]):
                                _card1_title = "🍫 " + ("Số sản phẩm" if not is_en else "Products")
                                _card1_val = f"{display_rows_count} Sản phẩm"
                            elif any(k in _dim_low for k in ["title", "chức danh", "job"]):
                                _card1_title = "💼 " + ("Số chức danh" if not is_en else "Job Titles")
                                _card1_val = f"{display_rows_count} Chức danh"
                            elif any(k in _dim_low for k in ["year", "năm", "hireyear"]):
                                _card1_title = "📅 " + ("Giai đoạn" if not is_en else "Period")
                                _card1_val = f"{display_rows_count} Năm"
                            elif any(k in _dim_low for k in ["name", "tên", "employee", "nhân viên", "nhân sự", "salesperson"]):
                                _card1_title = "👥 " + ("Số nhân sự" if not is_en else "Employees")
                                _card1_val = f"{display_rows_count:,} Người"
                            else:
                                _card1_title = "📋 " + ("Tổng số đối tượng" if not is_en else "Total Entities")
                                _card1_val = f"{display_rows_count:,}"
                            st.metric(_card1_title, _card1_val, delta=card1_delta)
                    with col2:
                        st.metric(f"{card_icon}{clean_card_title}{scope_suffix}", fmt_total)
                    with col3:
                        if is_comparison_query and total_rows == 2:
                            peak_title = "🥇 " + ("Lớn nhất" if not is_en else "Largest")
                            st.metric(peak_title, peak_label, delta=peak_delta_val)
                        else:
                            st.metric(f"📈 " + ("Trung bình" if not is_en else "Average"), fmt_avg)
                    with col4:
                        if is_comparison_query and total_rows == 2:
                            min_delta_val = f"{int(min_val):,} Người" if is_hc_measure else f"{_fmt_kpi_val(min_val)}"
                            min_title = "📉 " + ("Nhỏ nhất" if not is_en else "Smallest")
                            st.metric(min_title, min_label, delta=min_delta_val)
                        else:
                            peak_title = "🏆 " + ("Đội lớn nhất" if (is_hc_measure and any(k in str(label_cols[0] if label_cols else "").lower() for k in ["team", "đội"])) else ("Đỉnh cao nhất" if not is_en else "Peak Record"))
                            st.metric(peak_title, peak_label, delta=peak_delta_val)

                    if has_unassigned and unassigned_measure_sum > 0:
                        pct_unassigned = (unassigned_measure_sum / total_val * 100.0) if total_val > 0 else 0
                        st.caption(
                            f"ℹ️ **Lưu ý nhân sự**: Cơ sở dữ liệu ghi nhận có {int(unassigned_measure_sum):,} nhân sự ({pct_unassigned:.1f}%) "
                            f"chưa được gán Đội ngũ (trường `Team` đang để trống trong bảng `people`)."
                            if not is_en else
                            f"ℹ️ **HR Note**: Database records show {int(unassigned_measure_sum):,} employees ({pct_unassigned:.1f}%) "
                            f"currently unassigned to any business Team (field `Team` is blank in `people` table)."
                        )
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
            unassigned_label = "(Unassigned)" if is_en else "(Chưa xác định)"
            cleaned_df[col] = cleaned_df[col].apply(
                lambda val: unassigned_label if pd.isna(val) or (isinstance(val, str) and not val.strip()) else val
            )
    df = cleaned_df
    # 3. Thẻ Tóm tắt Chỉ số Điều hành (Executive KPI Summary Cards)
    user_query = result.get("query", "")
    render_executive_kpi_cards(df, is_en=is_en, user_query=user_query)

    # 4. Biểu đồ Trực quan Trung tâm (Visual-First Hero Chart)
    chart_options = (
        ["Automatic", "Bar (Vertical)", "Bar (Horizontal Ranking)", "Line", "Pie", "Area", "Scatter"]
        if is_en else
        ["Tự động", "Bar (Cột đứng)", "Bar (Cột ngang xếp hạng)", "Line (Đường)", "Pie (Tròn)", "Area (Miền)", "Scatter (Phân tán)"]
    )
    c_ch_space, c_ch_sel = st.columns([4, 1.3])
    with c_ch_sel:
        chart_override = st.selectbox(
            "Loại biểu đồ" if not is_en else "Chart Type",
            chart_options,
            key=f"charttype_{turn_id}",
            label_visibility="collapsed"
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

    anomalies_info = result.get("anomalies_info") or analyze_data_anomalies(df)
    has_anomaly = anomalies_info.get("has_anomaly", False)

    if chart_fig and has_anomaly:
        n_findings = len(anomalies_info.get("findings", []))
        caption_anom = f"🚨 **Detected {n_findings} statistical anomalies/trends**. See details in **'Insights & Analysis'** tab." if is_en else f"🚨 **Phát hiện {n_findings} điểm/xu hướng bất thường** trên dữ liệu. Xem chi tiết tại tab **'Insight & Hành động'**."
        st.caption(caption_anom)

    # 5. Cụm Tab Phân loại Thông tin (Progressive Disclosure Tabs)
    tab_data_label = "📋 Bảng số liệu & Báo cáo" if not is_en else "📋 Data Table & Reports"
    tab_insight_label = "💡 Insight & Hành động 🚨" if (has_anomaly and not is_en) else ("💡 Insight & Phân tích" if not is_en else ("💡 Insights & Anomalies 🚨" if has_anomaly else "💡 Insights & Analysis"))
    tab_forecast_label = "🔮 Dự báo xu hướng" if not is_en else "🔮 Forecast"
    tab_sql_label = "🛠️ Câu lệnh SQL & Debug" if not is_en else "🛠️ SQL Query & Logs"

    tab_data, tab_insight, tab_forecast, tab_sql = st.tabs([tab_data_label, tab_insight_label, tab_forecast_label, tab_sql_label])

    # -----------------------------------------------------
    # TAB 1: BẢNG SỐ LIỆU & XUẤT BÁO CÁO (EXCEL, PDF, TELEGRAM, EMAIL)
    # -----------------------------------------------------
    with tab_data:
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
                is_num = pd.api.types.is_numeric_dtype(display_df[col])

                is_year_or_id = (is_id_like(col) or (
                    (any(k in c_low for k in ["year", "năm", "hireyear", "tháng", "month"]) or c_low in ["nam", "năm"])
                    and not any(k in c_low for k in ["salary", "lương", "cost", "revenue", "amount", "profit", "budget", "tiền"])
                )) and not any(k in c_low for k in ["name", "tên", "department", "phòng", "title", "chức"])
                if is_year_or_id:
                    if is_num:
                        column_config[col] = st.column_config.NumberColumn(col_label, format="%d")
                    else:
                        column_config[col] = st.column_config.Column(col_label)
                elif any(k in c_low for k in ["pct", "percent", "percentage", "tỷ lệ", "tỉ lệ", "tỷ suất", "tỉ suất", "tỉ trọng", "tỷ trọng", "phần trăm", "share", "rate", "ratio", "margin", "biên", "%"]):
                    if is_num:
                        column_config[col] = st.column_config.NumberColumn(col_label, format="%.2f%%")
                    else:
                        column_config[col] = st.column_config.Column(col_label)
                elif any(k in c_low for k in [
                    "salary", "lương", "thu nhập", "budget", "quỹ", "tiền", "cost", "revenue", "chi phí", "sales",
                    "amount", "profit", "ordervalue", "doanh thu", "doanh số", "doanh", "lợi nhuận", "lãi", "lỗ",
                    "giá vốn", "cogs", "$"
                ]):
                    if is_num:
                        has_dec = display_df[col].dropna().apply(lambda x: float(x) != int(float(x)) if pd.notna(x) else False).any() if not display_df[col].dropna().empty else False
                        column_config[col] = st.column_config.NumberColumn(
                            col_label,
                            format="$%,.2f" if has_dec else "$%,.0f"
                        )
                    else:
                        column_config[col] = st.column_config.Column(col_label)
                elif any(k in c_low for k in ["raisecount", "raise_count", "numberofincreases", "salaryincreases", "salary_increases", "lần tăng", "số lần"]):
                    if is_num:
                        column_config[col] = st.column_config.NumberColumn(col_label, format="%d lần" if not is_en else "%d times")
                    else:
                        column_config[col] = st.column_config.Column(col_label)
                elif any(k in c_low for k in ["headcount", "hires", "count", "số lượng", "tổng số", "boxes", "thùng", "hộp", "nhân viên", "nhân sự", "slngnhnvin"]):
                    if is_num:
                        column_config[col] = st.column_config.NumberColumn(col_label, format="%,d")
                    else:
                        column_config[col] = st.column_config.Column(col_label)
                elif is_num:
                    has_dec = display_df[col].dropna().apply(lambda x: float(x) != int(float(x)) if pd.notna(x) else False).any() if not display_df[col].dropna().empty else False
                    column_config[col] = st.column_config.NumberColumn(
                        col_label,
                        format="%,.2f" if has_dec else "%,d"
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

        exp_share_title = "📤 Chia sẻ Báo cáo qua Telegram Bot & Email SMTP" if not is_en else "📤 Share Report (Telegram Bot & Email)"
        with st.expander(exp_share_title, expanded=False):
            saved = load_saved_config()
            tab_tg, tab_em = st.tabs(["🚀 Telegram Bot", "📧 Email SMTP"])

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
                        st.error("Vui lòng nhập Bot Token và Chat ID.")
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

    # -----------------------------------------------------
    # TAB 2: INSIGHT & HÀNH ĐỘNG
    # -----------------------------------------------------
    with tab_insight:
        title_insight_header = "💡 Executive Business Insight & Anomaly Report" if is_en else "💡 Báo cáo Phân tích Insight & Phát hiện Bất thường"
        st.subheader(title_insight_header)

        stats = anomalies_info.get("summary_stats", {})
        if stats:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total Rows" if is_en else "Tổng số dòng", f"{stats.get('count', 0):,}")
            c2.metric("Mean" if is_en else "Trung bình (Mean)", f"{stats.get('mean', 0):,.2f}")
            c3.metric("Max" if is_en else "Lớn nhất (Max)", f"{stats.get('max', 0):,.2f}")
            c4.metric("Min" if is_en else "Nhỏ nhất (Min)", f"{stats.get('min', 0):,.2f}")

        if has_anomaly:
            st.markdown("#### 🚨 Statistical Anomaly Findings:" if is_en else "#### 🚨 Các phát hiện bất thường từ thuật toán:")
            for f in anomalies_info.get("findings", []):
                st.warning(f"• {f.get('message')}")
        else:
            st.success("✅ No extreme anomalies or spikes detected in this dataset." if is_en else "✅ Thuật toán không phát hiện điểm đột biến hoặc biến động cực đoan bất thường trong tập dữ liệu này.")

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

    # -----------------------------------------------------
    # TAB 3: DỰ BÁO XU HƯỚNG
    # -----------------------------------------------------
    with tab_forecast:
        caption_forecast = (
            "🧮 Forecast uses deterministic linear regression — mathematically verifiable. Available when dataset contains time and numerical measure columns."
            if is_en else
            "🧮 Dự báo bằng mô hình hồi quy tuyến tính xác định (Deterministic Linear Regression) — có thể kiểm chứng toán học 100%. Áp dụng khi dữ liệu có cột thời gian và số đo."
        )
        st.caption(caption_forecast)

        periods = st.slider(
            "Forecast Horizon (periods)" if is_en else "Số kỳ dự báo tương lai",
            1, 12, st.session_state.get("forecast_periods", 3),
            key=f"periods_{turn_id}"
        )
        fig_forecast, method = forecast_series(df, periods=periods)
        if fig_forecast is None:
            st.info(method)
        else:
            st.plotly_chart(fig_forecast, width='stretch', key=f"forecast_{turn_id}")
            st.caption(f"Phương pháp: {method}" if not is_en else f"Method: {method}")

    # -----------------------------------------------------
    # TAB 4: CÂU LỆNH SQL & DEBUG LOGS
    # -----------------------------------------------------
    with tab_sql:
        if sql_query:
            st.markdown("#### ⚡ " + ("Câu Lệnh SQL Đã Thực Thi" if not is_en else "Executed SQL Query"))
            st.code(sql_query, language="sql")

            st.markdown("#### ⚡ " + ("Chỉnh sửa & Chạy lại SQL Trực tiếp" if not is_en else "Live SQL Editor & Playground"))
            st.caption(
                "Bạn có thể sửa câu lệnh SQL (đổi điều kiện WHERE, GROUP BY, ORDER BY, LIMIT...) và bấm nút bên dưới để cập nhật kết quả tức thì mà không cần gọi lại AI."
                if not is_en else
                "You can edit the SQL query below and re-run it directly to update results instantly without calling AI."
            )
            edited_sql = st.text_area(
                "SQL Editor",
                value=sql_query,
                height=120,
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

    # 6. Gợi ý Câu hỏi Phân tích Tiếp nối (Follow-up Question Suggestions)
    followups = result.get("followups", [])
    if not followups and df is not None and not df.empty:
        try:
            from src.llm.agent import generate_grounded_fallback_followups
            schema_ctx = st.session_state.get("schema_context", "")
            followups = generate_grounded_fallback_followups(df, schema_context=schema_ctx, current_query=user_query, lang=lang)
            result["followups"] = followups
        except Exception:
            pass

    if followups:
        st.markdown("<div style='margin-top: 20px; margin-bottom: 8px;'>", unsafe_allow_html=True)
        header_fup = "💡 **Gợi ý phân tích tiếp theo (Nhấp để chạy ngay):**" if not is_en else "💡 **Suggested Follow-up Questions (Click to run):**"
        st.markdown(header_fup)

        cols = st.columns(min(len(followups), 3))
        for idx, (col_f, q_text) in enumerate(zip(cols, followups[:3])):
            clean_q = sanitize_followup_question(q_text)
            if not clean_q:
                continue
            def _on_fup_click(q_target=clean_q):
                st.session_state["pending_prompt"] = q_target

            with col_f:
                help_text = f"Chạy tiếp: \"{clean_q}\"" if not is_en else f"Run query: \"{clean_q}\""
                st.button(
                    f"👉 {clean_q}",
                    key=f"btn_fup_{turn_id}_{idx}_{abs(hash(clean_q)) % 1000000}",
                    use_container_width=True,
                    help=help_text,
                    on_click=_on_fup_click
                )
        st.markdown("</div>", unsafe_allow_html=True)


