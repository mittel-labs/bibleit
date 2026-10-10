# CLI output contract, schema version 1

Finite `--format json` commands write one object to stdout:

```json
{
  "schema_version": 1,
  "ok": true,
  "records": [
    {"type": "ok", "fields": {"pong": true}}
  ]
}
```

Records retain server order and lowercase record types. END is framing and is
excluded. Fields use snake_case wire names. Object key order is not contractual.
Missing fields remain absent; an explicit empty permission/translation list is
`[]`. Unknown fields stay strings, even if their contents look like numbers.
IDs, names, statuses, source names, references and verse texts remain strings.
The envelope is identical for HTTP and SSH replies.

Known field types:

| Type | Fields |
| --- | --- |
| Boolean | paused, owned, protected, retiring, pong; local profile active, removed, credential_cached; auth in OK/local auth records |
| Non-negative integer | protocol_version, count, verses, chapters, results, books, commands, connections, actor_connections, anonymous_connections, running_for_seconds, revision, stack_entries, position, issued_at, created_at, last_used_at, expires_at, connected_at, connected_for_seconds, plan_activated_at, lives, tokens, keys, used, book, chapter, verse |
| String array | roles, permissions, capabilities, scopes; translations except the count cases below |
| Integer or string | quota limit is an integer, or the literal string `unlimited` |
| Context-specific translations | Account summary (`lives` present) and verse-push acknowledgement (`event=verse`) use an integer count; other translations fields are string arrays |

`auth` in COMMAND help records remains the string authority category. Opaque
account notification terms remain strings. Numeric/boolean validation failures
produce an error rather than silently converting a value to zero or false.
These are typed protocol records; they are not a serialization of the Go client's
domain structs. Future output schema changes must use a new schema_version.

Profile metadata uses PROFILE records with name, endpoint, transport, active,
credential_cached and identity. List order is alphabetical; show/use/add/remove
provide the corresponding metadata. No profile command prints a bearer value.
Local version/help/auth actions use version/help/auth record types. Interactive
browser progress and fallback browser URLs are written to stderr.

## Subscription NDJSON

Use `--format ndjson` only with an SSH `live <id> subscribe` command. Every
acknowledgement/event is one compact JSON object followed by a newline:

```json
{"schema_version":1,"record":{"type":"ok","raw":"OK id=live paused=false","fields":{"id":"live","paused":false}}}
{"schema_version":1,"record":{"type":"event","event":"closed","raw":"EVENT closed","fields":{}}}
```

The initial OK retains the server snapshot. Positional event names are exposed
as `event`; the keyed Live update becomes `event: "live"`. Verse events contain
`payload`, the native JSON decoded from the server's base64 payload. Every stream
record retains the original wire record in `raw`, including future positional
content. Invalid base64/JSON payloads fail explicitly. NDJSON keeps verse text
with embedded newlines inside JSON strings, not additional output lines.

Normal closed events end successfully. Revoked events are emitted before an
authentication error/exit 3. Unexpected disconnects fail. Reconnection remains
explicit and receives a fresh snapshot; NDJSON does not promise event replay.

## Errors and raw/human output

For json/ndjson, errors produce one JSON object on stderr and a nonzero exit:

```json
{"schema_version":1,"ok":false,"exit_code":7,"error":{"code":"rate_limited","message":"rate_limited","fields":{"retry_after_ms":"250"}}}
```

Error fields preserve protocol strings or native HTTP JSON metadata. HTTP errors
also include http_status. Generic codes match the documented exit category;
server error codes remain intact. Failed finite commands write no success object.
A stream can emit records before a later error. Local help/version bypass config
loading, so they still work when configuration is unreadable.

`raw` preserves wire records and framing; local profile/auth/version/help actions
use human output. Default tables retain server column order, escape control
characters, and keep verse text readable. Malformed output after a mutation does
not imply rollback; the CLI never retries mutations. Existing prerelease JSON
string fields are replaced by this documented, versioned typed contract.

## Confirmation errors and completion scripts

Guarded destructive commands require `--yes` with JSON output or when stdin or
stderr is not a terminal. No request is sent if confirmation is missing: stderr
contains the existing schema-version-1 error envelope with
`error.code = "confirmation_required"` and `exit_code = 2`; stdout is empty.
Interactive rejection/EOF uses `cancelled`, exit 1, and sends no request.
Prompts appear only on stderr in table/raw mode. `--yes` does not change the
successful command response or bypass server permissions.

`completion bash|zsh|fish` generates a shell script in table/raw mode. JSON and
NDJSON reject script generation; `help completion --format json` remains a
normal help record. The hidden `__complete` shell adapter emits newline-separated
candidates, ignores network credentials and never contacts the server.
