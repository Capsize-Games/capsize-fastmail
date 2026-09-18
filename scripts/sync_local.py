#!/usr/bin/env python3
"""Mirror the whole Fastmail account into a local SQLite database.

First run does a full backfill of every mailbox (skipping only trash/
junk, which the client already excludes); every run after that uses
JMAP delta sync (`Email/changes`) to pull only what changed. Meant to
run on a schedule (cron/systemd timer) for a standing local mirror -
see `README.md` for the deployment recipe.

Env vars:
    FASTMAIL_API_TOKEN   required - a Mail-scoped JMAP API token.
    FASTMAIL_SYNC_DB      optional - defaults to
                          ~/.local/share/capsize-fastmail/fastmail.db
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import _storage  # noqa: E402

from capsize_fastmail import (  # noqa: E402
    FastmailAPIError,
    FastmailAuthError,
    FastmailJMAPProvider,
)
from capsize_fastmail.concurrency import BATCH_SIZE  # noqa: E402

logger = logging.getLogger("capsize_fastmail.sync_local")

_DEFAULT_DB = "~/.local/share/capsize-fastmail/fastmail.db"
# Matches capsize_fastmail.concurrency.BATCH_SIZE - this script calls
# provider.get_emails() directly (it's already async end-to-end, so
# the sync fetch_email_bodies helper - which spins up its own event
# loop for non-async callers like a Celery task - doesn't apply here
# and would fail inside one that's already running). One page is one
# JMAP request, so it needs to respect the same per-request limit
# fetch_email_bodies's own batching exists to stay under.
_PAGE_SIZE = BATCH_SIZE


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


async def _store_page(
    provider: FastmailJMAPProvider,
    conn: sqlite3.Connection,
    ids: list[str],
    mailbox_roles: dict[str, str],
    mailbox_id: str,
    position: int,
) -> None:
    messages = await provider.get_emails(ids, mailbox_roles=mailbox_roles)
    _storage.upsert_messages(conn, messages, _now())
    logger.info(
        "backfilled %d messages (mailbox %s, position %d)",
        len(messages), mailbox_id, position,
    )


async def _backfill_mailbox(
    provider: FastmailJMAPProvider,
    conn: sqlite3.Connection,
    mailbox_id: str,
    mailbox_roles: dict[str, str],
) -> str | None:
    """Page through one mailbox, storing every message.

    Returns the last `query_state` seen - any mailbox's works as the
    seed for delta sync, since it's a token for the whole Email data
    type, not a per-mailbox one.
    """
    position = 0
    last_state: str | None = None
    while True:
        page = await provider.query_email_ids(
            mailbox_id, position=position, limit=_PAGE_SIZE
        )
        last_state = page.query_state or last_state
        if not page.ids:
            break
        await _store_page(
            provider, conn, page.ids, mailbox_roles, mailbox_id, position
        )
        if len(page.ids) < _PAGE_SIZE:
            break
        position += _PAGE_SIZE
    return last_state


async def _full_backfill(
    provider: FastmailJMAPProvider, conn: sqlite3.Connection
) -> None:
    mailboxes = await provider.list_mailboxes()
    mailbox_roles = {mb.id: mb.role for mb in mailboxes}
    last_state: str | None = None
    for mailbox in mailboxes:
        state = await _backfill_mailbox(
            provider, conn, mailbox.id, mailbox_roles
        )
        last_state = state or last_state
    if last_state:
        _storage.set_sync_state(conn, last_state)
    else:
        logger.warning(
            "backfill finished but no queryState was returned - "
            "delta sync cannot resume from this run"
        )


async def _delta_sync(
    provider: FastmailJMAPProvider,
    conn: sqlite3.Connection,
    since_state: str,
) -> None:
    mailboxes = await provider.list_mailboxes()
    mailbox_roles = {mb.id: mb.role for mb in mailboxes}
    changes = await provider.get_changes(since_state)
    changed_ids = list(set(changes.created) | set(changes.updated))
    for i in range(0, len(changed_ids), BATCH_SIZE):
        batch = changed_ids[i:i + BATCH_SIZE]
        messages = await provider.get_emails(
            batch, mailbox_roles=mailbox_roles
        )
        _storage.upsert_messages(conn, messages, _now())
    _storage.delete_messages(conn, changes.destroyed)
    logger.info(
        "delta sync: %d new/updated, %d removed",
        len(changed_ids), len(changes.destroyed),
    )
    if changes.new_state:
        _storage.set_sync_state(conn, changes.new_state)


async def _run(token: str, db_path: Path) -> int:
    provider = FastmailJMAPProvider(token)
    conn = _storage.open_db(db_path)
    try:
        since_state = _storage.get_sync_state(conn)
        if since_state is None:
            logger.info("no saved state - running a full backfill")
            await _full_backfill(provider, conn)
        else:
            await _delta_sync(provider, conn, since_state)
    except FastmailAuthError:
        logger.error("Fastmail rejected the API token")
        return 1
    except FastmailAPIError as exc:
        logger.error("Fastmail API error: %s", exc)
        return 1
    logger.info(
        "sync complete - %d messages stored", _storage.message_count(conn)
    )
    conn.close()
    return 0


def main() -> int:
    """Run one sync pass; return a process exit code."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    token = os.environ.get("FASTMAIL_API_TOKEN")
    if not token:
        logger.error("FASTMAIL_API_TOKEN is not set")
        return 1
    db_path = Path(os.environ.get("FASTMAIL_SYNC_DB", _DEFAULT_DB))
    return asyncio.run(_run(token, db_path))


if __name__ == "__main__":
    raise SystemExit(main())
