from __future__ import annotations

import sqlite3
import sys
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import _storage  # noqa: E402
import pytest  # noqa: E402
import sync_local  # noqa: E402

from capsize_fastmail.provider import (  # noqa: E402
    Changes,
    EmailMessage,
    Mailbox,
    Page,
)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = _storage.open_db(tmp_path / "fastmail.db")
    yield connection
    connection.close()


def _provider(**overrides: object) -> AsyncMock:
    provider = AsyncMock()
    provider.list_mailboxes.return_value = [
        Mailbox(id="mb-1", name="Inbox", role="inbox"),
        Mailbox(id="mb-2", name="Sent", role="sent"),
    ]
    provider.get_current_state.return_value = "state-final"
    for name, value in overrides.items():
        getattr(provider, name).return_value = value
    return provider


async def test_full_backfill_pages_until_short_page(
    conn: sqlite3.Connection,
) -> None:
    provider = _provider()
    full_page = Page(ids=[f"id-{i}" for i in range(sync_local._PAGE_SIZE)])
    short_page = Page(ids=["id-last"])
    empty_page = Page(ids=[])
    provider.query_email_ids.side_effect = [
        full_page, short_page,  # mailbox 1
        empty_page,  # mailbox 2
    ]
    provider.get_emails.return_value = []

    await sync_local._full_backfill(provider, conn)

    # Seeded from get_current_state(), NOT Page.query_state - see its
    # docstring for why those aren't interchangeable.
    assert _storage.get_sync_state(conn) == "state-final"
    assert provider.get_current_state.await_count == 1
    assert provider.query_email_ids.call_count == 3


async def test_delta_sync_upserts_and_deletes(
    conn: sqlite3.Connection,
) -> None:
    provider = _provider(
        get_changes=Changes(
            created=["new-1"],
            updated=["upd-1"],
            destroyed=["gone-1"],
            new_state="state-next",
        )
    )
    provider.get_emails.return_value = []
    _storage.upsert_messages(
        conn,
        [EmailMessage(
            provider_id="gone-1", thread_id="t", mailbox_role="",
            from_address="",
        )],
        "2026-01-01T00:00:00Z",
    )

    await sync_local._delta_sync(provider, conn, "state-prev")

    captured_ids = provider.get_emails.call_args.args[0]
    assert set(captured_ids) == {"new-1", "upd-1"}
    assert _storage.message_count(conn) == 0
    assert _storage.get_sync_state(conn) == "state-next"


async def test_run_requires_no_state_before_backfill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "fastmail.db"
    calls: list[str] = []
    monkeypatch.setattr(
        sync_local,
        "_full_backfill",
        AsyncMock(side_effect=lambda *a: calls.append("backfill")),
    )
    monkeypatch.setattr(
        sync_local,
        "_delta_sync",
        AsyncMock(side_effect=lambda *a: calls.append("delta")),
    )

    exit_code = await sync_local._run("token", db_path)

    assert exit_code == 0
    assert calls == ["backfill"]
