"""Non-LLM email preprocessing - stripping and classification.

Entirely algorithmic, no model cost - run this before any LLM call
on email content.
"""

from __future__ import annotations

import re

from capsize_fastmail.provider import EmailMessage

_SIG_DELIMITER = re.compile(r"^--\s*$", re.MULTILINE)
_QUOTE_PATTERN = re.compile(
    r"^On\s+.+wrote:\s*$", re.MULTILINE | re.IGNORECASE,
)
_QUOTE_LINE = re.compile(r"^>\s?", re.MULTILINE)

# Automated-email detection heuristics. Kept to unambiguous
# transactional senders - a broader match (e.g. "alerts", "billing")
# risks misclassifying mail the reader actually wants, like a bank
# alert or a freelance invoice; those are caught by subject text
# instead, where the context is clearer.
_AUTOMATED_FROM = re.compile(
    r"(no-?reply|noreply|donotreply|bounce"
    r"|auto-confirm|order-?update|shipment-?tracking|receipts?@)",
    re.IGNORECASE,
)
_AUTOMATED_DOMAINS = frozenset({
    "mailchimp", "sendgrid", "klaviyo", "convertkit",
    "constantcontact", "mailgun", "postmark", "hubspot",
    "marketo", "activecampaign", "drip",
})
_AUTOMATED_SUBJECTS = (
    "unsubscribe", "newsletter",
    "order confirmation", "your order", "order #",
    "has shipped", "shipping confirmation", "out for delivery",
    "delivered", "tracking number", "your receipt",
    "payment confirmation", "invoice #", "your invoice",
    "statement is ready", "auto-generated", "do not reply",
)


def strip_quoted_content(body: str) -> str:
    """Remove quoted reply blocks and signature lines.

    Uses the common ``On ... wrote:`` pattern, leading ``>`` quote
    markers, and the ``-- `` signature delimiter. Returns cleaned
    plaintext.
    """
    text = body or ""
    match = _QUOTE_PATTERN.search(text)
    if match:
        text = text[:match.start()].strip()
    lines = text.split("\n")
    cleaned = [line for line in lines if not _QUOTE_LINE.match(line)]
    text = "\n".join(cleaned)
    match = _SIG_DELIMITER.search(text)
    if match:
        text = text[:match.start()].strip()
    return text.strip()


def classify_automated(msg: EmailMessage) -> bool:
    """Return True if *msg* is likely automated/transactional.

    Covers receipts, shipping notices, and newsletters - mail that
    is usually not worth summarizing or indexing for a human reader.
    """
    from_addr = (msg.from_address or "").lower()
    if _AUTOMATED_FROM.search(from_addr):
        return True
    if any(domain in from_addr for domain in _AUTOMATED_DOMAINS):
        return True
    subject_lower = (msg.subject or "").lower()
    return any(h in subject_lower for h in _AUTOMATED_SUBJECTS)
