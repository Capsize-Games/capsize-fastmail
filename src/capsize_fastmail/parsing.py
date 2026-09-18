"""JMAP wire-format parsing helpers."""

from __future__ import annotations

from typing import Any

from capsize_fastmail.provider import EmailMessage


def parse_header_contacts(raw: Any) -> list[dict[str, str]]:
    """Normalise a JMAP EmailAddress array to a list of dicts."""
    if not raw or not isinstance(raw, list):
        return []
    return [
        {"address": c.get("email", ""), "name": c.get("name", "")}
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


def parse_email(em: dict[str, Any]) -> EmailMessage:
    """Convert one JMAP Email object to an ``EmailMessage``."""
    from_list = parse_header_contacts(em.get("from"))
    from_addr = from_list[0]["address"] if from_list else ""
    from_name = from_list[0]["name"] if from_list else ""

    text_body, html_body = parse_body(em)

    return EmailMessage(
        provider_id=em["id"],
        thread_id=em.get("threadId", ""),
        mailbox_role="",
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
