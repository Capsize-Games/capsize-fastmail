from capsize_fastmail.parsing import (
    parse_body,
    parse_email,
    parse_header_contacts,
)


def test_parse_header_contacts_empty() -> None:
    assert parse_header_contacts(None) == []
    assert parse_header_contacts("not-a-list") == []


def test_parse_header_contacts_normalizes() -> None:
    raw = [{"email": "a@example.com", "name": "Alice"}]
    assert parse_header_contacts(raw) == [
        {"address": "a@example.com", "name": "Alice"}
    ]


def test_parse_header_contacts_coerces_explicit_null_name() -> None:
    """`{"name": null}` is real, observed JMAP output.

    A contact with no display name, distinct from the key being
    absent - `dict.get(key, default)` does NOT fall back to `default`
    for an explicit `null` value, only a missing key. Confirmed live:
    this crashed a real sync with a NOT NULL constraint failure before
    the fix, since `None` isn't a `str`.
    """
    raw = [{"email": "a@example.com", "name": None}]
    assert parse_header_contacts(raw) == [
        {"address": "a@example.com", "name": ""}
    ]


def test_parse_body_resolves_body_values() -> None:
    em = {
        "textBody": [{"partId": "1"}],
        "htmlBody": [{"partId": "2"}],
        "bodyValues": {
            "1": {"value": "plain text"},
            "2": {"value": "<p>html</p>"},
        },
    }
    text, html = parse_body(em)
    assert text == "plain text"
    assert html == "<p>html</p>"


def test_parse_body_missing_parts_returns_empty() -> None:
    assert parse_body({}) == ("", "")


def test_parse_email_full() -> None:
    em = {
        "id": "msg-1",
        "threadId": "thread-1",
        "from": [{"email": "a@example.com", "name": "Alice"}],
        "to": [{"email": "b@example.com", "name": "Bob"}],
        "cc": [],
        "subject": "Hello",
        "sentAt": "2026-01-01T00:00:00Z",
        "hasAttachment": True,
        "textBody": [{"partId": "1"}],
        "bodyValues": {"1": {"value": "hi"}},
    }
    msg = parse_email(em)
    assert msg.provider_id == "msg-1"
    assert msg.thread_id == "thread-1"
    assert msg.from_address == "a@example.com"
    assert msg.from_name == "Alice"
    assert msg.to_addresses == [{"address": "b@example.com", "name": "Bob"}]
    assert msg.subject == "Hello"
    assert msg.has_attachments is True
    assert msg.body_text == "hi"


def test_parse_email_falls_back_to_received_at() -> None:
    em = {
        "id": "msg-2",
        "threadId": "thread-2",
        "from": [],
        "receivedAt": "2026-02-02T00:00:00Z",
    }
    msg = parse_email(em)
    assert msg.sent_at == "2026-02-02T00:00:00Z"
    assert msg.from_address == ""
    assert msg.from_name == ""


def test_parse_email_resolves_mailbox_role() -> None:
    em = {"id": "msg-3", "threadId": "t-3", "mailboxIds": {"mb-1": True}}
    msg = parse_email(em, mailbox_roles={"mb-1": "sent"})
    assert msg.mailbox_role == "sent"


def test_parse_email_without_mailbox_roles_is_blank() -> None:
    em = {"id": "msg-4", "threadId": "t-4", "mailboxIds": {"mb-1": True}}
    assert parse_email(em).mailbox_role == ""


def test_parse_email_prefers_sent_over_other_roles() -> None:
    em = {
        "id": "msg-5",
        "threadId": "t-5",
        "mailboxIds": {"mb-1": True, "mb-2": True},
    }
    msg = parse_email(
        em, mailbox_roles={"mb-1": "archive", "mb-2": "sent"}
    )
    assert msg.mailbox_role == "sent"
