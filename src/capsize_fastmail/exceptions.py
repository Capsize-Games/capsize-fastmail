"""Exceptions raised by capsize_fastmail.

These wrap whatever the JMAP transport raises, so callers never need
to inspect raw HTTP status codes or JMAP error-object shapes directly.
"""


class FastmailError(Exception):
    """Base class for all errors raised by this package."""


class FastmailAuthError(FastmailError):
    """The API token was rejected, or is missing/expired."""


class FastmailAPIError(FastmailError):
    """Any other JMAP request failure.

    Covers network errors, rate limits, malformed requests, and a
    JMAP method returning an ``error``-shaped response.
    """
