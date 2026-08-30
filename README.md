# 🗄️ Veraxus for SQL

Ứng dụng trợ lý ảo phân tích kinh doanh và trích xuất dữ liệu thông minh dựa trên AI, cho phép bạn kết nối trực tiếp với Database (MySQL Cloud/Local hoặc SQLite Demo), đặt câu hỏi bằng ngôn ngữ tự nhiên, tự động chuyển đổi thành SQL an toàn, vẽ biểu đồ tương tác, tự động tìm Insight kinh doanh, dự báo xu hướng và phát hiện điểm bất thường.

---

## ✨ Trải nghiệm Người dùng & Tính năng Nổi bật

1. **Sidebar Đa năng: Tra cứu Bảng CSDL & Quản lý Lịch sử Chat *(Mới)***:
   - **Top Sidebar**: Nút **`⚙️ Cấu hình`** (mở màn hình đổi kết nối) & nút **`➕ Chat Mới`** (tạo phiên hội thoại mới).
   - **Khám phá Bảng Database (Table Explorer)**: Xem danh sách toàn bộ các bảng trong CSDL đang kết nối, tra cứu cấu trúc cột, kiểu dữ liệu và **xem trước 5 dòng dữ liệu mẫu (*Sample Preview*)** của bảng đó.
   - **Lịch sử các cuộc trò chuyện (Chat History)**: Danh sách các câu hỏi đã hỏi trong phiên kèm nút **`🗑️ Xóa lịch sử`**.

2. **Giao diện Silent Fix (Tự sửa âm thầm) & Ẩn Log Kỹ thuật *(Mới)***:
   - Tự động sửa lỗi và kiểm định QA âm thầm trong nền, không xả log rác ra màn hình.
   - Toàn bộ câu lệnh SQL thuần và nhật ký thực thi được gom gọn gàng vào mục **`🛠️ Chi tiết Kỹ thuật`** (mặc định đóng).

3. **Màn hình Cấu hình Onboarding Chuyên biệt & Tự động Bỏ qua (Auto-Skip)**:
   - Màn hình Setup Wizard rộng rãi dạng Card trực quan.
   - Tự động kết nối và vào thẳng màn hình Chat nếu đã có cấu hình lưu sẵn trên máy.

4. **Tự động Tìm Insight Kinh doanh & Phát hiện Bất thường (Automated Insights)**:
   - **Outlier Thống kê (IQR)**: Nhận diện điểm dữ liệu bất thường vượt ngoài biên kỳ vọng.
   - **Đột biến & Sụt giảm Tốc độ**: Tự động phát hiện các kỳ tăng trưởng vọt ($> +100\%$) hoặc sụt giảm nghiêm trọng ($< -50\%$) trên chuỗi thời gian.
   - **Rủi ro Tập trung**: Cảnh báo khi 1 đối tượng chiếm $> 50\%$ tổng số liệu toàn bộ danh sách.
   - **Báo cáo Chiến lược từ AI (Chief BI Officer)**: Tự động phân tích nguyên nhân và đưa ra gợi ý hành động (Action Plan).

5. **Hỗ trợ Đa Nhà cung cấp AI (Multi-Provider)**:
   - **OpenRouter**: Tích hợp sẵn Base URL `https://openrouter.ai/api/v1`, hỗ trợ `deepseek/deepseek-chat`, `deepseek/deepseek-r1`, `anthropic/claude-3.5-sonnet`, `openai/gpt-4o`, `openai/gpt-4o-mini`,...
   - **Google Gemini**: Hỗ trợ `gemini-2.5-flash`, `gemini-1.5-pro`, `gemini-1.5-flash` qua SDK chính thức `google-genai`.
   - **Alibaba Qwen (DashScope)**: Hỗ trợ `qwen-plus`, `qwen-turbo`, `qwen2.5-72b-instruct`, `qwen-max` qua API tương thích OpenAI.

6. **Text-to-SQL Thông minh, Kiểm tra Cú pháp & Tự sửa lỗi (Self-Healing Loop)**:
   - Tự động trích xuất Schema (bảng, cột, kiểu dữ liệu).
   - Bộ kiểm tra cân đối dấu ngoặc đơn (`check_parentheses_balance`) ngăn chặn lỗi cú pháp MySQL 1064.
   - Kiểm tra an toàn SQL (chỉ cho phép `SELECT`/`WITH`, chặn truy vấn phá hủy/ghi đè).
   - Cơ chế **Self-Check (QA)** tự động kiểm định kết quả và thử sửa tối đa 3 lần nếu phát hiện lỗi logic hoặc cú pháp.
   - Cảnh báo tự động khi phát hiện dữ liệu bị nhân bản do JOIN bảng lịch sử.

