from __future__ import annotations

import sqlite3
import sys
from collections.abc import Iterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import _storage  # noqa: E402
import pytest  # noqa: E402

from capsize_fastmail.provider import EmailMessage  # noqa: E402


def _message(provider_id: str, **overrides: object) -> EmailMessage:
    defaults: dict[str, object] = {
        "provider_id": provider_id,
        "thread_id": f"t-{provider_id}",
        "mailbox_role": "sent",
        "from_address": "joe@example.com",
        "from_name": "Joe",
        "to_addresses": [{"address": "a@example.com", "name": "A"}],
        "cc_addresses": [],
        "subject": "Hello",
        "sent_at": "2026-01-01T00:00:00Z",
        "has_attachments": False,
        "body_text": "hi there",
        "body_html": "<p>hi there</p>",
    }
    defaults.update(overrides)
    return EmailMessage(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = _storage.open_db(tmp_path / "sub" / "fastmail.db")
    yield connection
    connection.close()


def test_open_db_creates_parent_dirs(tmp_path: Path) -> None:
    db_path = tmp_path / "a" / "b" / "fastmail.db"
    conn = _storage.open_db(db_path)
    assert db_path.exists()
    conn.close()


def test_sync_state_round_trips(conn: sqlite3.Connection) -> None:
    assert _storage.get_sync_state(conn) is None
    _storage.set_sync_state(conn, "state-1")
    assert _storage.get_sync_state(conn) == "state-1"
    _storage.set_sync_state(conn, "state-2")
    assert _storage.get_sync_state(conn) == "state-2"


def test_upsert_messages_inserts_and_updates(
    conn: sqlite3.Connection,
) -> None:
    _storage.upsert_messages(conn, [_message("m1")], "2026-01-01T00:00:00Z")
    assert _storage.message_count(conn) == 1

    updated = _message("m1", subject="Changed")
    _storage.upsert_messages(conn, [updated], "2026-01-02T00:00:00Z")
    assert _storage.message_count(conn) == 1
    row = conn.execute(
        "SELECT subject FROM messages WHERE provider_id = 'm1'"
    ).fetchone()
    assert row[0] == "Changed"


def test_upsert_messages_empty_list_is_a_noop(
    conn: sqlite3.Connection,
) -> None:
    _storage.upsert_messages(conn, [], "2026-01-01T00:00:00Z")
    assert _storage.message_count(conn) == 0


def test_delete_messages_removes_rows(conn: sqlite3.Connection) -> None:
    _storage.upsert_messages(
        conn, [_message("m1"), _message("m2")], "2026-01-01T00:00:00Z"
    )
    _storage.delete_messages(conn, ["m1"])
    assert _storage.message_count(conn) == 1
    row = conn.execute("SELECT provider_id FROM messages").fetchone()
    assert row[0] == "m2"


def test_delete_messages_empty_list_is_a_noop(
    conn: sqlite3.Connection,
) -> None:
    _storage.upsert_messages(conn, [_message("m1")], "2026-01-01T00:00:00Z")
    _storage.delete_messages(conn, [])
    assert _storage.message_count(conn) == 1
