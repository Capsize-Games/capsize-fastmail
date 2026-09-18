"""EmailProvider - abstract interface for mail provider backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Mailbox:
    """One mailbox (folder) returned by the provider."""

    id: str
    name: str
    role: str  # inbox, sent, trash, junk, archive, drafts, etc.


@dataclass
class EmailMessage:
    """One fetched email with headers and (possibly) body.

    ``body_text`` and ``body_html`` are only populated when the
    caller asked for them (see ``EmailProvider.get_emails``).
    """

    provider_id: str
    thread_id: str
    mailbox_role: str
    from_address: str
    from_name: str = ""
    to_addresses: list[dict[str, str]] = field(default_factory=list)
    cc_addresses: list[dict[str, str]] = field(default_factory=list)
    subject: str = ""
    sent_at: str | None = None
    has_attachments: bool = False
    body_text: str = ""
    body_html: str = ""


@dataclass
class Page:
    """One page of email IDs from a paginated query."""

    ids: list[str]
    position: int = 0
    total: int | None = None


@dataclass
class Changes:
    """Delta sync result - added/updated/destroyed email IDs."""

    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    destroyed: list[str] = field(default_factory=list)
    new_state: str = ""


class EmailProvider(ABC):
    """Abstract interface for email backends.

    ``FastmailJMAPProvider`` (see ``client.py``) is the only
    implementation this package ships; the interface exists so a
    caller can add another provider (e.g. Gmail) behind the same
    four methods without touching the code that consumes them.
    """

    @abstractmethod
    async def list_mailboxes(self) -> list[Mailbox]:
        """Return all mailboxes (folders) for the account."""
        ...

    @abstractmethod
    async def query_email_ids(
        self,
        mailbox_id: str,
        position: int = 0,
        limit: int = 100,
    ) -> Page:
        """Return a page of email IDs for one mailbox."""
        ...

    @abstractmethod
    async def get_emails(
        self,
        ids: list[str],
        include_body: bool = True,
        mailbox_roles: dict[str, str] | None = None,
    ) -> list[EmailMessage]:
        """Fetch full email objects for a batch of IDs."""
        ...

    @abstractmethod
    async def get_changes(self, since_state: str) -> Changes:
        """Return delta changes since the given state token."""
        ...
