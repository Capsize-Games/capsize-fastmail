from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from capsize_fastmail.client import FastmailJMAPProvider, validate_token
from capsize_fastmail.exceptions import FastmailAPIError, FastmailAuthError

_SESSION_BODY = {
    "apiUrl": "https://api.fastmail.com/jmap/api/",
    "primaryAccounts": {"urn:ietf:params:jmap:mail": "acct-1"},
    "accounts": {"acct-1": {"name": "user@fastmail.com"}},
}


def _fake_response(status_code: int, json_body: dict[str, Any]) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception("http error")
    else:
        resp.raise_for_status.return_value = None
    return resp


def _mock_async_client(
    get_response: MagicMock | None = None,
    post_response: MagicMock | None = None,
) -> MagicMock:
    """Return a context manager mimicking `httpx.AsyncClient()`."""
    client = AsyncMock()
    if get_response is not None:
        client.get.return_value = get_response
    if post_response is not None:
        client.post.return_value = post_response
    cm = MagicMock()
    cm.__aenter__.return_value = client
    cm.__aexit__.return_value = None
    return cm


async def test_validate_token_success() -> None:
    cm = _mock_async_client(get_response=_fake_response(200, _SESSION_BODY))
    with patch("capsize_fastmail.client.httpx.AsyncClient", return_value=cm):
        result = await validate_token("good-token")
    assert result == "user@fastmail.com"


async def test_validate_token_rejected() -> None:
    cm = _mock_async_client(get_response=_fake_response(401, {}))
    with patch("capsize_fastmail.client.httpx.AsyncClient", return_value=cm):
        result = await validate_token("bad-token")
    assert result is None


async def test_list_mailboxes_skips_trash_and_junk() -> None:
    session_cm = _mock_async_client(
        get_response=_fake_response(200, _SESSION_BODY)
    )
    call_body = {
        "methodResponses": [
            [
                "Mailbox/get",
                {
                    "list": [
                        {"id": "1", "name": "Inbox", "role": "inbox"},
                        {"id": "2", "name": "Trash", "role": "trash"},
                        {"id": "3", "name": "Junk", "role": "junk"},
                    ]
                },
                "mb_0",
            ]
        ]
    }
    post_cm = _mock_async_client(
        post_response=_fake_response(200, call_body)
    )
    provider = FastmailJMAPProvider("token")
    with patch(
        "capsize_fastmail.client.httpx.AsyncClient",
        side_effect=[session_cm, post_cm],
    ):
        mailboxes = await provider.list_mailboxes()
    assert [mb.role for mb in mailboxes] == ["inbox"]
    assert provider.account_id == "acct-1"


async def test_list_mailboxes_sends_resolved_account_id() -> None:
    """Every public method used to build its JMAP payload before ready.

    Reading `self._account_id` before `_call` had a chance to resolve
    the session and populate that field meant a fresh provider's very
    first call sent `accountId: null` to Fastmail - caught live
    against a real account, not by this suite, since no existing test
    asserted on the outgoing request body.
    """
    session_client = AsyncMock()
    session_client.get.return_value = _fake_response(200, _SESSION_BODY)
    session_cm = MagicMock()
    session_cm.__aenter__.return_value = session_client
    session_cm.__aexit__.return_value = None

    post_client = AsyncMock()
    post_client.post.return_value = _fake_response(
        200,
        {
            "methodResponses": [
                ["Mailbox/get", {"list": []}, "mb_0"],
            ]
        },
    )
    post_cm = MagicMock()
    post_cm.__aenter__.return_value = post_client
    post_cm.__aexit__.return_value = None

    provider = FastmailJMAPProvider("token")
    with patch(
        "capsize_fastmail.client.httpx.AsyncClient",
        side_effect=[session_cm, post_cm],
    ):
        await provider.list_mailboxes()

    sent_body = post_client.post.call_args.kwargs["json"]
    sent_account_id = sent_body["methodCalls"][0][1]["accountId"]
    assert sent_account_id == "acct-1"


async def test_query_email_ids_captures_query_state() -> None:
    session_cm = _mock_async_client(
        get_response=_fake_response(200, _SESSION_BODY)
    )
    query_body = {
        "methodResponses": [
            [
                "Email/query",
                {
                    "ids": ["e1", "e2"],
                    "position": 0,
                    "total": 2,
                    "queryState": "state-abc",
                },
                "eq_0",
            ],
        ]
    }
    post_cm = _mock_async_client(
        post_response=_fake_response(200, query_body)
    )
    provider = FastmailJMAPProvider("token")
    with patch(
        "capsize_fastmail.client.httpx.AsyncClient",
        side_effect=[session_cm, post_cm],
    ):
        page = await provider.query_email_ids("mbx-1")
    assert page.ids == ["e1", "e2"]
    assert page.query_state == "state-abc"


async def test_call_raises_on_error_response() -> None:
    session_cm = _mock_async_client(
        get_response=_fake_response(200, _SESSION_BODY)
    )
    error_body = {
        "methodResponses": [
            ["error", {"type": "accountNotFound"}, "eq_0"],
        ]
    }
    post_cm = _mock_async_client(
        post_response=_fake_response(200, error_body)
    )
    provider = FastmailJMAPProvider("token")
    with (
        patch(
            "capsize_fastmail.client.httpx.AsyncClient",
            side_effect=[session_cm, post_cm],
        ),
        pytest.raises(FastmailAPIError),
    ):
        await provider.query_email_ids("mbx-1")


async def test_ensure_session_raises_auth_error_on_401() -> None:
    session_cm = _mock_async_client(get_response=_fake_response(401, {}))
    provider = FastmailJMAPProvider("bad-token")
    with (
        patch(
            "capsize_fastmail.client.httpx.AsyncClient",
            return_value=session_cm,
        ),
        pytest.raises(FastmailAuthError),
    ):
        await provider.list_mailboxes()


async def test_get_emails_returns_empty_for_no_ids() -> None:
    provider = FastmailJMAPProvider("token")
    assert await provider.get_emails([]) == []


async def test_get_changes_returns_empty_for_no_state() -> None:
    provider = FastmailJMAPProvider("token")
    changes = await provider.get_changes("")
    assert changes.created == []
    assert changes.new_state == ""


async def test_get_current_state_returns_bare_state_token() -> None:
    """Deliberately distinct from a Page's `query_state`.

    Real Fastmail returns e.g. `"J977974"` here vs. `"J977974:0"`
    from `Email/query`, and only the bare form works as
    `get_changes`'s `since_state` (see `Page.query_state`'s
    docstring).
    """
    session_cm = _mock_async_client(
        get_response=_fake_response(200, _SESSION_BODY)
    )
    get_body = {
        "methodResponses": [
            ["Email/get", {"list": [], "state": "J977974"}, "eg_state"],
        ]
    }
    post_cm = _mock_async_client(post_response=_fake_response(200, get_body))
    provider = FastmailJMAPProvider("token")
    with patch(
        "capsize_fastmail.client.httpx.AsyncClient",
        side_effect=[session_cm, post_cm],
    ):
        state = await provider.get_current_state()
    assert state == "J977974"
