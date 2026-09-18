from __future__ import annotations

from capsize_fastmail.concurrency import (
    BATCH_SIZE,
    fetch_email_bodies,
    run_async,
)
from capsize_fastmail.provider import (
    Changes,
    EmailMessage,
    EmailProvider,
    Mailbox,
    Page,
)


class _FakeProvider(EmailProvider):
    """Records the batches it was called with and echoes them back."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.mailbox_roles_seen: list[dict[str, str] | None] = []

    async def list_mailboxes(self) -> list[Mailbox]:
        return []

    async def query_email_ids(
        self, mailbox_id: str, position: int = 0, limit: int = 100
    ) -> Page:
        return Page(ids=[])

    async def get_emails(
        self,
        ids: list[str],
        include_body: bool = True,
        mailbox_roles: dict[str, str] | None = None,
    ) -> list[EmailMessage]:
        self.calls.append(list(ids))
        self.mailbox_roles_seen.append(mailbox_roles)
        return [
            EmailMessage(
                provider_id=i,
                thread_id=i,
                mailbox_role="",
                from_address="",
            )
            for i in ids
        ]

    async def get_changes(self, since_state: str) -> Changes:
        return Changes()


def _ids(messages: list[EmailMessage]) -> list[str]:
    return [m.provider_id for m in messages]


def test_run_async_returns_coroutine_result() -> None:
    async def _coro() -> int:
        return 42

    assert run_async(_coro()) == 42


def test_fetch_email_bodies_empty_ids() -> None:
    provider = _FakeProvider()
    assert fetch_email_bodies(provider, set()) == []
    assert provider.calls == []


def test_fetch_email_bodies_single_batch() -> None:
    provider = _FakeProvider()
    ids = {f"id-{i}" for i in range(5)}
    result = fetch_email_bodies(provider, ids)
    assert sorted(_ids(result)) == sorted(ids)
    assert len(provider.calls) == 1


def test_fetch_email_bodies_splits_into_batches() -> None:
    provider = _FakeProvider()
    ids = {f"id-{i}" for i in range(BATCH_SIZE + 10)}
    result = fetch_email_bodies(provider, ids)
    assert sorted(_ids(result)) == sorted(ids)
    assert len(provider.calls) == 2
    assert {len(c) for c in provider.calls} == {BATCH_SIZE, 10}


def test_fetch_email_bodies_passes_mailbox_roles() -> None:
    provider = _FakeProvider()
    roles = {"mb-1": "sent"}
    fetch_email_bodies(provider, {"id-1"}, mailbox_roles=roles)
    assert provider.mailbox_roles_seen == [roles]
