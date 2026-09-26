"""
Veraxus Internationalization (i18n) & Localization System.
Supports seamless, instant, reactive switching between Vietnamese (vi) and English (en).
"""

import streamlit as st
from typing import Any, Dict

# =========================================================================
# TRANSLATION DICTIONARIES (VI & EN)
# =========================================================================
TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "vi": {
        # --- Common & Global ---
        "app_title": "Veraxus - Trí tuệ Doanh nghiệp",
        "app_subtitle": "Trợ lý Dữ liệu Kinh doanh Thông minh • Trực quan, Tức thì & Tuyệt đối Tin cậy",
        "lang_vi": "Tiếng Việt",
        "lang_en": "English",
        "switch_lang": "Ngôn ngữ / Language",
        "loading": "Đang tải dữ liệu...",
        "error": "Lỗi",
        "success": "Thành công",
        "warning": "Cảnh báo",
        "confirm": "Xác nhận",
        "cancel": "Hủy bỏ",
        "close": "Đóng",
        "save": "Lưu",
        "delete": "Xóa",
        "clear": "Làm mới",
        "search": "Tìm kiếm",
        "view": "Xem",
        "back": "Quay lại",
        "back_to_chat": "← Quay lại Trợ lý Chat",
        "apply": "Áp dụng",
        "records": "bản ghi",
        "columns": "cột",
        "fields": "trường dữ liệu",
        "download": "Tải về",

        # --- Header & Hero Section ---
        "hero_badge_ready": "Doanh Nghiệp • Sẵn Sàng Phân Tích",
        "hero_badge_connecting": "Đang Kết Nối CSDL...",
        "hero_badge_demo": "Chế Độ Trải Nghiệm Demo",
        "hero_title": "VERAXUS",
        "hero_input_placeholder": "Hỏi Veraxus... (vd: Doanh số theo quý, lương bình quân theo phòng ban)",
        "hero_btn_analyze": "Phân tích ➔",
        "hero_pill_security": "Bảo mật On-Premise 100%",
        "hero_pill_realtime": "Kết nối Real-Time CSDL",
        "hero_pill_instant": "Phân tích tức thì <0.5s",
        "voice_listening": "Đang nghe... Hãy nói câu hỏi của bạn",
        "voice_btn_tooltip": "Nhập liệu bằng giọng nói",

        # --- Starter Cards & Framework Categories ---
        "starter_framework_title": "Khung Phân Tích & Truy Vấn Điều Hành:",
        "starter_tab_trends": "Xu hướng & Thời gian",
        "starter_tab_ranking": "Xếp hạng & Phân khúc",
        "starter_tab_perf": "Hiệu suất & Cơ cấu",
        "starter_btn_explore": "Khám phá ➔",

        # --- Sidebar ---
        "sidebar_connected_engine": "CSDL Doanh Nghiệp • Local Engine",
        "sidebar_demo_engine": "CSDL Demo • SQLite Engine",
        "sidebar_disconnected": "Chưa Kết Nối CSDL",
        "sidebar_btn_new_chat": "+ Chat Mới",
        "sidebar_btn_settings": "Thiết lập ⚙",
        "sidebar_btn_hr_dashboard": "❖ HR & Payroll Dashboard",
        "sidebar_btn_sales_dashboard": "❖ Sales Executive Dashboard",
        "sidebar_btn_crm_dashboard": "❖ CRM Executive Dashboard",
        "sidebar_btn_evolution": "🧬 Vòng Lặp Tiến Hóa",
        "sidebar_schema_title": "Danh Mục Bảng CSDL",
        "sidebar_schema_table_info": "Bảng `{table}`: {count} trường dữ liệu",
        "sidebar_schema_open_table": "Mở bảng `{table}` →",
        "sidebar_history_title": "Lịch Sử Truy Vấn",
        "sidebar_history_empty": "Chưa có truy vấn nào. Hãy nhập câu hỏi đầu tiên ở khung tìm kiếm!",
        "sidebar_history_clear_btn": "Xóa lịch sử trò chuyện",
        "sidebar_history_clear_confirm": "Đã dọn dẹp toàn bộ lịch sử trò chuyện!",
        "sidebar_history_click_hint": "Bấm vào câu hỏi để xem lại kết quả:",

        # --- Chat & Results Components ---
        "exec_summary_title": "TÓM TẮT ĐIỀU HÀNH",
        "exec_time_label": "Thời gian thực thi:",
        "sql_query_toggle": "Xem câu lệnh SQL truy vấn",
        "sql_query_copy": "Sao chép SQL",
        "sql_query_copied": "Đã sao chép SQL!",
        "sql_dialect_label": "Hệ quản trị CSDL:",
        "table_tab_label": "📋 Bảng số liệu & Báo cáo",
        "chart_tab_bar": "📊 Biểu đồ Cột",
        "chart_tab_line": "📈 Biểu đồ Đường",
        "chart_tab_donut": "🍩 Biểu đồ Cơ cấu",
        "chart_tab_scatter": "🔵 Biểu đồ Phân tán",
        "chart_tab_kpi": "📌 Chỉ số KPI",
        "insights_title": "💡 Insight & Phân tích",
        "forecast_tab_title": "🔮 Dự báo xu hướng",
        "agent_team_tab_title": "🏛 Hội đồng 5 Agent & SQL",
        "insights_highlights": "Điểm sáng & Cơ hội tăng trưởng",
        "insights_risks": "Cảnh báo rủi ro & Điểm nghẽn",
        "insights_actions": "Đề xuất hành động chiến lược",
        "follow_up_title": "Gợi ý câu hỏi đào sâu tiếp theo:",
        "export_excel": "📥 Xuất Excel (.xlsx)",
        "export_pdf": "📄 Xuất Báo cáo PDF",
        "export_png": "🖼️ Tải Biểu đồ PNG",
        "export_csv": "📥 Tải CSV",
        "share_report_btn": "Chia sẻ Báo cáo qua Telegram Bot & Email",
        "export_report_title": "BÁO CÁO PHÂN TÍCH DỮ LIỆU ĐIỀU HÀNH",
        "thinking_step_1": "Phân tích câu hỏi & Lập kế hoạch truy vấn...",
        "thinking_step_2": "Xác định bảng dữ liệu & Trích xuất logic nghiệp vụ...",
        "thinking_step_3": "Tạo câu lệnh SQL chuẩn mực & Thực thi an toàn...",
        "thinking_step_4": "Tổng hợp chỉ số KPI & Trực quan hóa dữ liệu...",
        "audit_integrity_passed": "✓ Dữ liệu đã được kiểm chứng tính toàn vẹn (Độ tin cậy 100%)",
        "audit_source_label": "Nguồn: CSDL Doanh Nghiệp",
        "audit_index_optimized": "⚡ Tối ưu Index",

        # --- Settings & Onboarding ---
        "settings_modal_title": "⚙️ CẤU HÌNH HỆ THỐNG & KẾT NỐI",
        "settings_tab_db": "Kết Nối CSDL",
        "settings_tab_ai": "Cấu Hình AI Engine",
        "settings_tab_advanced": "Tùy Chọn Nâng Cao",
        "db_type_label": "Loại Cơ Sở Dữ Liệu",
        "db_host_label": "Máy chủ (Host)",
        "db_port_label": "Cổng (Port)",
        "db_name_label": "Tên Cơ Sở Dữ Liệu (Database)",
        "db_user_label": "Tên người dùng (Username)",
        "db_pass_label": "Mật khẩu (Password)",
        "db_btn_test": "Kiểm tra kết nối",
        "db_btn_save_connect": "Lưu & Kết nối CSDL",
        "ai_provider_label": "Nhà cung cấp Mô hình (Provider)",
        "ai_model_label": "Tên Mô hình (Model Name)",
        "ai_api_key_label": "API Key",
        "ai_btn_save": "Lưu cấu hình AI",
        "adv_auto_insights": "Tự động tạo Phân tích chuyên sâu (AI Insights)",
        "adv_self_check": "Kích hoạt Vòng lặp Tự kiểm tra & Sửa lỗi SQL",
        "adv_cache": "Lưu bộ nhớ đệm truy vấn tức thì (Query Cache)",

        # --- HR & Payroll Dashboard ---
        "hr_dash_title": "👥 HR & Payroll Intelligence Dashboard",
        "hr_dash_badge": "CSDL EMPLOYEES • LIVE SQL",
        "hr_select_layer_label": "Chọn tầng phân tích",
        "hr_btn_copilot": "💬 Trợ Lý Copilot",
        "hr_btn_main_chat": "🔄 Chat Chính",
        "hr_copilot_help": "Mở trợ lý AI Copilot giải đáp tức thì theo ngữ cảnh màn hình này",
        "hr_main_chat_help": "Quay lại giao diện trò chuyện & hỏi tự do với Tác tử AI",
        "hr_layer_overview": "🏠 Trang chủ Tổng quan (Overview)",
        "hr_layer_dept": "🏢 Quản lý Phòng ban (Departments)",
        "hr_layer_emp": "👥 Danh bạ Nhân viên (Directory)",
        "hr_layer_salary": "💰 Phân tích Tiền lương (Salary)",
        "hr_layer_org": "🌳 Cơ cấu Tổ chức (Org Structure)",
        "hr_layer_titles": "🎓 Chức danh & Vị trí (Titles)",
        "hr_layer_managers": "👔 Đội ngũ Quản lý (Managers)",

        # 6 Topic Navigation Cards
        "hr_nav_header": "Chọn Chủ Đề Phân Tích Chuyên Sâu (Khám Phá Theo Layer):",
        "card_dept_title": "Department Management",
        "card_dept_desc": "Danh sách phòng ban, quản lý & quỹ lương chi trả ➔",
        "card_emp_title": "Employee Directory",
        "card_emp_desc": "Danh bạ toàn bộ nhân sự, tra cứu theo ID & chức danh ➔",
        "card_sal_title": "Salary Analysis",
        "card_sal_desc": "Phân bổ mức lương theo phòng ban & Top 10 thu nhập ➔",
        "card_org_title": "Organizational Structure",
        "card_org_desc": "Sơ đồ cơ cấu tổ chức & nhân sự trực tiếp dưới Manager ➔",
        "card_title_title": "Title & Positions",
        "card_title_desc": "Danh mục chức danh & thu nhập bình quân theo vị trí ➔",
        "card_mgr_title": "Department Managers",
        "card_mgr_desc": "Hồ sơ đội ngũ Manager, phòng ban quản lý & nhiệm kỳ ➔",

        # Timeline Slider & Filters
        "timeline_slider_title": "Thanh Trượt Dòng Thời Gian Phân Tích (Timeline Filter Slider)",
        "timeline_period_all": "Toàn bộ lịch sử",
        "timeline_criteria_title": "Tiêu Chí Khớp Dòng Thời Gian Biểu Đồ Trend:",
        "cr_hiring": "👥 Quy mô Tuyển dụng & Giới tính (Hiring & Gender)",
        "cr_salary": "💰 Quỹ lương & Thu nhập Bình quân (Payroll & Avg Salary)",
        "cr_dept_transfer": "🏢 Phân bổ & Điều chuyển phòng ban (Department Staffing)",
        "cr_promotions": "🎓 Bổ nhiệm & Thăng tiến chức danh (Title Appointments)",

        # KPI Summary Cards
        "kpi_overview_header": "Chỉ Số Tổng Hợp Doanh Nghiệp (Executive Overview KPIs):",
        "kpi_total_employees": "Nhân Sự Đang Làm Việc",
        "kpi_sub_total_employees_all": "👥 Nhân sự đang làm việc (Active Headcount)",
        "kpi_sub_total_employees_period": "👥 Nhân sự active trong kỳ ({period})",
        "kpi_total_depts": "Số Department",
        "kpi_sub_total_depts": "🏢 Khối phòng ban hoạt động",
        "kpi_avg_salary": "Mức Lương Bình Quân",
        "kpi_sub_avg_salary_all": "💵 Quỹ lương hiện hành/người",
        "kpi_sub_avg_salary_period": "💵 Lương bình quân ({period})",
        "kpi_distinct_titles": "Số Vị Trí / Title",
        "kpi_sub_distinct_titles": "🎓 Phân cấp chuyên môn",

        # Anomaly & Strategic Panel
        "anomaly_panel_title": "Phân Tích Dữ Liệu & Chiến Lược Quản Trị",
        "anomaly_health_label": "Sức Khỏe Vận Hành",
        "tab_diagnosis": "🔍 Chẩn Đoán Điểm Bất Thường ({count})",
        "tab_strategic_plan": "🎯 Kế Hoạch Chiến Lược 3 Tầng Thực Chiến",
        "anomaly_actual_data": "Số liệu thực tế",
        "anomaly_root_cause": "Chẩn đoán nguyên nhân gốc rễ (Root Cause)",
        "anomaly_quantified_impact": "Lượng hóa rủi ro & tác động (Quantified Impact)",
        "plan_tier1_title": "🚨 TẦNG 1: CẤP BÁCH (0 — 30 NGÀY)",
        "plan_tier2_title": "⚖️ TẦNG 2: TÁI CẤU TRÚC (1 — 2 QUÝ)",
        "plan_tier3_title": "🔮 TẦNG 3: BỀN VỮNG & QUY HOẠCH NGUỒN LỰC (1 — 3 NĂM)",
        "plan_okr_title": "🎯 HỆ THỐNG CHỈ SỐ OKRS CAM KẾT & PHÂN CÔNG RACI",
        "btn_resolution": "🏛️ Ban hành Nghị Quyết Chiến Lược ({period})",
        "btn_zoom_report": "📊 Phóng to & Báo cáo Toàn màn hình",

        # Resolution Dialog
        "resolution_dialog_title": "🏛️ NGHỊ QUYẾT HỘI ĐỒNG QUẢN TRỊ & BAN ĐIỀU HÀNH",
        "resolution_doc_code": "MÃ VĂN BẢN: NQ-BĐH/{time}",
        "resolution_applied_period": "Áp dụng cho kỳ vận hành:",
        "resolution_health_status": "Trạng thái sức khỏe:",
        "resolution_sec1": "I. CĂN CỨ VẬN HÀNH & CHẨN ĐOÁN DỮ LIỆU THỰC TẾ",
        "resolution_sec2": "II. QUYẾT NGHỊ KẾ HOẠCH HÀNH ĐỘNG 3 TẦNG THỰC CHIẾN",
        "resolution_sec3": "III. CHỈ SỐ OKRS CAM KẾT & PHÂN CÔNG TRÁCH NHIỆM RACI",
        "resolution_sec4": "IV. ĐIỀU KHOẢN THI HÀNH & HIỆU LỰC NGHỊ QUYẾT",
        "resolution_btn_export": "📥 Tải Nghị Quyết PDF",

        # Chart Card Titles & Descriptions
        "chart_dept_dist_title": "🎯 Phân Bổ Nhân Viên Theo Department",
        "chart_top5_dept_title": "🏆 Top 5 Department Quy Mô Lớn Nhất",
        "chart_trend_title": "📈 Xu Hướng Biến Động Dòng Thời Gian ({metric})",

        # --- Sales Dashboard ---
        "sales_dash_title": "📊 Sales Executive Intelligence Dashboard",
        "sales_dash_badge": "CSDL AWESOME CHOCOLATES • LIVE SQL",
        "sales_layer_overview": "🏠 Tổng quan Kinh doanh (Overview)",
        "sales_layer_geo": "🌍 Doanh thu Thị trường (Geo)",
        "sales_layer_people": "👥 Đội ngũ Bán hàng (People & Teams)",
        "sales_layer_products": "🍫 Danh mục Sản phẩm (Products)",
        "sales_layer_trends": "📈 Xu hướng Doanh thu (Trends)",
        "sales_layer_top_performers": "🏆 Xếp hạng Ngôi sao Bán hàng (Top Performers)",
        "sales_kpi_revenue": "Tổng Doanh Thu",
        "sales_kpi_boxes": "Tổng Số Hộp Bán Ra",
        "sales_kpi_orders": "Tổng Số Giao Dịch",
        "sales_kpi_customers": "Số Chuyên Viên Kinh Doanh",

        # --- Evolution Dashboard ---
        "evo_dash_title": "🧬 VÒNG LẶP TIẾN HÓA & TỰ HOÀN THIỆN TRI THỨC (SELF-EVOLUTION LOOP)",
        "evo_dash_subtitle": "Hệ thống Tự học, Đánh giá Độc lập & Tích lũy Tri thức Tự động của Veraxus",
        "evo_kpi_score": "Điểm Chất lượng Trung bình",
        "evo_kpi_samples": "Tổng Mẫu Tri thức Vàng",
        "evo_kpi_autofix": "Tỷ lệ Tự sửa lỗi Thành công",
        "evo_kpi_latency": "Độ trễ Phản hồi Trung bình",
        "evo_tab_overview": "📈 Tổng quan Tiến hóa",
        "evo_tab_knowledge": "📚 Kho Tri thức Mẫu",
        "evo_tab_eval_logs": "🔍 Nhật ký Đánh giá & Giám sát",
    },

    "en": {
        # --- Common & Global ---
        "app_title": "Veraxus - Enterprise Intelligence",
        "app_subtitle": "Smart Business Data Copilot • Visual, Instant & Fully Reliable",
        "lang_vi": "Tiếng Việt",
        "lang_en": "English",
        "switch_lang": "Language / Ngôn ngữ",
        "loading": "Loading data...",
        "error": "Error",
        "success": "Success",
        "warning": "Warning",
        "confirm": "Confirm",
        "cancel": "Cancel",
        "close": "Close",
        "save": "Save",
        "delete": "Delete",
        "clear": "Reset",
        "search": "Search",
        "view": "View",
        "back": "Back",
        "back_to_chat": "← Back to Chat Copilot",
        "apply": "Apply",
        "records": "records",
        "columns": "columns",
        "fields": "fields",
        "download": "Download",

        # --- Header & Hero Section ---
        "hero_badge_ready": "Enterprise • Ready for Analysis",
        "hero_badge_connecting": "Connecting to Database...",
        "hero_badge_demo": "Demo Experience Mode",
        "hero_title": "VERAXUS",
        "hero_input_placeholder": "Ask Veraxus... (e.g., Quarterly sales by team, avg salary by department)",
        "hero_btn_analyze": "Analyze ➔",
        "hero_pill_security": "100% On-Premise Security",
        "hero_pill_realtime": "Real-Time DB Connection",
        "hero_pill_instant": "Instant Analytics <0.5s",
        "voice_listening": "Listening... Please state your question",
        "voice_btn_tooltip": "Voice input",

        # --- Starter Cards & Framework Categories ---
        "starter_framework_title": "Executive Analysis & Query Framework:",
        "starter_tab_trends": "Trends & Time",
        "starter_tab_ranking": "Ranking & Segmentation",
        "starter_tab_perf": "Performance & Structure",
        "starter_btn_explore": "Explore ➔",

        # --- Sidebar ---
        "sidebar_connected_engine": "Enterprise DB • Local Engine",
        "sidebar_demo_engine": "Demo DB • SQLite Engine",
        "sidebar_disconnected": "Database Disconnected",
        "sidebar_btn_new_chat": "+ New Chat",
        "sidebar_btn_settings": "Settings ⚙",
        "sidebar_btn_hr_dashboard": "❖ HR & Payroll Dashboard",
        "sidebar_btn_sales_dashboard": "❖ Sales Executive Dashboard",
        "sidebar_btn_crm_dashboard": "❖ CRM Executive Dashboard",
        "sidebar_btn_evolution": "🧬 Evolution Loop",
        "sidebar_schema_title": "Database Tables",
        "sidebar_schema_table_info": "Table `{table}`: {count} fields",
        "sidebar_schema_open_table": "Open table `{table}` →",
        "sidebar_history_title": "Query History",
        "sidebar_history_empty": "No queries yet. Enter your first question in the search bar above!",
        "sidebar_history_clear_btn": "Clear Chat History",
        "sidebar_history_clear_confirm": "All query history cleared!",
        "sidebar_history_click_hint": "Click on any query to view results:",

        # --- Chat & Results Components ---
        "exec_summary_title": "EXECUTIVE SUMMARY",
        "exec_time_label": "Execution Time:",
        "sql_query_toggle": "View SQL Query",
        "sql_query_copy": "Copy SQL",
        "sql_query_copied": "SQL Copied!",
        "sql_dialect_label": "Database Engine:",
        "table_tab_label": "📋 Data Table & Report",
        "chart_tab_bar": "📊 Bar Chart",
        "chart_tab_line": "📈 Line Chart",
        "chart_tab_donut": "🍩 Donut Chart",
        "chart_tab_scatter": "🔵 Scatter Plot",
        "chart_tab_kpi": "📌 KPI Metrics",
        "insights_title": "💡 Insights & Deep Dive",
        "forecast_tab_title": "🔮 Trend Forecast",
        "agent_team_tab_title": "🏛 5-Agent Council & SQL",
        "insights_highlights": "Key Highlights & Growth Opportunities",
        "insights_risks": "Risk Warnings & Bottlenecks",
        "insights_actions": "Strategic Action Plan",
        "follow_up_title": "Suggested Follow-up Questions:",
        "export_excel": "📥 Export Excel (.xlsx)",
        "export_pdf": "📄 Export PDF Report",
        "export_png": "🖼️ Download Chart PNG",
        "export_csv": "📥 Download CSV",
        "share_report_btn": "Share Report via Telegram Bot & Email",
        "export_report_title": "EXECUTIVE DATA ANALYTICS REPORT",
        "thinking_step_1": "Analyzing question & planning subtasks...",
        "thinking_step_2": "Identifying schema tables & business metrics...",
        "thinking_step_3": "Generating optimal SQL query & executing safely...",
        "thinking_step_4": "Synthesizing executive KPIs & chart visualization...",
        "audit_integrity_passed": "✓ Data Integrity Verified (100% Confidence)",
        "audit_source_label": "Source: Enterprise Database",
        "audit_index_optimized": "⚡ Index Optimized",

        # --- Settings & Onboarding ---
        "settings_modal_title": "⚙️ SYSTEM CONFIGURATION & CONNECTION",
        "settings_tab_db": "Database Connection",
        "settings_tab_ai": "AI Engine Setup",
        "settings_tab_advanced": "Advanced Options",
        "db_type_label": "Database Type",
        "db_host_label": "Host",
        "db_port_label": "Port",
        "db_name_label": "Database Name",
        "db_user_label": "Username",
        "db_pass_label": "Password",
        "db_btn_test": "Test Connection",
        "db_btn_save_connect": "Save & Connect Database",
        "ai_provider_label": "AI Model Provider",
        "ai_model_label": "Model Name",
        "ai_api_key_label": "API Key",
        "ai_btn_save": "Save AI Configuration",
        "adv_auto_insights": "Auto-generate Deep AI Insights",
        "adv_self_check": "Enable SQL Self-Correction & Verification Loop",
        "adv_cache": "Enable Instant Query Cache",

        # --- HR & Payroll Dashboard ---
        "hr_dash_title": "👥 HR & Payroll Intelligence Dashboard",
        "hr_dash_badge": "EMPLOYEES DB • LIVE SQL",
        "hr_select_layer_label": "Select Analysis Layer",
        "hr_btn_copilot": "💬 Copilot Assistant",
        "hr_btn_main_chat": "🔄 Main Chat",
        "hr_copilot_help": "Open AI Copilot assistant for instant context-aware analysis",
        "hr_main_chat_help": "Return to conversational AI assistant",
        "hr_layer_overview": "🏠 Executive Overview",
        "hr_layer_dept": "🏢 Department Management",
        "hr_layer_emp": "👥 Employee Directory",
        "hr_layer_salary": "💰 Compensation & Salary",
        "hr_layer_org": "🌳 Organizational Structure",
        "hr_layer_titles": "🎓 Titles & Positions",
        "hr_layer_managers": "👔 Department Managers",

        # 6 Topic Navigation Cards
        "hr_nav_header": "Select Deep Dive Analytics Domain (Explore by Layer):",
        "card_dept_title": "Department Management",
        "card_dept_desc": "Department roster, leadership & payroll expenditures ➔",
        "card_emp_title": "Employee Directory",
        "card_emp_desc": "Full employee directory, lookup by ID & title ➔",
        "card_sal_title": "Salary Analysis",
        "card_sal_desc": "Salary distribution by department & Top 10 earners ➔",
        "card_org_title": "Organizational Structure",
        "card_org_desc": "Hierarchy structure & direct subordinates under Managers ➔",
        "card_title_title": "Title & Positions",
        "card_title_desc": "Position catalog & average compensation by role ➔",
        "card_mgr_title": "Department Managers",
        "card_mgr_desc": "Manager profiles, assigned departments & tenures ➔",

        # Timeline Slider & Filters
        "timeline_slider_title": "Analysis Timeline Filter Slider",
        "timeline_period_all": "Full History",
        "timeline_criteria_title": "Trend Chart Timeline Criteria:",
        "cr_hiring": "👥 Hiring Scale & Gender Distribution",
        "cr_salary": "💰 Payroll & Average Compensation",
        "cr_dept_transfer": "🏢 Department Distribution & Staffing",
        "cr_promotions": "🎓 Title Appointments & Promotions",

        # KPI Summary Cards
        "kpi_overview_header": "Executive Overview Key Performance Indicators:",
        "kpi_total_employees": "Active Headcount",
        "kpi_sub_total_employees_all": "👥 Currently active workforce",
        "kpi_sub_total_employees_period": "👥 Active personnel in period ({period})",
        "kpi_total_depts": "Departments",
        "kpi_sub_total_depts": "🏢 Active operational departments",
        "kpi_avg_salary": "Average Salary",
        "kpi_sub_avg_salary_all": "💵 Current average payroll/person",
        "kpi_sub_avg_salary_period": "💵 Average salary ({period})",
        "kpi_distinct_titles": "Distinct Titles / Roles",
        "kpi_sub_distinct_titles": "🎓 Professional hierarchy levels",

        # Anomaly & Strategic Panel
        "anomaly_panel_title": "Data Diagnostics & Strategic Governance",
        "anomaly_health_label": "Operational Health",
        "tab_diagnosis": "🔍 Anomaly Diagnostics ({count})",
        "tab_strategic_plan": "🎯 3-Tier Strategic Action Plan",
        "anomaly_actual_data": "Actual Metrics",
        "anomaly_root_cause": "Root Cause Diagnosis",
        "anomaly_quantified_impact": "Quantified Risk & Impact",
        "plan_tier1_title": "🚨 TIER 1: URGENT (0 — 30 DAYS)",
        "plan_tier2_title": "⚖️ TIER 2: RESTRUCTURING (1 — 2 QUARTERS)",
        "plan_tier3_title": "🔮 TIER 3: SUSTAINABILITY & TALENT PIPELINE (1 — 3 YEARS)",
        "plan_okr_title": "🎯 COMMITTED OKRS & RACI GOVERNANCE FRAMEWORK",
        "btn_resolution": "🏛️ Issue Strategic Resolution ({period})",
        "btn_zoom_report": "📊 Fullscreen Analytics & Zoom Report",

        # Resolution Dialog
        "resolution_dialog_title": "🏛️ BOARD OF DIRECTORS & EXECUTIVE STRATEGIC RESOLUTION",
        "resolution_doc_code": "DOCUMENT ID: RES-EXEC/{time}",
        "resolution_applied_period": "Applicable Operational Period:",
        "resolution_health_status": "Operational Health Status:",
        "resolution_sec1": "I. OPERATIONAL BASELINE & EMPIRICAL DATA DIAGNOSTICS",
        "resolution_sec2": "II. 3-TIER EXECUTIVE STRATEGIC ACTION RESOLUTION",
        "resolution_sec3": "III. COMMITTED OKRS & RACI RESPONSIBILITY ASSIGNMENT",
        "resolution_sec4": "IV. GOVERNANCE MANDATE & ENFORCEMENT",
        "resolution_btn_export": "📥 Export Resolution PDF",

        # Chart Card Titles & Descriptions
        "chart_dept_dist_title": "🎯 Employee Distribution by Department",
        "chart_top5_dept_title": "🏆 Top 5 Largest Departments by Headcount",
        "chart_trend_title": "📈 Historical Timeline Trends ({metric})",

        # --- Sales Dashboard ---
        "sales_dash_title": "📊 Sales Executive Intelligence Dashboard",
        "sales_dash_badge": "AWESOME CHOCOLATES DB • LIVE SQL",
        "sales_layer_overview": "🏠 Sales Overview",
        "sales_layer_geo": "🌍 Geographic Revenue",
        "sales_layer_people": "👥 Sales Team & Reps",
        "sales_layer_products": "🍫 Product Portfolio",
        "sales_layer_trends": "📈 Revenue & Volume Trends",
        "sales_layer_top_performers": "🏆 Top Sales Performers",
        "sales_kpi_revenue": "Total Revenue",
        "sales_kpi_boxes": "Total Boxes Sold",
        "sales_kpi_orders": "Total Transactions",
        "sales_kpi_customers": "Sales Specialists",

        # --- Evolution Dashboard ---
        "evo_dash_title": "🧬 SELF-EVOLUTION & KNOWLEDGE ENHANCEMENT LOOP",
        "evo_dash_subtitle": "Veraxus Autonomous Learning, Independent Evaluation & Knowledge Curation Engine",
        "evo_kpi_score": "Average Quality Score",
        "evo_kpi_samples": "Golden Knowledge Samples",
        "evo_kpi_autofix": "Auto-Fix Success Rate",
        "evo_kpi_latency": "Average Query Latency",
        "evo_tab_overview": "📈 Evolution Overview",
        "evo_tab_knowledge": "📚 Knowledge Base",
        "evo_tab_eval_logs": "🔍 Evaluation & Audit Logs",
    }
}


