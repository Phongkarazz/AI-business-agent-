"""
Multi-provider LLM client supporting Google Gemini, OpenRouter, and Alibaba Qwen (OpenAI-compatible)
with intelligent key detection, automatic model routing, max_tokens optimization (fixing 402 errors),
and robust SQL extraction.
"""

import re
import time
from google import genai

try:
    from openai import OpenAI as _OpenAIClient
except ImportError:
    _OpenAIClient = None

from src.config import DASHSCOPE_BASE_URL, OPENROUTER_BASE_URL, OLLAMA_BASE_URL


def extract_clean_content(raw: str) -> str:
    """Trích xuất nội dung sạch từ phản hồi của mô hình (bóc tách code block, loại bỏ backticks, lời thoại mở đầu)."""
    if not raw:
        return ""

    # 1. Nếu có markdown code block ```sql ... ``` hoặc ```json ... ``` hoặc ``` ... ```
    match = re.search(r"```(?:sql|json)?\s*([\s\S]*?)\s*```", raw, re.IGNORECASE)
    if match:
        extracted = match.group(1).strip()
    else:
        extracted = raw.strip()

    # 2. Bóc bỏ markdown backticks đơn/kép/ba bao quanh: `SELECT ...` hoặc ```sql SELECT ...
    extracted = re.sub(r"^```(?:sql|json)?\s*", "", extracted, flags=re.IGNORECASE)
    extracted = re.sub(r"\s*```$", "", extracted)
    extracted = extracted.strip().strip("`").strip()

    # 3. Loại bỏ các tiền tố giải thích hoặc comment mở đầu (#, --, /* */) trước câu lệnh chính
    extracted = re.sub(r"^\s*/\*.*?\*/\s*", "", extracted, flags=re.DOTALL)
    lines = extracted.splitlines()
    cleaned_lines = []
    found_sql_start = False
    for line in lines:
        stripped_line = line.strip().strip("`")
        if not found_sql_start:
            if not stripped_line or stripped_line.startswith("#") or stripped_line.startswith("--") or stripped_line.startswith("//"):
                continue
            if stripped_line.lower() in ("sql", "json"):
                continue
            found_sql_start = True
        cleaned_lines.append(line)

    extracted = "\n".join(cleaned_lines).strip().strip("`").strip()

    # 4. Tìm câu lệnh SQL thực sự (phải có SELECT ... FROM hoặc WITH ... SELECT ... FROM)
    # Tránh bắt nhầm các lời thoại bình luận mở đầu như: "Select phần**:", "SELECT mục 1:", "Select câu hỏi..."
    if re.search(r"^\s*SELECT[^\n]*(?:[\*\:]{2,}|phần|mục|đoạn|bước|câu)", extracted, re.IGNORECASE):
        real_sql_match = re.search(r"(?:^|\n)\s*(SELECT\s+[\s\S]*?\bFROM\b[\s\S]*?)(?:;|\n\n|$)", extracted, re.IGNORECASE)
        if real_sql_match:
            extracted = real_sql_match.group(1).strip()
    else:
        match_kw = re.search(r"\b(SELECT\s+[\s\S]*?\bFROM\b|WITH\s+[a-zA-Z0-9_]+\s+AS\b)", extracted, re.IGNORECASE)
        if match_kw and match_kw.start() > 0:
            prefix = extracted[:match_kw.start()].strip()
            if not any(k in prefix.lower() for k in ["insert", "update", "delete", "drop", "alter", "create"]):
                extracted = extracted[match_kw.start():].strip()

    return extracted.strip().strip("`").strip()


def normalize_model_for_openrouter(model_name: str) -> str:
    """Tự động chuẩn hóa tên model cho OpenRouter nếu người dùng chỉ nhập tên ngắn."""
    model_name = (model_name or "").strip()
    if not model_name:
        return "deepseek/deepseek-chat"

    if "/" not in model_name:
        lowered = model_name.lower()
        if lowered.startswith("qwen"):
            return f"qwen/{model_name}"
        elif lowered.startswith("gpt") or lowered.startswith("o1") or lowered.startswith("o3"):
            return f"openai/{model_name}"
        elif lowered.startswith("claude"):
            return f"anthropic/{model_name}"
        elif lowered.startswith("gemini"):
            return f"google/{model_name}"
        elif lowered.startswith("deepseek"):
            return f"deepseek/{model_name}"
        elif lowered.startswith("llama"):
            return f"meta-llama/{model_name}"
    return model_name


def get_llm_client(provider: str, api_key: str, base_url: str = None):
    """Tạo client AI tương ứng với provider được chọn với tính năng tự động nhận diện OpenRouter và Ollama."""
    api_key = (api_key or "").strip()
    if not api_key and provider != "Ollama (Local AI Offline)":
        raise ValueError("API Key không được để trống.")
    if provider == "Ollama (Local AI Offline)" and not api_key:
        api_key = "ollama"

    base_url_str = (base_url or "").strip().lower()

    is_openrouter = (
        provider == "OpenRouter"
        or api_key.startswith("sk-or-v1-")
        or "openrouter.ai" in base_url_str
    )

    if provider == "Gemini (Google)" and not is_openrouter:
        return genai.Client(api_key=api_key)
    elif provider == "Ollama (Local AI Offline)":
        if _OpenAIClient is None:
            raise ImportError("Thiếu thư viện `openai`. Vui lòng cài đặt: pip install openai")
        target_url = (base_url or "").strip() or OLLAMA_BASE_URL
        return _OpenAIClient(api_key="ollama", base_url=target_url)
    elif is_openrouter:
        if _OpenAIClient is None:
            raise ImportError("Thiếu thư viện `openai`. Vui lòng cài đặt: pip install openai")
        target_url = (base_url or "").strip() or OPENROUTER_BASE_URL
        return _OpenAIClient(
            api_key=api_key,
            base_url=target_url,
            default_headers={
                "HTTP-Referer": "https://localhost:8501",
                "X-Title": "Veraxus for SQL",
            }
        )
    elif provider == "Qwen (Alibaba Cloud)":
        if _OpenAIClient is None:
            raise ImportError("Thiếu thư viện `openai`. Vui lòng cài đặt: pip install openai")
        target_url = (base_url or "").strip() or DASHSCOPE_BASE_URL
        return _OpenAIClient(api_key=api_key, base_url=target_url)
    else:
        raise ValueError(f"Provider không được hỗ trợ: {provider}")


