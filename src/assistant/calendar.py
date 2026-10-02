from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from .business import Business
from .config import Settings

log = logging.getLogger("assistant.calendar")

SCOPES = ["https://www.googleapis.com/auth/calendar"]
RequestFn = Callable[..., Any]


@dataclass(frozen=True)
class Slot:
    start: datetime
    end: datetime


class CalendarClient:
    def __init__(self, settings: Settings, request_fn: RequestFn | None = None) -> None:
        self.settings = settings
        self._request_fn = request_fn or requests.request
        self._token: str | None = None

    @property
    def enabled(self) -> bool:
        return self.settings.google_enabled

    def _auth_header(self) -> dict[str, str]:
        if self._token is None:
            creds = service_account.Credentials.from_service_account_file(
                str(self.settings.google_service_account_file),
                scopes=SCOPES,
            )
            creds.refresh(Request())
            self._token = creds.token
        return {"Authorization": f"Bearer {self._token}"}

    def _api(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"https://www.googleapis.com/calendar/v3{path}"
        headers = {**self._auth_header(), "Content-Type": "application/json"}
        resp = self._request_fn(method, url, headers=headers, timeout=30, **kwargs)
        if resp.status_code >= 400:
            raise RuntimeError(f"Google Calendar API {resp.status_code}: {resp.text[:300]}")
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    def list_busy(self, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
        if not self.enabled:
            return []
        body = {
            "timeMin": start.isoformat(),
            "timeMax": end.isoformat(),
            "items": [{"id": self.settings.google_calendar_id}],
        }
        data = self._api("POST", "/freeBusy", json=body)
        busy = data.get("calendars", {}).get(self.settings.google_calendar_id, {}).get("busy", [])
        tz = self.settings.tz
        return [
            (datetime.fromisoformat(item["start"].replace("Z", "+00:00")).astimezone(tz),
             datetime.fromisoformat(item["end"].replace("Z", "+00:00")).astimezone(tz))
            for item in busy
        ]

    def free_slots(
        self,
        business: Business,
        day: date,
        duration_min: int,
        *,
        limit: int = 5,
        extra_busy: list[tuple[datetime, datetime]] | None = None,
    ) -> list[Slot]:
        tz = self.settings.tz
        weekday = day.weekday()
        ranges = business.hours.get(weekday, [])
        if not ranges:
            return []
        now = datetime.now(tz)
        min_start = now + timedelta(hours=business.min_notice_hours)
        max_start = now + timedelta(days=business.max_days_ahead)
        day_start = datetime.combine(day, time.min, tzinfo=tz)
        day_end = day_start + timedelta(days=1)
        busy = list(self.list_busy(day_start, day_end) if self.enabled else [])
        if extra_busy:
            busy.extend(extra_busy)
        slots: list[Slot] = []
        step = timedelta(minutes=business.slot_step_min)
        duration = timedelta(minutes=duration_min)
        for open_time, close_time in ranges:
            cursor = datetime.combine(day, open_time, tzinfo=tz)
            end_limit = datetime.combine(day, close_time, tzinfo=tz)
            while cursor + duration <= end_limit:
                slot_end = cursor + duration
                if cursor >= min_start and cursor <= max_start and not _overlaps(cursor, slot_end, busy):
                    slots.append(Slot(start=cursor, end=slot_end))
                    if len(slots) >= limit:
                        return slots
                cursor += step
        return slots

    def create_event(
        self,
        *,
        title: str,
        description: str,
        start: datetime,
        end: datetime,
    ) -> str:
        if not self.enabled:
            return "local-only"
        body = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start.isoformat(), "timeZone": str(self.settings.timezone)},
            "end": {"dateTime": end.isoformat(), "timeZone": str(self.settings.timezone)},
        }
        data = self._api(
            "POST",
            f"/calendars/{self.settings.google_calendar_id}/events",
            json=body,
        )
        return str(data.get("id", ""))

    def update_event(self, event_id: str, *, start: datetime, end: datetime) -> None:
        if not self.enabled or event_id == "local-only":
            return
        body = {
            "start": {"dateTime": start.isoformat(), "timeZone": str(self.settings.timezone)},
            "end": {"dateTime": end.isoformat(), "timeZone": str(self.settings.timezone)},
        }
        self._api(
            "PATCH",
            f"/calendars/{self.settings.google_calendar_id}/events/{event_id}",
            json=body,
        )

    def delete_event(self, event_id: str) -> None:
        if not self.enabled or event_id == "local-only":
            return
        self._api("DELETE", f"/calendars/{self.settings.google_calendar_id}/events/{event_id}")


def _overlaps(start: datetime, end: datetime, busy: list[tuple[datetime, datetime]]) -> bool:
    for b_start, b_end in busy:
        if start < b_end and end > b_start:
            return True
    return False