def get_current_language() -> str:
    """Trả về mã ngôn ngữ hiện tại ('vi' hoặc 'en'), mặc định là 'vi'."""
    if hasattr(st, "session_state") and "language" in st.session_state:
        lang = st.session_state.get("language", "vi")
        if lang in ("vi", "en"):
            return lang
    return "vi"


def set_current_language(lang: str) -> None:
    """Cập nhật ngôn ngữ trong session_state ('vi' hoặc 'en')."""
    if lang in ("vi", "en"):
        st.session_state["language"] = lang


def t(key: str, lang: str = None, **kwargs: Any) -> str:
    """Tra cứu bản dịch theo key cho ngôn ngữ hiện tại.
    Hỗ trợ format biến: t("sidebar_schema_table_info", table="departments", count=2)
    """
    target_lang = lang or get_current_language()
    lang_dict = TRANSLATIONS.get(target_lang, TRANSLATIONS["vi"])
    fallback_dict = TRANSLATIONS.get("vi", {})
    
    text = lang_dict.get(key, fallback_dict.get(key, key))
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text


def render_language_switcher_button(key_suffix: str = "main") -> None:
    """Hiển thị nút chuyển đổi song ngữ gọn gàng, hiện đại (VI 🇻🇳 / EN 🇬🇧)."""
    current_lang = get_current_language()
    
    col1, col2 = st.columns([1, 1], gap="small")
    
    with col1:
        is_vi = (current_lang == "vi")
        btn_type = "primary" if is_vi else "secondary"
        if st.button("🇻🇳 VI", key=f"lang_btn_vi_{key_suffix}", type=btn_type, use_container_width=True):
            if current_lang != "vi":
                set_current_language("vi")
                st.rerun()

    with col2:
        is_en = (current_lang == "en")
        btn_type = "primary" if is_en else "secondary"
        if st.button("🇬🇧 EN", key=f"lang_btn_en_{key_suffix}", type=btn_type, use_container_width=True):
            if current_lang != "en":
                set_current_language("en")
                st.rerun()
