"""capsize_fastmail - a Fastmail JMAP client for reading mail."""

from capsize_fastmail.client import (
    SESSION_URL,
    FastmailJMAPProvider,
    validate_token,
)
from capsize_fastmail.concurrency import (
    BATCH_SIZE,
    MAX_CONCURRENT_JMAP_REQUESTS,
    fetch_email_bodies,
    run_async,
)
from capsize_fastmail.exceptions import (
    FastmailAPIError,
    FastmailAuthError,
    FastmailError,
)
from capsize_fastmail.preprocessing import (
    classify_automated,
    strip_quoted_content,
)
from capsize_fastmail.provider import (
    Changes,
    EmailMessage,
    EmailProvider,
    Mailbox,
    Page,
)

__all__ = [
    "BATCH_SIZE",
    "MAX_CONCURRENT_JMAP_REQUESTS",
    "SESSION_URL",
    "Changes",
    "EmailMessage",
    "EmailProvider",
    "FastmailAPIError",
    "FastmailAuthError",
    "FastmailError",
    "FastmailJMAPProvider",
    "Mailbox",
    "Page",
    "classify_automated",
    "fetch_email_bodies",
    "run_async",
    "strip_quoted_content",
    "validate_token",
]
