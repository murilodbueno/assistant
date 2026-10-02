from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock

from petshop.business import load_business
from petshop.calendar import CalendarClient
from petshop.config import Settings


def _settings_without_google() -> Settings:
    return Settings(
        llm_api_key="test-api-key",
        llm_base_url="https://example.com/v1",
        llm_model="test-model",
        llm_timeout_sec=5.0,
        fallback_api_key="",
        fallback_base_url="https://example.com/v1",
        fallback_model="",
        fallback_timeout_sec=5.0,
        waha_url="http://localhost:3000",
        waha_api_key="fake-waha-key",
        waha_session="default",
        waha_hmac_key="fake-hmac-key",
        google_service_account_file=Path("/nonexistent/fake.json"),
        google_calendar_id="",
        owner_phone="5511999999999",
        bot_pause_hours=12.0,
        debounce_sec=0.1,
        reminder_start_hour=9,
        reminder_end_hour=19,
        business_file=Path("business.yaml"),
        db_path=Path("data/test.db"),
        timezone="America/Sao_Paulo",
    )


def test_free_slots_without_google():
    root = Path(__file__).resolve().parents[1]
    business = load_business(root / "business" / "pet_shop.yaml")
    settings = _settings_without_google()
    client = CalendarClient(settings)
    # Tuesday in business.yaml
    day = date(2026, 10, 6)
    slots = client.free_slots(business, day, 60, limit=3)
    assert isinstance(slots, list)


def test_create_event_local_only():
    settings = _settings_without_google()
    client = CalendarClient(settings)
    event_id = client.create_event(
        title="Test",
        description="fake",
        start=datetime(2026, 10, 6, 10, 0),
        end=datetime(2026, 10, 6, 11, 0),
    )
    assert event_id == "local-only"


def test_list_busy_mock():
    settings = _settings_without_google()
    settings = Settings(
        **{**settings.__dict__, "google_calendar_id": "fake-cal@test", "google_service_account_file": Path(__file__)}
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"calendars":{"fake-cal@test":{"busy":[]}}}'
    mock_resp.json.return_value = {"calendars": {"fake-cal@test": {"busy": []}}}

    def fake_request(method, url, headers=None, timeout=None, json=None):
        return mock_resp

    client = CalendarClient(settings, request_fn=fake_request)
    client._token = "fake-token-not-real"
    busy = client.list_busy(
        datetime(2026, 10, 6, 8, 0),
        datetime(2026, 10, 6, 18, 0),
    )
    assert busy == []
