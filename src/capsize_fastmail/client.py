"""FastmailJMAPProvider - a JMAP client for Fastmail mailboxes.

Raw JMAP JSON method calls via `httpx` rather than a full JMAP
package - this client only needs four operations (list mailboxes,
paginate message IDs, fetch messages, delta sync), and handling
batching and error translation explicitly is not much more code than
wrapping a general-purpose JMAP library would be.
"""

from __future__ import annotations

import json
import logging
from typing import Any, cast

import httpx

from capsize_fastmail.exceptions import FastmailAPIError, FastmailAuthError
from capsize_fastmail.parsing import parse_email
from capsize_fastmail.provider import (
    Changes,
    EmailMessage,
    EmailProvider,
    Mailbox,
    Page,
)

logger = logging.getLogger(__name__)

SESSION_URL = "https://api.fastmail.com/jmap/session"
_SKIP_MAILBOX_ROLES = frozenset({"trash", "junk"})


async def validate_token(token: str) -> str | None:
    """Validate a Fastmail API token via the JMAP session endpoint.

    Returns the account's primary email address on success, or
    ``None`` when the token is rejected. Raises ``FastmailAPIError``
    for anything other than a clean accept/reject (network error,
    unexpected response shape).
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                SESSION_URL,
                headers={"Authorization": f"Bearer {token}"},
                timeout=15.0,
            )
    except httpx.HTTPError as exc:
        raise FastmailAPIError(str(exc)) from exc
    if resp.status_code != 200:
        return None
    data = resp.json()
    primary = data.get("primaryAccounts", {}).get(
        "urn:ietf:params:jmap:mail", ""
    )
    account = data.get("accounts", {}).get(primary, {})
    return account.get("name") or None


class FastmailJMAPProvider(EmailProvider):
    """One JMAP session for one Fastmail account.

    Holds an API token and the JMAP session resource (API URL,
    account ID) it resolves lazily on first use. No database layer,
    no session persistence beyond the lifetime of the instance, and
    no web-framework assumptions.
    """

    def __init__(self, api_token: str) -> None:
        """Store the API token; the session is resolved lazily."""
        self._token = api_token
        self._session: dict[str, Any] | None = None
        self._api_url: str | None = None
        self._account_id: str | None = None

    @property
    def account_id(self) -> str | None:
        """Return the cached JMAP account ID (set after first call)."""
        return self._account_id

    async def _ensure_session(self) -> None:
        """Resolve and cache the JMAP session resource."""
        if self._session is not None:
            return
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    SESSION_URL,
                    headers={"Authorization": f"Bearer {self._token}"},
                    timeout=15.0,
                )
            except httpx.HTTPError as exc:
                raise FastmailAPIError(str(exc)) from exc
            if resp.status_code in (401, 403):
                raise FastmailAuthError(
                    "Fastmail rejected the API token"
                )
            resp.raise_for_status()
            self._session = resp.json()
            primary = self._session.get("primaryAccounts", {}).get(
                "urn:ietf:params:jmap:mail", ""
            )
            self._account_id = primary
            self._api_url = self._session.get("apiUrl", "")

    def _headers(self) -> dict[str, str]:
        """Return common JMAP request headers."""
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def _call(self, methods: list[list[Any]]) -> dict[str, Any]:
        """Invoke one or more JMAP methods in a single HTTP request."""
        await self._ensure_session()
        assert self._api_url is not None  # set by _ensure_session
        payload = {
            "using": [
                "urn:ietf:params:jmap:core",
                "urn:ietf:params:jmap:mail",
            ],
            "methodCalls": methods,
        }
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    self._api_url,
                    headers=self._headers(),
                    json=payload,
                    timeout=30.0,
                )
            except httpx.HTTPError as exc:
                raise FastmailAPIError(str(exc)) from exc
            resp.raise_for_status()
            body: dict[str, Any] = resp.json()
            if "methodResponses" not in body:
                raise FastmailAPIError(
                    "JMAP response missing methodResponses: "
                    f"{json.dumps(body)[:500]}"
                )
            return body

    @staticmethod
    def _find_method_response(
        result: dict[str, Any], method: str
    ) -> dict[str, Any]:
        """Return the args dict for *method* from *result*.

        Raises ``FastmailAPIError`` on an error-shaped response or
        when the method is absent from ``methodResponses``.
        """
        responses: list[list[Any]] = result.get("methodResponses", [])
        for name, args, _tag in responses:
            if name == "error":
                raise FastmailAPIError(
                    f"JMAP error for {method}: "
                    f"{args.get('type', 'unknown')}"
                )
            if name == method:
                return cast(dict[str, Any], args)
        raise FastmailAPIError(
            f"JMAP method {method} not found in response"
        )

    async def list_mailboxes(self) -> list[Mailbox]:
        """Return every mailbox with its role, skipping trash/junk."""
        await self._ensure_session()
        result = await self._call(
            [["Mailbox/get", {"accountId": self._account_id}, "mb_0"]]
        )
        args = self._find_method_response(result, "Mailbox/get")
        return [
            Mailbox(id=mb["id"], name=mb.get("name", ""), role=role)
            for mb in args.get("list", [])
            if (role := (mb.get("role") or "").lower())
            not in _SKIP_MAILBOX_ROLES
        ]

    async def query_email_ids(
        self,
        mailbox_id: str,
        position: int = 0,
        limit: int = 100,
    ) -> Page:
        """Return a page of email IDs, newest first.

        Requests ``calculateTotal`` so callers can report accurate
        progress against the mailbox's true size.
        """
        await self._ensure_session()
        result = await self._call([
            ["Email/query", {
                "accountId": self._account_id,
                "filter": {"inMailbox": mailbox_id},
                "position": position, "limit": limit,
                "calculateTotal": True,
                "sort": [
                    {"property": "receivedAt", "isAscending": False},
                ],
            }, "eq_0"],
        ])
        args = self._find_method_response(result, "Email/query")
        return Page(
            ids=args.get("ids", []),
            position=args.get("position", position),
            total=args.get("total"),
            query_state=args.get("queryState"),
        )

    async def get_emails(
        self,
        ids: list[str],
        include_body: bool = True,
        mailbox_roles: dict[str, str] | None = None,
    ) -> list[EmailMessage]:
        """Fetch email objects for a batch of IDs.

        Set *include_body* to ``False`` for a metadata-only pass
        (headers, no ``textBody``/``htmlBody``/``bodyValues``) - each
        body can be 100+KB, so skip it when the caller will fetch it
        again later anyway.

        *mailbox_roles* (mailbox ID -> role, from ``list_mailboxes()``)
        lets the returned messages report which mailbox they're in
        (e.g. to tell sent mail from received mail) - omit it to leave
        each message's ``mailbox_role`` blank.
        """
        if not ids:
            return []
        await self._ensure_session()
        properties = [
            "id", "threadId", "mailboxIds",
            "from", "to", "cc", "bcc",
            "subject", "receivedAt", "sentAt",
            "hasAttachment", "preview",
        ]
        args: dict[str, Any] = {
            "accountId": self._account_id,
            "ids": ids,
            "properties": properties,
        }
        if include_body:
            # textBody/htmlBody are part descriptors only unless the
            # fetch flags below are set, which add a bodyValues map
            # of partId -> {value, ...} to resolve them against.
            properties.extend(["textBody", "htmlBody", "bodyValues"])
            args["fetchTextBodyValues"] = True
            args["fetchHTMLBodyValues"] = True
        result = await self._call([["Email/get", args, "eg_0"]])
        args = self._find_method_response(result, "Email/get")
        return [
            parse_email(em, mailbox_roles)
            for em in args.get("list", [])
        ]

    async def get_changes(self, since_state: str) -> Changes:
        """Return delta changes since the given JMAP state token."""
        if not since_state:
            return Changes()
        await self._ensure_session()
        result = await self._call([
            [
                "Email/changes",
                {
                    "accountId": self._account_id,
                    "sinceState": since_state,
                    "maxChanges": 500,
                },
                "ec_0",
            ],
        ])
        args = self._find_method_response(result, "Email/changes")
        return Changes(
            created=args.get("created", []),
            updated=args.get("updated", []),
            destroyed=args.get("destroyed", []),
            new_state=args.get("newState", ""),
        )
