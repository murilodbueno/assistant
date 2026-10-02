from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .config import Settings

log = logging.getLogger("petshop.llm")


@dataclass(frozen=True)
class ChatResult:
    content: str
    model: str
    latency_ms: int


def _post_chat(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    timeout_sec: float,
    json_mode: bool = False,
) -> ChatResult:
    body: dict[str, Any] = {"model": model, "messages": messages, "temperature": 0.2}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    started = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    latency_ms = int((time.monotonic() - started) * 1000)
    content = str(data["choices"][0]["message"]["content"])
    used_model = str(data.get("model") or model)
    return ChatResult(content=content, model=used_model, latency_ms=latency_ms)


def chat(
    settings: Settings,
    messages: list[dict[str, str]],
    *,
    json_mode: bool = False,
    temperature: float | None = None,
) -> ChatResult | None:
    if not settings.llm_api_key:
        log.warning("LLM_API_KEY not configured")
        return None
    try:
        return _post_chat(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            messages=messages,
            timeout_sec=settings.llm_timeout_sec,
            json_mode=json_mode,
        )
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
        log.warning("Primary LLM failed: %s", exc)
        if not settings.fallback_enabled:
            return None
        try:
            return _post_chat(
                base_url=settings.fallback_base_url,
                api_key=settings.fallback_api_key,
                model=settings.fallback_model,
                messages=messages,
                timeout_sec=settings.fallback_timeout_sec,
                json_mode=json_mode,
            )
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, KeyError, json.JSONDecodeError) as fb_exc:
            log.error("Fallback LLM failed: %s", fb_exc)
            return None


def chat_json(settings: Settings, messages: list[dict[str, str]]) -> dict[str, Any] | None:
    result = chat(settings, messages, json_mode=True)
    if result is None:
        return None
    try:
        return json.loads(result.content)
    except json.JSONDecodeError:
        log.warning("LLM returned invalid JSON: %s", result.content[:200])
        return None
