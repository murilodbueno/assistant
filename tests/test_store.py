from pathlib import Path

from petshop.store import Store


def test_store_messages_and_appointment(tmp_path: Path):
    db = tmp_path / "test.db"
    store = Store(db)
    store.init_db()
    store.add_message("5511888888888", "user", "ola")
    store.add_message("5511888888888", "assistant", "oi")
    msgs = store.recent_messages("5511888888888")
    assert len(msgs) == 2
    appt_id = store.create_appointment(
        phone="5511888888888",
        pet_name="Rex",
        service="Banho",
        size="grande",
        start_ts=1_700_000_000.0,
        end_ts=1_700_000_600.0,
    )
    appt = store.get_appointment(appt_id)
    assert appt is not None
    assert appt.pet_name == "Rex"
    store.mark_reminder_sent(appt_id)
    assert store.reminder_sent(appt_id)
