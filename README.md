# 🤖 Universal AI Business Agent for SQL

Ứng dụng trợ lý ảo phân tích kinh doanh thông minh dựa trên AI, cho phép bạn kết nối trực tiếp với Database (MySQL Cloud/Local hoặc SQLite Demo), đặt câu hỏi bằng ngôn ngữ tự nhiên, tự động chuyển đổi thành SQL an toàn, vẽ biểu đồ tương tác, dự báo xu hướng và phân tích điểm bất thường.

---

## ✨ Tính năng Nổi bật

1. **Hỗ trợ Đa Nhà cung cấp AI (Multi-Provider)**:
   - **Google Gemini**: Hỗ trợ các model như `gemini-2.5-flash`, `gemini-1.5-pro`, `gemini-1.5-flash`.
   - **Alibaba Qwen (DashScope)**: Hỗ trợ `qwen-plus`, `qwen-turbo`, `qwen2.5-72b-instruct`, `qwen-max` qua API tương thích OpenAI.

2. **Text-to-SQL Thông minh & Tự sửa lỗi (Self-Healing Loop)**:
   - Tự động trích xuất Schema (bảng, cột, kiểu dữ liệu).
   - Kiểm tra an toàn SQL (chỉ cho phép `SELECT`/`WITH`, chặn truy vấn phá hủy/ghi đè).
   - Cơ chế **Self-Check (QA)** tự động kiểm định kết quả và thử sửa tối đa 3 lần nếu phát hiện lỗi logic hoặc cú pháp.
   - Cảnh báo tự động khi phát hiện dữ liệu bị nhân bản do JOIN bảng lịch sử.

3. **Trực quan hóa Dữ liệu Thông minh (Smart Charting)**:
   - Tự động phát hiện kiểu dữ liệu để chọn biểu đồ tối ưu (**Line**, **Bar**, **Area**, **Scatter**).
   - Tự động phân nhóm màu sắc, xử lý nhãn trùng lặp và giới hạn số lượng cột quá lớn.

4. **Dự báo Xác định & Phát hiện Bất thường**:
   - **Dự báo xu hướng**: Sử dụng thuật toán Hồi quy tuyến tính xác định (*Deterministic Linear Regression*) với đường cầu nối thực tế và tương lai.
   - **Phát hiện Outlier**: Thuật toán IQR (*Interquartile Range*) kết hợp AI giải thích nguyên nhân kinh doanh.

5. **Tối ưu Quota & Trải nghiệm**:
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
    ├── database/                  # Quản lý kết nối DB & truy vấn
    │   ├── __init__.py
    │   ├── connection.py          # Kết nối MySQL & xử lý alias
    │   ├── demo_data.py           # Sinh dữ liệu mẫu SQLite in-memory
    │   ├── schema.py              # Tự động đọc Schema DB
    │   └── query_runner.py        # Đọc dữ liệu giới hạn dòng & làm sạch lỗi
    ├── llm/                       # Tương tác với AI
    │   ├── __init__.py
    │   ├── client.py              # Wrapper cho Gemini và Qwen (OpenAI-compatible)
    │   ├── prompts.py             # Quản lý toàn bộ prompt templates
    │   └── agent.py               # SQL Agent, QA self-check & vòng lặp tự sửa lỗi
    ├── analytics/                 # Thống kê & Phân tích
    │   ├── __init__.py
    │   ├── heuristics.py          # Phân loại cột thông minh (ID, Time, Measure)
    │   ├── forecasting.py         # Dự báo hồi quy tuyến tính
    │   └── anomaly.py             # Phát hiện điểm bất thường IQR
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
Tạo môi trường ảo (khuyến nghị) và cài đặt các thư viện phụ thuộc:

```bash
# Tạo môi trường ảo
python3 -m venv venv
source venv/bin/activate  # Trên macOS/Linux
# venv\Scripts\activate   # Trên Windows

# Cài đặt thư viện
pip install -r requirements.txt
```

### 3. Chạy Ứng dụng
Khởi chạy giao diện Streamlit:

```bash
streamlit run app.py
```

Trình duyệt sẽ tự động mở tại địa chỉ: `http://localhost:8501`.

---

## 💡 Hướng dẫn Sử dụng

1. **Khởi động**:
   - Ở thanh công cụ bên trái (**Sidebar**), chọn **🎮 Dùng dữ liệu mẫu (Demo)** để thử nghiệm ngay lập tức.
   - Chọn Provider AI (**Gemini** hoặc **Qwen**) và nhập API Key của bạn.
   - Nhấn **🔌 Kết nối Database & AI**.
2. **Đặt câu hỏi**:
   - Nhập câu hỏi vào khung chat ở dưới cùng (VD: *"Tổng doanh số theo từng tháng năm 2023"* hoặc *"Top 3 nhân viên có số khách hàng cao nhất"*).
   - Agent sẽ tự động sinh SQL, thực thi và trả về bảng kết quả.
3. **Phân tích nâng cao**:
   - Xem biểu đồ tương tác tại tab **📊 Biểu đồ** hoặc bấm nút **🔍 AI giải thích điểm bất thường** nếu phát hiện outlier.
   - Chuyển sang tab **🔮 Dự báo** để xem xu hướng cho các kỳ tương lai.
   - Bấm **⬇️ Tải CSV** để xuất dữ liệu về máy.

---

## 🛡️ Bảo mật & Tối ưu Quota
- Ứng dụng không lưu trữ mật khẩu hay API Key vào bất kỳ file nào trên ổ đĩa.
- Thông báo lỗi kết nối tự động che mật khẩu (`***`).
- Các câu lệnh SQL bị cấm: `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`,... chỉ cho phép `SELECT`/`WITH`.
- Giới hạn đọc tối đa `3000` dòng/lần truy vấn để bảo vệ bộ nhớ và tốc độ ứng dụng.
