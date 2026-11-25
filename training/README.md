# Veraxus Stage 4 — Fine-Tuning Mô Hình Local (Colab L4 -> Ollama Offline)

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Phongkarazz/AI-business-agent-/blob/main/training/Veraxus_Stage4_Colab_L4_Train.ipynb)

Pipeline huấn luyện **SFT + When2Call DPO → GGUF (`Q4_K_M`)** tối ưu cho Veraxus chạy 100% offline qua Ollama trên máy Mac 8GB RAM (`veraxus-coder:3b`) hoặc server 16GB+ RAM (`veraxus-coder:7b`).

## 1. Dữ liệu huấn luyện thuần tổng hợp (`training/datasets/`)
Được tạo bằng `datamate/stage4_dataset_builder.py` từ **100% dữ liệu tổng hợp nội bộ & demo công khai của Veraxus** (không chứa bất kỳ dữ liệu bên ngoài hay dữ liệu cuộc thi nào):
- **Chaos SME Archetypes**: Đa kỳ `source_sheet`, nối biệt danh `LEFT JOIN + COALESCE`, SĐT mất số `0`, và Python Sandbox (`sum_compound_vn_nums`, ma trận chấm công 31 ngày).
- **Veraxus Public Demo & Synthetic SMEs**: Sinh và kiểm chứng thực thi end-to-end qua `execute_sql_safe` + `verify_sql_semantics`.
- **Hammer Schema Masking**: Ẩn tên bảng/cột ngẫu nhiên kèm kiểm chứng thực thi tương đương để mô hình học suy luận cấu trúc schema tổng quát.
- **When2Call DPO**: Dạy ranh giới `Call SQL/Python` vs `Unanswerable`, giữ lọc trạng thái hủy/hoàn, dùng `NORM_VN(...)`, và không gộp mất `source_sheet`.

## 2. Chạy trên Google Colab (chỉ cần L4 GPU + Run All)
1. Mở `training/Veraxus_Stage4_Colab_L4_Train.ipynb` bằng nút **Open in Colab** ở trên.
2. Vào **Runtime → Change runtime type → Chọn GPU `L4`** (24GB VRAM).
3. Giữ `MODEL_PROFILE = "3b"` (tối ưu cho máy Mac 8GB RAM; đổi `"7b"` nếu dùng máy 16GB+ RAM), bật `SAVE_TO_GOOGLE_DRIVE = True` để lưu thẳng file `.gguf` vào Google Drive.
4. Bấm **Runtime → Run all** và tải file `veraxus-coder-3b-q4_k_m.gguf`.

## 3. Nạp vào Ollama trên máy Mac & dùng trong Veraxus
```bash
bash training/import_to_ollama.sh ~/Downloads/veraxus-coder-3b-q4_k_m.gguf veraxus-coder:3b
```
Sau khi nạp xong, mở Veraxus (`streamlit run app.py`), chọn **Ollama (Local AI Offline)** và chọn model **`veraxus-coder:3b`** (nếu chưa import, hệ thống sẽ tự fallback an toàn về `qwen2.5-coder:3b`).
