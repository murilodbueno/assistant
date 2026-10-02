from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

import requests

from .config import Settings

log = logging.getLogger("assistant.whatsapp")


def verify_hmac(body: bytes, signature: str, secret: str) -> bool:
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha512).hexdigest()
    provided = signature.removeprefix("sha512=").strip()
    return hmac.compare_digest(expected, provided)


class WhatsAppClient:
    def __init__(self, settings: Settings, request_fn: Any | None = None) -> None:
        self.settings = settings
        self._request = request_fn or requests.post

    def _chat_id(self, phone: str) -> str:
        digits = "".join(ch for ch in phone if ch.isdigit())
        return f"{digits}@c.us"

    def send_text(self, phone: str, text: str) -> bool:
        if not self.settings.waha_api_key:
            log.info("WAHA not configured; would send to %s: %s", phone, text[:80])
            return False
        url = f"{self.settings.waha_url}/api/sendText"
        payload = {
            "session": self.settings.waha_session,
            "chatId": self._chat_id(phone),
            "text": text,
        }
        headers = {"X-Api-Key": self.settings.waha_api_key, "Content-Type": "application/json"}
        try:
            resp = self._request(url, json=payload, headers=headers, timeout=15)
            if hasattr(resp, "status_code") and resp.status_code >= 400:
                log.error("WAHA sendText failed: %s", getattr(resp, "text", resp))
                return False
            return True
        except requests.RequestException as exc:
            log.error("WAHA sendText error: %s", exc)
            return False

    def parse_incoming(self, payload: dict[str, Any]) -> tuple[str, str] | None:
        """Extract (phone, text) from WAHA webhook payload."""
        event = payload.get("event") or payload.get("type") or ""
        if event and event not in ("message", "message.any"):
            return None
        data = payload.get("payload") or payload
        if data.get("fromMe"):
            return None
        body = data.get("body") or data.get("text") or ""
        if not body or not isinstance(body, str):
            return None
        sender = data.get("from") or data.get("author") or ""
        phone = "".join(ch for ch in str(sender) if ch.isdigit())
        if not phone:
            return None
        return phone, body.strip()