def _call_gemini_impl(client, model_name: str, prompt: str, max_tokens: int = 2048) -> str:
    # Chuẩn hóa tên model Gemini và tự động chuyển tiếp lên Gemini 3 Series
    clean_model = (model_name or "").strip().lower()
    if "/" in clean_model:
        clean_model = clean_model.split("/")[-1]

    if clean_model in ("gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro", "gemini-flash", "gemini-pro", ""):
        clean_model = "gemini-3.7-flash"

    # Danh sách model dự phòng ưu tiên theo thứ tự chịu tải tốt và tốc độ cao
    target_models = [clean_model]
    for fallback in ["gemini-3.5-flash-lite", "gemini-2.5-flash", "gemini-3.7-flash", "gemini-3.1-pro-preview"]:
        if fallback not in target_models:
            target_models.append(fallback)

    last_exc = None
    for m in target_models:
        try:
            response = client.models.generate_content(model=m, contents=prompt)
            if response and response.text:
                return response.text
        except Exception as e:
            last_exc = e
            err_str = str(e).lower()
            should_fallback = any(k in err_str for k in [
                "404", "not_found", "no longer available", "not found",
                "503", "unavailable", "high demand", "overloaded", "spikes in demand",
                "429", "resource_exhausted", "quota", "rate_limit", "exhausted"
            ])
            if should_fallback:
                time.sleep(1.0)
                continue
            raise e

    if last_exc:
        raise last_exc
    return ""


def _call_openai_compatible_impl(client, model_name: str, prompt: str, max_tokens: int = 2048) -> str:
    completion = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens
    )
    return completion.choices[0].message.content


def call_llm(client, provider: str, model_name: str, prompt: str, max_retries: int = 3, max_tokens: int = 2048) -> tuple[str | None, str | None]:
    """Gọi LLM với cấu hình max_tokens tối ưu, cơ chế Exponential Backoff trên lỗi 429/503 và tự động fallback."""
    if not client:
        return None, "Chưa khởi tạo client AI."

    is_openrouter = (
        provider == "OpenRouter"
        or ("openrouter.ai" in str(getattr(client, "base_url", "")).lower())
    )

    if is_openrouter:
        model_name = normalize_model_for_openrouter(model_name)

    impl = _call_gemini_impl if (provider == "Gemini (Google)" and not is_openrouter) else _call_openai_compatible_impl

    current_max_tokens = max_tokens
    last_error = None

    for attempt in range(max_retries):
        try:
            raw = impl(client, model_name, prompt, max_tokens=current_max_tokens)
            cleaned = extract_clean_content(raw)
            return cleaned, None
        except Exception as e:
            err = str(e)
            last_error = err

            # 1. Tự động bắt lỗi 402 OpenRouter do vượt quá trần credit khi đặt max_tokens lớn
            if "402" in err or "fewer max_tokens" in err or "can only afford" in err:
                if current_max_tokens > 512:
                    current_max_tokens = 1024 if current_max_tokens > 1024 else 512
                    time.sleep(1)
                    continue
                return None, "Tài khoản OpenRouter của bạn đã hết số dư ($0.00). Vui lòng nạp thêm credit tại https://openrouter.ai/settings/credits để tiếp tục."

            # 2. Xử lý lỗi 429 (Rate Limit / Quota) với cơ chế tự động chờ (Exponential Backoff)
            if "429" in err or "RESOURCE_EXHAUSTED" in err or "RateLimit" in err or "Throttling" in err or "insufficient_quota" in err or "quota" in err.lower():
                if attempt < max_retries - 1:
                    wait_time = 2 * (attempt + 1)
                    time.sleep(wait_time)
                    continue
                return None, f"Đạt giới hạn tần suất gọi hoặc hết quota ({provider} - {model_name}). Hệ thống đã tự động thử lại {max_retries} lần nhưng chưa thành công. Vui lòng chờ 1 phút hoặc chuyển sang model khác."

            # 3. Xử lý lỗi API Key
            if "401" in err or "invalid_api_key" in err or "Incorrect API key" in err:
                return None, f"API Key không hợp lệ cho {provider}. (Nếu dùng OpenRouter, hãy đảm bảo chọn đúng Provider: OpenRouter hoặc dán key dạng sk-or-v1-...)."

            # 4. Xử lý lỗi 503 (Server quá tải)
            if "503" in err or "UNAVAILABLE" in err:
                if attempt < max_retries - 1:
                    wait_time = 2 * (attempt + 1)
                    time.sleep(wait_time)
                    continue
            # 5. Xử lý lỗi kết nối Ollama khi chưa bật ứng dụng
            if provider == "Ollama (Local AI Offline)" and any(k in err.lower() for k in ["connection refused", "connecterror", "failed to connect", "connection error"]):
                return None, "Không thể kết nối đến Ollama tại http://localhost:11434. Vui lòng đảm bảo bạn đã mở ứng dụng Ollama trên máy tính của bạn."

            else:
                return None, f"Lỗi {provider} ({model_name}): {err}"

    return None, f"Server {provider} quá tải sau {max_retries} lần thử: {last_error}"
