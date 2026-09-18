from __future__ import annotations

import sqlite3
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any
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
    for name, value in overrides.items():
        getattr(provider, name).return_value = value
    return provider


async def test_full_backfill_pages_until_short_page(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _provider()
    full_page = Page(
        ids=[f"id-{i}" for i in range(sync_local._PAGE_SIZE)],
        query_state="state-mid",
    )
    short_page = Page(ids=["id-last"], query_state="state-final")
    empty_page = Page(ids=[], query_state="state-final")
    provider.query_email_ids.side_effect = [
        full_page, short_page,  # mailbox 1
        empty_page,  # mailbox 2
    ]
    monkeypatch.setattr(
        sync_local, "fetch_email_bodies", lambda *a, **k: []
    )

    await sync_local._full_backfill(provider, conn)

    assert _storage.get_sync_state(conn) == "state-final"
    assert provider.query_email_ids.call_count == 3


async def test_delta_sync_upserts_and_deletes(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _provider(
        get_changes=Changes(
            created=["new-1"],
            updated=["upd-1"],
            destroyed=["gone-1"],
            new_state="state-next",
        )
    )
    _storage.upsert_messages(
        conn,
        [EmailMessage(
            provider_id="gone-1", thread_id="t", mailbox_role="",
            from_address="",
        )],
        "2026-01-01T00:00:00Z",
    )
    captured_ids: list[set[str]] = []

    def _fake_fetch(
        _provider: object, ids: set[str], **_kwargs: Any
    ) -> list[object]:
        captured_ids.append(ids)
        return []

    monkeypatch.setattr(sync_local, "fetch_email_bodies", _fake_fetch)

    await sync_local._delta_sync(provider, conn, "state-prev")

    assert captured_ids == [{"new-1", "upd-1"}]
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
