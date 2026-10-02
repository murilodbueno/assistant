from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request

from .business import Business, load_business
from .calendar import CalendarClient
from .config import load_settings
from .orchestrator import Orchestrator
from .reminders import reminder_loop
from .store import Store
from .whatsapp import WhatsAppClient, verify_hmac

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("petshop.main")

settings = load_settings()
business = load_business(settings.business_file)
store = Store(settings.db_path)
store.init_db()
calendar = CalendarClient(settings)
whatsapp = WhatsAppClient(settings)
orchestrator = Orchestrator(settings, business, store, calendar, whatsapp)


def _sync_business(reloaded: Business) -> None:
    global business
    business = reloaded


orchestrator.on_business_reload = _sync_business
_reminder_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _reminder_task
    _reminder_task = asyncio.create_task(
        reminder_loop(settings, store, whatsapp, lambda: orchestrator.business)
    )
    yield
    if _reminder_task:
        _reminder_task.cancel()
        try:
            await _reminder_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Pet Shop Assistant", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhook/waha")
async def waha_webhook(
    request: Request,
    x_webhook_hmac: str | None = Header(default=None, alias="X-Webhook-Hmac"),
) -> dict[str, str]:
    body = await request.body()
    if settings.waha_hmac_key and not verify_hmac(body, x_webhook_hmac or "", settings.waha_hmac_key):
        raise HTTPException(status_code=401, detail="invalid hmac")
    payload: dict[str, Any] = await request.json()
    parsed = whatsapp.parse_incoming(payload)
    if parsed is None:
        return {"status": "ignored"}
    phone, text = parsed
    await orchestrator.handle_webhook_message(phone, text)
    return {"status": "ok"}


def run() -> None:
    import uvicorn

    uvicorn.run("petshop.main:app", host="0.0.0.0", port=8000, reload=False)
