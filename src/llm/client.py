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

from src.config import DASHSCOPE_BASE_URL, OPENROUTER_BASE_URL


def extract_clean_content(raw: str) -> str:
    """Trích xuất nội dung sạch từ phản hồi của mô hình (bóc tách code block, loại bỏ comment mở đầu)."""
    if not raw:
        return ""

    # 1. Nếu có markdown code block ```sql ... ``` hoặc ```json ... ``` hoặc ``` ... ```
    match = re.search(r"```(?:sql|json)?\s*([\s\S]*?)\s*```", raw, re.IGNORECASE)
    if match:
        extracted = match.group(1).strip()
    else:
        extracted = raw.strip()

    # 2. Loại bỏ các tiền tố giải thích hoặc comment mở đầu (#, --, /* */) trước câu lệnh chính
    extracted = re.sub(r"^\s*/\*.*?\*/\s*", "", extracted, flags=re.DOTALL)
    lines = extracted.splitlines()
    cleaned_lines = []
    found_sql_start = False
    for line in lines:
        stripped_line = line.strip()
        if not found_sql_start:
            if not stripped_line or stripped_line.startswith("#") or stripped_line.startswith("--") or stripped_line.startswith("//"):
                continue
            if stripped_line.lower() in ("sql", "json"):
                continue
            found_sql_start = True
        cleaned_lines.append(line)

    extracted = "\n".join(cleaned_lines).strip()
    return extracted


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
    """Tạo client AI tương ứng với provider được chọn với tính năng tự động nhận diện OpenRouter."""
    api_key = (api_key or "").strip()
    if not api_key:
        raise ValueError("API Key không được để trống.")

    base_url_str = (base_url or "").strip().lower()

    is_openrouter = (
        provider == "OpenRouter"
        or api_key.startswith("sk-or-v1-")
        or "openrouter.ai" in base_url_str
    )

    if provider == "Gemini (Google)" and not is_openrouter:
        return genai.Client(api_key=api_key)
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
    # Chuẩn hóa tên model Gemini và tự động chuyển tiếp nếu gặp model cũ bị 404
    clean_model = (model_name or "").strip().lower()
    if clean_model in ("gemini-2.5-flash", "gemini-flash", "gemini-pro", ""):
        clean_model = "gemini-2.0-flash"

    target_models = [clean_model]
    for fallback in ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]:
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
            if "404" in err_str or "not_found" in err_str or "no longer available" in err_str:
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


def call_llm(client, provider: str, model_name: str, prompt: str, max_retries: int = 3) -> tuple[str | None, str | None]:
    """Gọi LLM với cấu hình max_tokens tối ưu (tránh lỗi 402 OpenRouter) và cơ chế tự động giảm tokens."""
    if not client:
        return None, "Chưa khởi tạo client AI."

    is_openrouter = (
        provider == "OpenRouter"
        or ("openrouter.ai" in str(getattr(client, "base_url", "")).lower())
    )

    if is_openrouter:
        model_name = normalize_model_for_openrouter(model_name)

    impl = _call_gemini_impl if (provider == "Gemini (Google)" and not is_openrouter) else _call_openai_compatible_impl

    current_max_tokens = 2048
    last_error = None

    for attempt in range(max_retries):
        try:
            raw = impl(client, model_name, prompt, max_tokens=current_max_tokens)
            cleaned = extract_clean_content(raw)
            return cleaned, None
        except Exception as e:
            err = str(e)
            last_error = err

            # Tự động bắt lỗi 402 OpenRouter do vượt quá trần credit khi đặt max_tokens lớn
            if "402" in err or "fewer max_tokens" in err or "can only afford" in err:
                if current_max_tokens > 512:
                    current_max_tokens = 1024 if current_max_tokens > 1024 else 512
                    time.sleep(1)
                    continue
                return None, f"Tài khoản OpenRouter của bạn đã hết số dư ($0.00). Vui lòng nạp thêm credit tại https://openrouter.ai/settings/credits để tiếp tục."

            if "429" in err or "RESOURCE_EXHAUSTED" in err or "RateLimit" in err or "Throttling" in err or "insufficient_quota" in err:
                return None, f"Hết quota hoặc đạt giới hạn gọi ({provider} - {model_name}). Vui lòng kiểm tra lại số dư hoặc đổi model."
            if "401" in err or "invalid_api_key" in err or "Incorrect API key" in err:
                return None, f"API Key không hợp lệ cho {provider}. (Nếu dùng OpenRouter, hãy đảm bảo chọn đúng Provider: OpenRouter hoặc dán key dạng sk-or-v1-...)."
            if "503" in err or "UNAVAILABLE" in err:
                wait = 2 * (attempt + 1)
                time.sleep(wait)
            else:
                return None, f"Lỗi {provider} ({model_name}): {err}"

    return None, f"Server {provider} quá tải sau {max_retries} lần thử: {last_error}"
