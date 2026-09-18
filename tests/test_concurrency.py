from __future__ import annotations

from capsize_fastmail.concurrency import (
    BATCH_SIZE,
    fetch_email_bodies,
    run_async,
)


class _FakeProvider:
    """Records the batches it was called with and echoes them back."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def get_emails(self, ids: list[str]) -> list[str]:
        self.calls.append(list(ids))
        return list(ids)


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
    assert sorted(result) == sorted(ids)
    assert len(provider.calls) == 1


def test_fetch_email_bodies_splits_into_batches() -> None:
    provider = _FakeProvider()
    ids = {f"id-{i}" for i in range(BATCH_SIZE + 10)}
    result = fetch_email_bodies(provider, ids)
    assert sorted(result) == sorted(ids)
    assert len(provider.calls) == 2
    assert {len(c) for c in provider.calls} == {BATCH_SIZE, 10}
