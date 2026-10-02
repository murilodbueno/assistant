from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


@dataclass
class Appointment:
    id: int
    phone: str
    pet_name: str
    service: str
    size: str
    start_ts: float
    end_ts: float
    gcal_event_id: str | None
    status: str


SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    phone TEXT PRIMARY KEY,
    state_json TEXT NOT NULL DEFAULT '{}',
    paused_until REAL NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT NOT NULL,
    pet_name TEXT NOT NULL,
    service TEXT NOT NULL,
    size TEXT NOT NULL,
    start_ts REAL NOT NULL,
    end_ts REAL NOT NULL,
    gcal_event_id TEXT,
    status TEXT NOT NULL DEFAULT 'confirmed',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS handoffs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_phone TEXT NOT NULL,
    question TEXT NOT NULL,
    owner_notified_at REAL,
    owner_reply TEXT,
    resolved_at REAL
);
CREATE TABLE IF NOT EXISTS reminder_log (
    appointment_id INTEGER PRIMARY KEY,
    sent_at REAL NOT NULL,
    FOREIGN KEY (appointment_id) REFERENCES appointments(id)
);
CREATE INDEX IF NOT EXISTS idx_messages_phone ON messages(phone);
CREATE INDEX IF NOT EXISTS idx_appointments_phone ON appointments(phone);
CREATE INDEX IF NOT EXISTS idx_appointments_start ON appointments(start_ts);
CREATE TABLE IF NOT EXISTS admin_sessions (
    phone TEXT PRIMARY KEY,
    state_json TEXT NOT NULL DEFAULT '{}',
    updated_at REAL NOT NULL
);
"""


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    def get_state(self, phone: str) -> dict[str, Any]:
        with self._conn() as conn:
            row = conn.execute("SELECT state_json FROM conversations WHERE phone = ?", (phone,)).fetchone()
        if row is None:
            return {}
        return json.loads(row["state_json"])

    def set_state(self, phone: str, state: dict[str, Any]) -> None:
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO conversations (phone, state_json, paused_until, updated_at)
                VALUES (?, ?, 0, ?)
                ON CONFLICT(phone) DO UPDATE SET state_json = excluded.state_json, updated_at = excluded.updated_at
                """,
                (phone, json.dumps(state), now),
            )

    def is_paused(self, phone: str) -> bool:
        with self._conn() as conn:
            row = conn.execute("SELECT paused_until FROM conversations WHERE phone = ?", (phone,)).fetchone()
        return bool(row and row["paused_until"] > time.time())

    def pause(self, phone: str, until_ts: float) -> None:
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO conversations (phone, state_json, paused_until, updated_at)
                VALUES (?, '{}', ?, ?)
                ON CONFLICT(phone) DO UPDATE SET paused_until = excluded.paused_until, updated_at = excluded.updated_at
                """,
                (phone, until_ts, now),
            )

    def add_message(self, phone: str, role: str, content: str) -> None:
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO messages (phone, role, content, created_at) VALUES (?, ?, ?, ?)",
                (phone, role, content, now),
            )
            conn.execute(
                """
                INSERT INTO conversations (phone, state_json, paused_until, updated_at)
                VALUES (?, '{}', 0, ?)
                ON CONFLICT(phone) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (phone, now),
            )

    def recent_messages(self, phone: str, limit: int = 12) -> list[dict[str, str]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT role, content FROM messages WHERE phone = ? ORDER BY id DESC LIMIT ?",
                (phone, limit),
            ).fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]

    def create_appointment(
        self,
        *,
        phone: str,
        pet_name: str,
        service: str,
        size: str,
        start_ts: float,
        end_ts: float,
        gcal_event_id: str | None = None,
    ) -> int:
        now = time.time()
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO appointments (phone, pet_name, service, size, start_ts, end_ts, gcal_event_id, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'confirmed', ?)
                """,
                (phone, pet_name, service, size, start_ts, end_ts, gcal_event_id, now),
            )
            return int(cur.lastrowid)

    def get_appointment(self, appointment_id: int) -> Appointment | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
        return _row_to_appointment(row) if row else None

    def find_active_appointment(self, phone: str) -> Appointment | None:
        now = time.time()
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM appointments
                WHERE phone = ? AND status = 'confirmed' AND start_ts > ?
                ORDER BY start_ts ASC LIMIT 1
                """,
                (phone, now),
            ).fetchone()
        return _row_to_appointment(row) if row else None

    def update_appointment(
        self,
        appointment_id: int,
        *,
        start_ts: float | None = None,
        end_ts: float | None = None,
        gcal_event_id: str | None = None,
        status: str | None = None,
    ) -> None:
        fields: list[str] = []
        values: list[Any] = []
        if start_ts is not None:
            fields.append("start_ts = ?")
            values.append(start_ts)
        if end_ts is not None:
            fields.append("end_ts = ?")
            values.append(end_ts)
        if gcal_event_id is not None:
            fields.append("gcal_event_id = ?")
            values.append(gcal_event_id)
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if not fields:
            return
        values.append(appointment_id)
        with self._conn() as conn:
            conn.execute(f"UPDATE appointments SET {', '.join(fields)} WHERE id = ?", values)

    def busy_intervals_between(
        self,
        start_ts: float,
        end_ts: float,
        *,
        exclude_id: int | None = None,
    ) -> list[tuple[float, float]]:
        with self._conn() as conn:
            if exclude_id is None:
                rows = conn.execute(
                    """
                    SELECT start_ts, end_ts FROM appointments
                    WHERE status = 'confirmed' AND start_ts < ? AND end_ts > ?
                    """,
                    (end_ts, start_ts),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT start_ts, end_ts FROM appointments
                    WHERE status = 'confirmed' AND start_ts < ? AND end_ts > ? AND id != ?
                    """,
                    (end_ts, start_ts, exclude_id),
                ).fetchall()
        return [(float(row["start_ts"]), float(row["end_ts"])) for row in rows]

    def appointments_between(self, start_ts: float, end_ts: float) -> list[Appointment]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM appointments
                WHERE status = 'confirmed' AND start_ts >= ? AND start_ts < ?
                ORDER BY start_ts
                """,
                (start_ts, end_ts),
            ).fetchall()
        return [_row_to_appointment(row) for row in rows]

    def create_handoff(self, client_phone: str, question: str) -> int:
        now = time.time()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO handoffs (client_phone, question, owner_notified_at) VALUES (?, ?, ?)",
                (client_phone, question, now),
            )
            return int(cur.lastrowid)

    def pending_handoff_for_client(self, client_phone: str) -> sqlite3.Row | None:
        with self._conn() as conn:
            return conn.execute(
                """
                SELECT * FROM handoffs
                WHERE client_phone = ? AND resolved_at IS NULL
                ORDER BY id DESC LIMIT 1
                """,
                (client_phone,),
            ).fetchone()

    def resolve_handoff(self, handoff_id: int, owner_reply: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE handoffs SET owner_reply = ?, resolved_at = ? WHERE id = ?",
                (owner_reply, time.time(), handoff_id),
            )

    def latest_open_handoff(self) -> sqlite3.Row | None:
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM handoffs WHERE resolved_at IS NULL ORDER BY id DESC LIMIT 1",
            ).fetchone()

    def mark_reminder_sent(self, appointment_id: int) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO reminder_log (appointment_id, sent_at) VALUES (?, ?)",
                (appointment_id, time.time()),
            )

    def reminder_sent(self, appointment_id: int) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM reminder_log WHERE appointment_id = ?",
                (appointment_id,),
            ).fetchone()
        return row is not None

    def get_admin_session(self, phone: str) -> dict[str, Any]:
        with self._conn() as conn:
            row = conn.execute("SELECT state_json FROM admin_sessions WHERE phone = ?", (phone,)).fetchone()
        if row is None:
            return {"mode": "idle"}
        return json.loads(row["state_json"])

    def set_admin_session(self, phone: str, state: dict[str, Any]) -> None:
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO admin_sessions (phone, state_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(phone) DO UPDATE SET state_json = excluded.state_json, updated_at = excluded.updated_at
                """,
                (phone, json.dumps(state), now),
            )

    def clear_admin_session(self, phone: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM admin_sessions WHERE phone = ?", (phone,))


def _row_to_appointment(row: sqlite3.Row) -> Appointment:
    return Appointment(
        id=int(row["id"]),
        phone=str(row["phone"]),
        pet_name=str(row["pet_name"]),
        service=str(row["service"]),
        size=str(row["size"]),
        start_ts=float(row["start_ts"]),
        end_ts=float(row["end_ts"]),
        gcal_event_id=row["gcal_event_id"],
        status=str(row["status"]),
    )
