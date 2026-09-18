"""JMAP wire-format parsing helpers."""

from __future__ import annotations

from typing import Any

from capsize_fastmail.provider import EmailMessage


def parse_header_contacts(raw: Any) -> list[dict[str, str]]:
    """Normalise a JMAP EmailAddress array to a list of dicts.

    ``dict.get(key, "")`` only falls back to the default when the key
    is *absent* - real JMAP messages can send an explicit ``"name":
    null`` (a contact with no display name), which `.get` happily
    returns as `None`, not `""`. `or ""` catches both cases so this
    never hands back something other than `str`, matching
    `EmailMessage`'s own declared (non-Optional) field types.
    """
    if not raw or not isinstance(raw, list):
        return []
    return [
        {"address": c.get("email") or "", "name": c.get("name") or ""}
        for c in raw
    ]


def _resolve_body_value(parts: Any, body_values: dict[str, Any]) -> str:
    """Resolve JMAP body part descriptors to their text via bodyValues.

    ``textBody``/``htmlBody`` are lists of ``{partId, type, ...}``
    descriptors, not the text itself - the actual content only
    appears in ``bodyValues[partId]["value"]`` when the caller
    requested ``fetchTextBodyValues``/``fetchHTMLBodyValues``.
    """
    if not isinstance(parts, list):
        return ""
    for part in parts:
        part_id = part.get("partId") if isinstance(part, dict) else None
        if not isinstance(part_id, str):
            continue
        value = body_values.get(part_id, {}).get("value", "")
        if value:
            return str(value)
    return ""


def parse_body(em: dict[str, Any]) -> tuple[str, str]:
    """Extract text and HTML body content from a JMAP Email object."""
    body_values = em.get("bodyValues", {}) or {}
    text_body = _resolve_body_value(em.get("textBody"), body_values)
    html_body = _resolve_body_value(em.get("htmlBody"), body_values)
    return text_body, html_body


# A message can sit in more than one JMAP mailbox at once (e.g. a
# custom label alongside Inbox); when that happens, prefer whichever
# role best identifies *why* the message matters to a caller - sent
# mail is the strongest signal (it is provably the account owner's
# own writing), inbox next, then everything else in no particular
# order.
_ROLE_PRIORITY = ("sent", "inbox", "drafts", "archive")


def _resolve_mailbox_role(
    em: dict[str, Any], mailbox_roles: dict[str, str] | None
) -> str:
    if not mailbox_roles:
        return ""
    ids = em.get("mailboxIds")
    if not isinstance(ids, dict):
        return ""
    roles = {mailbox_roles[i] for i in ids if i in mailbox_roles}
    for preferred in _ROLE_PRIORITY:
        if preferred in roles:
            return preferred
    return next(iter(roles), "")


def parse_email(
    em: dict[str, Any], mailbox_roles: dict[str, str] | None = None
) -> EmailMessage:
    """Convert one JMAP Email object to an ``EmailMessage``.

    ``mailbox_roles`` maps a JMAP mailbox ID to its role (e.g. from
    ``EmailProvider.list_mailboxes()``) - passed through so the
    returned message can report which mailbox it actually lives in
    (see ``_resolve_mailbox_role``). Omit it to leave ``mailbox_role``
    blank, e.g. when the caller doesn't need it.
    """
    from_list = parse_header_contacts(em.get("from"))
    from_addr = from_list[0]["address"] if from_list else ""
    from_name = from_list[0]["name"] if from_list else ""

    text_body, html_body = parse_body(em)

    return EmailMessage(
        provider_id=em["id"],
        thread_id=em.get("threadId") or "",
        mailbox_role=_resolve_mailbox_role(em, mailbox_roles),
        from_address=from_addr,
        from_name=from_name,
        to_addresses=parse_header_contacts(em.get("to")),
        cc_addresses=parse_header_contacts(em.get("cc")),
        subject=em.get("subject", "") or "",
        sent_at=em.get("sentAt") or em.get("receivedAt"),
        has_attachments=bool(em.get("hasAttachment", False)),
        body_text=text_body,
        body_html=html_body,
    )
