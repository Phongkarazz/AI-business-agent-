"""
Multi-provider LLM client supporting Google Gemini, OpenRouter, and Alibaba Qwen (OpenAI-compatible).
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
    """Trích xuất nội dung sạch từ phản hồi của mô hình (bóc tách code block nếu có)."""
    if not raw:
        return ""

    # Nếu có markdown code block ```sql ... ``` hoặc ```json ... ``` hoặc ``` ... ```
    match = re.search(r"```(?:sql|json)?\s*([\s\S]*?)\s*```", raw, re.IGNORECASE)
    if match:
        extracted = match.group(1).strip()
    else:
        extracted = raw.strip()

    # Loại bỏ prefix sql\n hoặc json\n nếu sót lại ở đầu chuỗi
    extracted = re.sub(r"^(?:sql\s*\n|json\s*\n)", "", extracted, flags=re.IGNORECASE).strip()
    return extracted


def get_llm_client(provider: str, api_key: str, base_url: str = None):
    """Tạo client AI tương ứng với provider được chọn (Gemini, OpenRouter, Qwen)."""
    if not api_key:
        raise ValueError("API Key không được để trống.")

    if provider == "Gemini (Google)":
        return genai.Client(api_key=api_key)
    elif provider == "OpenRouter":
        if _OpenAIClient is None:
            raise ImportError("Thiếu thư viện `openai`. Vui lòng cài đặt: pip install openai")
        target_url = (base_url or "").strip() or OPENROUTER_BASE_URL
        return _OpenAIClient(
            api_key=api_key,
            base_url=target_url,
            default_headers={
                "HTTP-Referer": "https://localhost:8501",
                "X-Title": "AI Business Agent",
            }
        )
    elif provider == "Qwen (Alibaba Cloud)":
        if _OpenAIClient is None:
            raise ImportError("Thiếu thư viện `openai`. Vui lòng cài đặt: pip install openai")
        target_url = (base_url or "").strip() or DASHSCOPE_BASE_URL
        return _OpenAIClient(api_key=api_key, base_url=target_url)
    else:
        raise ValueError(f"Provider không được hỗ trợ: {provider}")


def _call_gemini_impl(client, model_name: str, prompt: str) -> str:
    response = client.models.generate_content(model=model_name, contents=prompt)
    return response.text


def _call_openai_compatible_impl(client, model_name: str, prompt: str) -> str:
    completion = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
    )
    return completion.choices[0].message.content


def call_llm(client, provider: str, model_name: str, prompt: str, max_retries: int = 3) -> tuple[str | None, str | None]:
    """Gọi LLM với cơ chế retry và trả về (kết_quả, thông_báo_lỗi)."""
    if not client:
        return None, "Chưa khởi tạo client AI."

    impl = _call_gemini_impl if provider == "Gemini (Google)" else _call_openai_compatible_impl

    last_error = None
    for attempt in range(max_retries):
        try:
            raw = impl(client, model_name, prompt)
            cleaned = extract_clean_content(raw)
            return cleaned, None
        except Exception as e:
            err = str(e)
            last_error = err
            if "429" in err or "RESOURCE_EXHAUSTED" in err or "RateLimit" in err or "Throttling" in err or "insufficient_quota" in err:
                return None, f"Hết quota {provider} hoặc đạt giới hạn gọi. Vui lòng kiểm tra lại tài khoản hoặc đổi Provider."
            if "503" in err or "UNAVAILABLE" in err:
                wait = 2 * (attempt + 1)
                time.sleep(wait)
            else:
                return None, f"Lỗi {provider}: {err}"

    return None, f"Server {provider} quá tải sau {max_retries} lần thử: {last_error}"
