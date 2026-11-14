"""Unified, deterministic headless LLM client adapter for DataMate.

Reuses Veraxus's provider routing (`src.llm.client.get_llm_client`) when available
while preserving raw structured JSON/SQL outputs (avoiding SQL-only post-stripping
on JSON responses) and supporting offline Ollama / vLLM / OpenAI-compatible endpoints.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Protocol

try:
    from openai import OpenAI as _OpenAIClient
except ImportError:
    _OpenAIClient = None

try:
    from src.llm.client import get_llm_client as _veraxus_get_llm_client
    from src.config import DASHSCOPE_BASE_URL, OLLAMA_BASE_URL, OPENROUTER_BASE_URL
except ImportError:
    _veraxus_get_llm_client = None
    OLLAMA_BASE_URL = "http://localhost:11434/v1"
    OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
    DASHSCOPE_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

_THINK_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
_CODE_FENCE_RE = re.compile(r"```(?:json|sql)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


class LLMBackend(Protocol):
    """Minimal protocol implemented by real providers and test mocks."""

    model_name: str

    def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.0,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> str:
        ...


@dataclass
class LLMConfig:
    provider: str = "Ollama (Local AI Offline)"
    model_name: str = "qwen2.5-coder:3b"
    api_key: str = ""
    base_url: str = ""
    timeout: float = 60.0
    max_retries: int = 3
    temperature: float = 0.0

    @classmethod
    def from_env(
        cls,
        provider: Optional[str] = None,
        model_name: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> "LLMConfig":
        """Resolve provider/model/endpoint cleanly from args, env vars, or saved config."""
        prov = (provider or os.environ.get("DATAMATE_PROVIDER") or "").strip()
        model = (model_name or os.environ.get("DATAMATE_MODEL") or "").strip()
        url = (base_url or os.environ.get("DATAMATE_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or "").strip()
        key = (api_key or os.environ.get("DATAMATE_API_KEY") or "").strip()

        if not key:
            if "openrouter" in prov.lower():
                key = os.environ.get("OPENROUTER_API_KEY", "").strip()
            elif "gemini" in prov.lower():
                key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
            elif "qwen" in prov.lower() or "dashscope" in prov.lower():
                key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
            else:
                key = (
                    os.environ.get("OPENAI_API_KEY")
                    or os.environ.get("GEMINI_API_KEY")
                    or os.environ.get("OPENROUTER_API_KEY")
                    or ""
                ).strip()

        if not prov:
            if url and "11434" not in url:
                prov = "OpenAI-Compatible"
            elif os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
                prov = "Gemini (Google)"
            elif os.environ.get("OPENROUTER_API_KEY"):
                prov = "OpenRouter"
            else:
                prov = "Ollama (Local AI Offline)"

        if not model:
            if prov == "Gemini (Google)":
                model = "gemini-3.7-flash"
            elif prov == "OpenRouter":
                model = "qwen/qwen-2.5-coder-32b-instruct"
            else:
                model = "qwen2.5-coder:3b"

        if not url and prov == "Ollama (Local AI Offline)":
            url = OLLAMA_BASE_URL

        return cls(
            provider=prov,
            model_name=model,
            api_key=key,
            base_url=url,
        )


def strip_thinking(text: str) -> str:
    """Remove <think>...</think> blocks without corrupting JSON/SQL content."""
    if not text:
        return ""
    cleaned = _THINK_RE.sub("", text).strip()
    if not cleaned and "<think>" in text:
        m = _CODE_FENCE_RE.search(text)
        if m:
            return m.group(1).strip()
    return cleaned


def extract_json_object(raw: str) -> Optional[Dict[str, Any]]:
    """Robustly parse the first JSON object from an LLM response."""
    text = strip_thinking(raw)
    if not text:
        return None

    m = _CODE_FENCE_RE.search(text)
    candidates = [m.group(1).strip(), text] if m else [text]
    for cand in candidates:
        try:
            obj = json.loads(cand)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

    # Balanced brace scan fallback for prose-wrapped JSON
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        escape = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if escape:
                escape = False
                continue
            if ch == "\\" and in_str:
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    snippet = text[start : idx + 1]
                    try:
                        obj = json.loads(snippet)
                        if isinstance(obj, dict):
                            return obj
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None


class MultiProviderLLMBackend:
    """Deterministic multi-provider backend supporting Ollama, OpenAI-compatible/vLLM, OpenRouter, Gemini."""

    def __init__(self, config: Optional[LLMConfig] = None) -> None:
        self.config = config or LLMConfig.from_env()
        self.model_name = self.config.model_name
        self._client = None
        self._init_client()

    def _init_client(self) -> None:
        prov = self.config.provider
        if prov == "OpenAI-Compatible":
            if _OpenAIClient is not None:
                self._client = _OpenAIClient(
                    api_key=self.config.api_key or "EMPTY",
                    base_url=self.config.base_url.rstrip("/"),
                    timeout=self.config.timeout,
                    max_retries=1,
                )
            return

        if _veraxus_get_llm_client is not None:
            try:
                self._client = _veraxus_get_llm_client(
                    provider=prov,
                    api_key=self.config.api_key or ("ollama" if "ollama" in prov.lower() else ""),
                    base_url=self.config.base_url or None,
                )
                return
            except Exception:
                self._client = None

        if _OpenAIClient is not None and ("ollama" in prov.lower() or self.config.base_url):
            base = (self.config.base_url or OLLAMA_BASE_URL).rstrip("/")
            self._client = _OpenAIClient(
                api_key=self.config.api_key or "ollama",
                base_url=base,
                timeout=self.config.timeout,
                max_retries=1,
            )

    def _http_openai_chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        json_mode: bool = False,
    ) -> str:
        base = (self.config.base_url or OLLAMA_BASE_URL).rstrip("/")
        if not base.endswith("/v1") and "ollama" in self.config.provider.lower():
            base = f"{base}/v1"
        url = f"{base}/chat/completions"
        payload: Dict[str, Any] = {
            "model": self.config.model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if json_mode and exc.code in (400, 422):
                payload.pop("response_format", None)
                req2 = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers=headers,
                    method="POST",
                )
                with urllib.request.urlopen(req2, timeout=self.config.timeout) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
            else:
                raise
        return body["choices"][0]["message"]["content"]

    def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: Optional[float] = None,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> str:
        temp = self.config.temperature if temperature is None else temperature
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        last_err: Optional[Exception] = None
        for attempt in range(self.config.max_retries):
            try:
                if self.config.provider == "Gemini (Google)" and self._client is not None:
                    full_prompt = f"{system_prompt}\n\n{prompt}".strip() if system_prompt else prompt
                    try:
                        from google.genai import types
                        cfg_kwargs: Dict[str, Any] = {
                            "max_output_tokens": max_tokens,
                            "temperature": temp,
                        }
                        if json_mode:
                            cfg_kwargs["response_mime_type"] = "application/json"
                        cfg = types.GenerateContentConfig(**cfg_kwargs)
                        resp = self._client.models.generate_content(
                            model=self.config.model_name,
                            contents=full_prompt,
                            config=cfg,
                        )
                    except Exception:
                        resp = self._client.models.generate_content(
                            model=self.config.model_name,
                            contents=full_prompt,
                        )
                    return strip_thinking(getattr(resp, "text", "") or "")

                if self._client is not None and hasattr(self._client, "chat"):
                    create_kwargs: Dict[str, Any] = {
                        "model": self.config.model_name,
                        "messages": messages,
                        "temperature": temp,
                        "max_tokens": max_tokens,
                    }
                    if json_mode:
                        create_kwargs["response_format"] = {"type": "json_object"}
                    try:
                        comp = self._client.chat.completions.create(**create_kwargs)
                    except Exception as sdk_exc:
                        if json_mode and "response_format" in str(sdk_exc).lower():
                            create_kwargs.pop("response_format", None)
                            comp = self._client.chat.completions.create(**create_kwargs)
                        else:
                            raise
                    return strip_thinking(comp.choices[0].message.content or "")

                return strip_thinking(self._http_openai_chat(messages, temp, max_tokens, json_mode=json_mode))

            except (urllib.error.URLError, TimeoutError, Exception) as exc:
                last_err = exc
                if attempt < self.config.max_retries - 1:
                    time.sleep(min(2 ** attempt, 4))
                    continue
                raise RuntimeError(
                    f"LLM call failed ({self.config.provider}/{self.config.model_name}): {exc}"
                ) from exc

        raise RuntimeError(f"LLM call failed: {last_err}")


class MockLLMBackend:
    """Deterministic stub backend for unit tests without external API or Ollama."""

    def __init__(self, handler: Callable[[str, str], str], model_name: str = "mock-llm") -> None:
        self._handler = handler
        self.model_name = model_name
        self.calls: List[Dict[str, str]] = []

    def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.0,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> str:
        self.calls.append({"system_prompt": system_prompt, "prompt": prompt})
        return self._handler(prompt, system_prompt)