7. **Trực quan hóa Dữ liệu Thông minh (Smart Charting)**:
   - Tự động phát hiện kiểu dữ liệu để chọn biểu đồ tối ưu (**Line**, **Bar**, **Area**, **Scatter**).
   - Thanh trượt điều chỉnh số lượng đối tượng hiển thị linh hoạt (hỗ trợ hiển thị đầy đủ 100+ đối tượng).

8. **Dự báo Xác định (Deterministic Forecasting)**:
   - Sử dụng thuật toán Hồi quy tuyến tính xác định (*Linear Regression*) với đường cầu nối thực tế và tương lai.

9. **Tối ưu Quota & Trải nghiệm**:
   - Tích hợp sẵn cơ sở dữ liệu mẫu **SQLite Demo** (kinh doanh chocolate 2023) để trải nghiệm ngay.
   - Bộ nhớ tạm (**Cache**) tránh gọi lại AI khi người dùng hỏi các câu hỏi trùng lặp trong cùng phiên.
   - Hỗ trợ kết nối MySQL Local (`localhost`, `127.0.0.1`, `host.docker.internal`) và MySQL Cloud (Aiven, Railway,...).

---

## 📁 Cấu trúc Thư mục Dự án

```text
AI-business-agent-/
├── .devcontainer/
│   └── devcontainer.json          # Cấu hình môi trường Codespaces/Dev Container
├── .env.example                   # Mẫu cấu hình biến môi trường
├── .gitignore                     # Cấu hình bỏ qua file rác và cache
├── README.md                      # Tài liệu hướng dẫn sử dụng
├── requirements.txt               # Danh sách thư viện cần thiết
├── app.py                         # Điểm khởi chạy chính & Điều hướng View
├── legacy/                        # Lưu trữ các file code nháp / phiên bản cũ
└── src/                           # Toàn bộ mã nguồn module hóa
    ├── __init__.py
    ├── config.py                  # Cấu hình tập trung, hằng số, regex, providers
    ├── config_store.py            # Lưu trữ và nạp lại cấu hình tự động
    ├── database/                  # Quản lý kết nối DB & truy vấn
    │   ├── __init__.py
    │   ├── connection.py          # Kết nối MySQL & xử lý alias
    │   ├── demo_data.py           # Sinh dữ liệu mẫu SQLite in-memory
    │   ├── schema.py              # Tự động đọc Schema DB & Table Inspector
    │   └── query_runner.py        # Đọc dữ liệu giới hạn dòng & làm sạch lỗi
    ├── llm/                       # Tương tác với AI
    │   ├── __init__.py
    │   ├── client.py              # Wrapper cho Gemini, OpenRouter và Qwen
    │   ├── prompts.py             # Quản lý toàn bộ prompt templates
    │   └── agent.py               # SQL Agent, QA self-check & Insight generator
    ├── analytics/                 # Thống kê & Phân tích
    │   ├── __init__.py
    │   ├── heuristics.py          # Phân loại cột thông minh (ID, Time, Measure)
    │   ├── forecasting.py         # Dự báo hồi quy tuyến tính
    │   └── anomaly.py             # Phát hiện điểm bất thường đa chiều
    ├── visualization/             # Trực quan hóa
    │   ├── __init__.py
    │   └── charts.py              # Vẽ biểu đồ thông minh với Plotly
    └── ui/                        # Giao diện người dùng Streamlit
        ├── __init__.py
        ├── state.py               # Quản lý Session State
        ├── onboarding.py          # Màn hình Onboarding / Cài đặt độc lập
        ├── sidebar.py             # Sidebar tra cứu bảng DB & Lịch sử chat
        ├── connection_dialog.py   # Dialog Loading & Auto-connect error view
        └── components.py          # Components hiển thị kết quả, tabs, logs
```

---

## 🚀 Hướng dẫn Khởi chạy Ứng dụng

```bash
streamlit run app.py
```
- **Lần đầu mở**: Trình duyệt hiển thị màn hình Onboarding rộng rãi để chọn nguồn dữ liệu và dán API Key.
- **Từ các lần sau**: Hệ thống tự động bỏ qua onboarding và mở thẳng giao diện Chat sẵn sàng làm việc!
- **Sidebar bên trái**: Tra cứu danh sách các bảng trong DB, xem 5 dòng mẫu và quản lý lịch sử hội thoại.
- **Đổi cấu hình**: Bấm nút **`⚙️ Cấu hình`** ở Top Sidebar hoặc Top Header bất cứ lúc nào.
