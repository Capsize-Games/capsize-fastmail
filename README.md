# capsize-fastmail

A small [Fastmail](https://www.fastmail.com/) [JMAP](https://jmap.io/)
client for reading mail: list mailboxes, page through message IDs,
fetch messages, and delta-sync — with no database layer, no session
persistence, and no web-framework assumptions.

```bash
pip install capsize-fastmail
```

## What it does not do

This is a **read-only** client. There is no `EmailSubmission` support
— sending mail is out of scope. It also does not read environment
variables, does not store credentials anywhere, and does not know
about your database or web framework. The host application decides
what (if anything) to persist between calls. That is the same
boundary [`capsize-bluesky`](https://github.com/capsize-games/capsize-bluesky)
draws for its own third-party API client.

## Authentication

Fastmail JMAP uses a bearer API token — not OAuth. Generate one under
Settings → Password & Security → Connected apps & API tokens on
fastmail.com, scoped to Mail. Store it however your application
stores secrets; this package only ever holds it in memory for the
lifetime of the client instance.

## Usage

```python
from capsize_fastmail import FastmailJMAPProvider

provider = FastmailJMAPProvider(api_token)

mailboxes = await provider.list_mailboxes()
inbox = next(mb for mb in mailboxes if mb.role == "inbox")

page = await provider.query_email_ids(inbox.id, position=0, limit=100)
messages = await provider.get_emails(page.ids)

for msg in messages:
    print(msg.subject, msg.from_address)
```

### Delta sync

Fetch only what changed since a previous JMAP state token (returned
as `new_state` on every `Changes` result — save it and pass it back
in on the next sync):

```python
changes = await provider.get_changes(since_state=saved_state)
new_messages = await provider.get_emails(changes.created)
```

### Validating a token before storing it

```python
from capsize_fastmail import validate_token

email_address = await validate_token(candidate_token)
if email_address is None:
    ...  # bad or expired token
```

### Fetching many messages concurrently

`get_emails` fetches one batch per call. For a full-mailbox backfill,
`fetch_email_bodies` bounds concurrency to Fastmail's published JMAP
session limits (`maxConcurrentRequests: 10`) while batching requests
under `maxCallsInRequest`/`maxObjectsInSet`, and works from a sync
context (e.g. a Celery task) via its own event loop:

```python
from capsize_fastmail import fetch_email_bodies

messages = fetch_email_bodies(provider, set(all_ids))
```

### Preprocessing

Two algorithmic (non-LLM) helpers for triaging fetched messages:

```python
from capsize_fastmail import classify_automated, strip_quoted_content

if not classify_automated(msg):  # skip receipts/newsletters/etc.
    body = strip_quoted_content(msg.body_text)  # drop quoted replies
```

## Errors

`FastmailJMAPProvider`'s methods and `validate_token` raise:

- `FastmailAuthError` — the API token was rejected.
- `FastmailAPIError` — any other JMAP failure (network, rate limit,
  malformed request, a JMAP method returning an `error`-shaped
  response, ...).

Both subclass `FastmailError`, so callers that don't care about the
distinction can catch just that.

## Local mirror (`scripts/sync_local.py`)

A standalone script - deliberately outside the `capsize_fastmail`
package itself, which stays database-free by design (see above) -
that mirrors the whole account into a local SQLite database. First
run does a full backfill of every mailbox; every run after that uses
JMAP delta sync (`Email/changes`) to fetch only what changed, so it's
safe to run often.

```bash
export FASTMAIL_API_TOKEN=...          # required, Mail-scoped
export FASTMAIL_SYNC_DB=/path/to.db    # optional, see the script for the default
python scripts/sync_local.py
```

Each stored message carries a real `mailbox_role` (`sent`, `inbox`,
`drafts`, ...) resolved from `list_mailboxes()`, so a downstream
consumer can select e.g. only sent mail (the account owner's own
writing) without touching anything received from someone else.

### Running on a schedule

This is a plain script with a normal process exit code (`0` success,
`1` failure) - any scheduler works. A user crontab entry is the
simplest option for a personal machine:

```cron
*/30 * * * * FASTMAIL_API_TOKEN=... /path/to/.venv/bin/python /path/to/capsize-fastmail/scripts/sync_local.py >> /path/to/sync.log 2>&1
```

Keep the token out of the crontab line itself in practice - source it
from a file with `. /path/to/.env &&` prefixed to the command, or use
a systemd user timer with `EnvironmentFile=` instead.

## Extending to another provider

`EmailProvider` (in `capsize_fastmail.provider`) is the four-method
interface `FastmailJMAPProvider` implements. A caller that wants to
support another backend (e.g. Gmail) behind the same call sites can
implement that interface directly; this package does not ship any
other implementation.
