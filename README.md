# 🤖 Universal AI Business Agent for SQL

Ứng dụng trợ lý ảo phân tích kinh doanh thông minh dựa trên AI, cho phép bạn kết nối trực tiếp với Database (MySQL Cloud/Local hoặc SQLite Demo), đặt câu hỏi bằng ngôn ngữ tự nhiên, tự động chuyển đổi thành SQL an toàn, vẽ biểu đồ tương tác, tự động tìm Insight kinh doanh, dự báo xu hướng và phát hiện điểm bất thường.

---

## ✨ Tính năng Nổi bật

1. **Tự động Kết nối Ngay khi Mở Trang (Auto-Connect on Startup) *(Mới)***:
   - Tự động nạp thông tin đăng nhập và thiết lập kết nối Database & AI ngay khi mở web nếu cấu hình hợp lệ.
   - Sẵn sàng truy vấn ngay lập tức mà không cần bấm nút kết nối thủ công mỗi lần mở lại app.

2. **Tự động Tìm Insight Kinh doanh & Phát hiện Bất thường (Automated Insights) *(Mới)***:
   - **Outlier Thống kê (IQR)**: Nhận diện điểm dữ liệu bất thường vượt ngoài biên kỳ vọng.
   - **Đột biến & Sụt giảm Tốc độ**: Tự động phát hiện các kỳ tăng trưởng vọt ($> +100\%$) hoặc sụt giảm nghiêm trọng ($< -50\%$) trên chuỗi thời gian.
   - **Rủi ro Tập trung**: Cảnh báo khi 1 đối tượng chiếm $> 50\%$ tổng số liệu toàn bộ danh sách.
   - **Báo cáo Chiến lược từ AI (Chief BI Officer)**: Tự động phân tích nguyên nhân và đưa ra gợi ý hành động (Action Plan).

3. **Hỗ trợ Đa Nhà cung cấp AI (Multi-Provider)**:
   - **OpenRouter**: Tích hợp sẵn Base URL `https://openrouter.ai/api/v1`, hỗ trợ `deepseek/deepseek-chat`, `deepseek/deepseek-r1`, `anthropic/claude-3.5-sonnet`, `openai/gpt-4o`, `openai/gpt-4o-mini`,...
   - **Google Gemini**: Hỗ trợ `gemini-2.5-flash`, `gemini-1.5-pro`, `gemini-1.5-flash` qua SDK chính thức `google-genai`.
   - **Alibaba Qwen (DashScope)**: Hỗ trợ `qwen-plus`, `qwen-turbo`, `qwen2.5-72b-instruct`, `qwen-max` qua API tương thích OpenAI.

4. **Text-to-SQL Thông minh, Kiểm tra Cú pháp & Tự sửa lỗi (Self-Healing Loop)**:
   - Tự động trích xuất Schema (bảng, cột, kiểu dữ liệu).
   - Bộ kiểm tra cân đối dấu ngoặc đơn (`check_parentheses_balance`) ngăn chặn lỗi cú pháp MySQL 1064.
   - Kiểm tra an toàn SQL (chỉ cho phép `SELECT`/`WITH`, chặn truy vấn phá hủy/ghi đè).
   - Cơ chế **Self-Check (QA)** tự động kiểm định kết quả và thử sửa tối đa 3 lần nếu phát hiện lỗi logic hoặc cú pháp.
   - Cảnh báo tự động khi phát hiện dữ liệu bị nhân bản do JOIN bảng lịch sử.

5. **Trực quan hóa Dữ liệu Thông minh (Smart Charting)**:
   - Tự động phát hiện kiểu dữ liệu để chọn biểu đồ tối ưu (**Line**, **Bar**, **Area**, **Scatter**).
   - Thanh trượt điều chỉnh số lượng đối tượng hiển thị linh hoạt (hỗ trợ hiển thị đầy đủ 100+ đối tượng).

6. **Dự báo Xác định (Deterministic Forecasting)**:
   - Sử dụng thuật toán Hồi quy tuyến tính xác định (*Linear Regression*) với đường cầu nối thực tế và tương lai.

7. **Tối ưu Quota & Trải nghiệm**:
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
├── app.py                         # Điểm khởi chạy chính của ứng dụng Streamlit
├── legacy/                        # Lưu trữ các file code nháp / phiên bản cũ
└── src/                           # Toàn bộ mã nguồn module hóa
    ├── __init__.py
    ├── config.py                  # Cấu hình tập trung, hằng số, regex, providers
    ├── config_store.py            # Lưu trữ và nạp lại cấu hình tự động
    ├── database/                  # Quản lý kết nối DB & truy vấn
    │   ├── __init__.py
    │   ├── connection.py          # Kết nối MySQL & xử lý alias
    │   ├── demo_data.py           # Sinh dữ liệu mẫu SQLite in-memory
    │   ├── schema.py              # Tự động đọc Schema DB
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
        ├── sidebar.py             # Sidebar cấu hình kết nối DB & AI
        └── components.py          # Components hiển thị kết quả, tabs, logs
```

---

## 🚀 Hướng dẫn Cài đặt & Khởi chạy

### 1. Yêu cầu Hệ thống
- **Python**: 3.10 trở lên
- **Git**

### 2. Cài đặt Thư viện
```bash
pip install -r requirements.txt
```

### 3. Chạy Ứng dụng
Khởi chạy giao diện Streamlit:
```bash
streamlit run app.py
```
Trình duyệt sẽ tự động mở tại địa chỉ: `http://localhost:8501`.
Lần đầu bạn nhập thông tin cấu hình và bấm Kết nối, hệ thống sẽ tự động lưu lại. Từ các lần mở sau, hệ thống sẽ tự động kết nối sẵn sàng cho bạn!
