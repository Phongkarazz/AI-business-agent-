"""
Multi-provider LLM client supporting Google Gemini and Alibaba Qwen (OpenAI-compatible).
"""

import time
from google import genai

try:
    from openai import OpenAI as _OpenAIClient
except ImportError:
    _OpenAIClient = None

from src.config import DASHSCOPE_BASE_URL


def get_llm_client(provider: str, api_key: str, base_url: str = DASHSCOPE_BASE_URL):
    """Tạo client AI tương ứng với provider được chọn."""
    if not api_key:
        raise ValueError("API Key không được để trống.")

    if provider == "Gemini (Google)":
        return genai.Client(api_key=api_key)
    elif provider == "Qwen (Alibaba Cloud)":
        if _OpenAIClient is None:
            raise ImportError("Thiếu thư viện `openai`. Vui lòng cài đặt: pip install openai")
        return _OpenAIClient(api_key=api_key, base_url=base_url or DASHSCOPE_BASE_URL)
    else:
        raise ValueError(f"Provider không được hỗ trợ: {provider}")


def _call_gemini_impl(client, model_name: str, prompt: str) -> str:
    response = client.models.generate_content(model=model_name, contents=prompt)
    return response.text


def _call_qwen_impl(client, model_name: str, prompt: str) -> str:
    completion = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
    )
    return completion.choices[0].message.content


def call_llm(client, provider: str, model_name: str, prompt: str, max_retries: int = 3) -> tuple[str | None, str | None]:
    """Gọi LLM với cơ chế retry và trả về (kết_quả, thông_báo_lỗi)."""
    if not client:
        return None, "Chưa khởi tạo client AI."

    impl = _call_gemini_impl if provider == "Gemini (Google)" else _call_qwen_impl

    last_error = None
    for attempt in range(max_retries):
        try:
            raw = impl(client, model_name, prompt)
            cleaned = raw.strip().replace("```sql", "").replace("```json", "").replace("```", "").strip()
            return cleaned, None
        except Exception as e:
            err = str(e)
            last_error = err
            if "429" in err or "RESOURCE_EXHAUSTED" in err or "RateLimit" in err or "Throttling" in err:
                return None, f"Hết quota {provider} hôm nay. Vui lòng tạo key mới hoặc đổi Provider."
            if "503" in err or "UNAVAILABLE" in err:
                wait = 2 * (attempt + 1)
                time.sleep(wait)
            else:
                return None, f"Lỗi {provider}: {err}"

    return None, f"Server {provider} quá tải sau {max_retries} lần thử: {last_error}"
