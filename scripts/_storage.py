"""SQLite storage for a local mirror of synced messages.

Deliberately outside the `capsize_fastmail` package itself - that
package's own boundary is "no database layer, host decides what to
persist" (see its README). This is one such host, living in the same
repo as a convenience since the sync tool is only useful paired with
the client it consumes.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from capsize_fastmail.provider import EmailMessage

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS messages (
    provider_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    mailbox_role TEXT NOT NULL,
    from_address TEXT NOT NULL,
    from_name TEXT NOT NULL,
    to_addresses TEXT NOT NULL,
    cc_addresses TEXT NOT NULL,
    subject TEXT NOT NULL,
    sent_at TEXT,
    has_attachments INTEGER NOT NULL,
    body_text TEXT NOT NULL,
    body_html TEXT NOT NULL,
    synced_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_mailbox_role
    ON messages (mailbox_role);

CREATE TABLE IF NOT EXISTS sync_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    state TEXT NOT NULL
);
"""


def open_db(path: Path) -> sqlite3.Connection:
    """Open (creating if needed) the local sync database at `path`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def get_sync_state(conn: sqlite3.Connection) -> str | None:
    """Return the saved JMAP state token, or `None` before first sync."""
    row = conn.execute("SELECT state FROM sync_state WHERE id = 1").fetchone()
    return row[0] if row else None


def set_sync_state(conn: sqlite3.Connection, state: str) -> None:
    """Save `state` as the JMAP token to resume delta sync from next time."""
    conn.execute(
        "INSERT INTO sync_state (id, state) VALUES (1, ?) "
        "ON CONFLICT (id) DO UPDATE SET state = excluded.state",
        (state,),
    )
    conn.commit()


def _row_for(msg: EmailMessage, synced_at: str) -> tuple[object, ...]:
    return (
        msg.provider_id,
        msg.thread_id,
        msg.mailbox_role,
        msg.from_address,
        msg.from_name,
        json.dumps(msg.to_addresses),
        json.dumps(msg.cc_addresses),
        msg.subject,
        msg.sent_at,
        int(msg.has_attachments),
        msg.body_text,
        msg.body_html,
        synced_at,
    )


def upsert_messages(
    conn: sqlite3.Connection, messages: list[EmailMessage], synced_at: str
) -> None:
    """Insert or replace `messages`, keyed by their provider ID."""
    if not messages:
        return
    conn.executemany(
        "INSERT INTO messages (provider_id, thread_id, mailbox_role, "
        "from_address, from_name, to_addresses, cc_addresses, subject, "
        "sent_at, has_attachments, body_text, body_html, synced_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (provider_id) DO UPDATE SET "
        "thread_id = excluded.thread_id, "
        "mailbox_role = excluded.mailbox_role, "
        "from_address = excluded.from_address, "
        "from_name = excluded.from_name, "
        "to_addresses = excluded.to_addresses, "
        "cc_addresses = excluded.cc_addresses, "
        "subject = excluded.subject, "
        "sent_at = excluded.sent_at, "
        "has_attachments = excluded.has_attachments, "
        "body_text = excluded.body_text, "
        "body_html = excluded.body_html, "
        "synced_at = excluded.synced_at",
        [_row_for(m, synced_at) for m in messages],
    )
    conn.commit()


def delete_messages(conn: sqlite3.Connection, ids: list[str]) -> None:
    """Remove messages Fastmail reports as destroyed."""
    if not ids:
        return
    conn.executemany(
        "DELETE FROM messages WHERE provider_id = ?", [(i,) for i in ids]
    )
    conn.commit()


def message_count(conn: sqlite3.Connection) -> int:
    """Return how many messages are currently stored."""
    row = conn.execute("SELECT COUNT(*) FROM messages").fetchone()
    return int(row[0])
