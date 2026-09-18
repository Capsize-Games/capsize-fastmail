"""Concurrency-bounded batch fetching for `EmailProvider.get_emails`.

JMAP sub-batches fetch concurrently on one event loop instead of
sequentially on a fresh loop each - sequential fetching means the
next batch's HTTP request does not even start until the previous one
fully returns.

Global concurrency gate
------------------------
Fastmail's published JMAP session limits include:

- ``maxConcurrentRequests: 10``
- ``maxCallsInRequest: 50``
- ``maxObjectsInSet: 4096``

This module guards the *total* number of in-flight JMAP HTTP requests
across the whole process with a ``threading.Semaphore`` - not an
``asyncio.Semaphore`` - so the bound holds even when ``run_async`` is
called from more than one worker thread, each running its own
independent event loop.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar

from capsize_fastmail.provider import EmailMessage, EmailProvider

_T = TypeVar("_T")

# Fastmail's published JMAP session capability: maxConcurrentRequests: 10.
MAX_CONCURRENT_JMAP_REQUESTS = 10

# Fastmail's maxCallsInRequest: 50, maxObjectsInSet: 4096. 250 IDs per
# request stays safely under both while keeping round-trips low.
BATCH_SIZE = 250

_jmap_concurrency_semaphore = threading.Semaphore(
    MAX_CONCURRENT_JMAP_REQUESTS,
)


def fetch_email_bodies(
    provider: EmailProvider, ids: set[str]
) -> list[EmailMessage]:
    """Fetch email bodies for one chunk, JMAP sub-batches concurrently."""
    fetch_list = list(ids)
    batches = [
        fetch_list[i:i + BATCH_SIZE]
        for i in range(0, len(fetch_list), BATCH_SIZE)
    ]
    if not batches:
        return []

    results = run_async(_gather_batches(provider, batches))
    all_emails: list[EmailMessage] = []
    for batch_result in results:
        all_emails.extend(batch_result)
    return all_emails


async def _gather_batches(
    provider: EmailProvider, batches: list[list[str]]
) -> list[list[EmailMessage]]:
    """Fetch every batch concurrently on one event loop.

    Acquires the module-level semaphore before each
    ``provider.get_emails`` call so the total number of in-flight
    JMAP HTTP requests never exceeds
    ``MAX_CONCURRENT_JMAP_REQUESTS``, regardless of how many worker
    threads or inner sub-batches are calling this at once.
    ``asyncio.to_thread`` acquires the blocking semaphore without
    blocking the event loop.
    """
    async def _fetch_with_semaphore(
        batch: list[str],
    ) -> list[EmailMessage]:
        await asyncio.to_thread(_jmap_concurrency_semaphore.acquire)
        try:
            return await provider.get_emails(batch)
        finally:
            _jmap_concurrency_semaphore.release()

    return await asyncio.gather(*(
        _fetch_with_semaphore(batch) for batch in batches
    ))


def run_async(coro: Coroutine[Any, Any, _T]) -> _T:
    """Run an async coroutine on a fresh event loop in the calling thread.

    For calling async provider methods from sync/worker-thread code
    (e.g. a Celery task) that has no event loop of its own.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
