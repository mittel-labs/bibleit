# Bibleit client contract: protocol v1

This directory starts a language-neutral compatibility suite for the Go,
Python, Ruby, and Rust clients. It records current server behavior. It does not
change the server protocol or constitute a complete formal specification.

## Transport

`POST /api/cli/command` takes `Authorization: Bearer <token>` and a JSON body
of the form `{"command":"PING"}`. Responses use the same UTF-8, newline-delimited
text records as SSH exec. Domain errors can arrive with HTTP 200; inspect the
protocol envelope, not only the HTTP status.

HTTP supports finite command replies. `LIVE <id> SUBSCRIBE` is SSH-only.
Browser WebSockets are not yet a bearer-token replacement for client subscriptions.
V1 interactive SSH has FIFO replies without request IDs, with EVENT records
between envelopes. The initial Go decoder is for finite HTTP/SSH-exec replies,
not multiplexed interactive channels.

## Commands and quoting

Commands are constructed from supported operations and individual arguments.
Arguments containing spaces or tabs are double quoted. CR, LF, NUL, and double
quotes are rejected: the current server request tokenizer does not implement
escaped quotes. Backslashes in requests are literal and must not be doubled.
The server's response encoder does escape quotes, backslashes, LF/CR/tab and ASCII control characters
(`\n`, `\r`, `\t`, `\uNNNN`); clients decode these when parsing field values. Request and response escaping differ in v1.

Customer translation commands use `ACCOUNT TRANSLATION ...`. Global
`TRANSLATION FETCH`, `DELETE`, and catalogue administration are outside this
initial client surface.

The current server accepts `LIVE <id> SECRET <value>` for secret authentication
and `SECRET CREATE|ROTATE|DELETE` for secret management. It explicitly rejects
`SECRET SET <value>`. The CLI rejects `secret set <value>` with an explicit unsupported-operation
message, rather than silently treating management as authentication. Secret authentication is connection-scoped;
a one-command invocation does not establish a persistent subscription session.

## Finite responses

- Single reply: `OK ...` followed by a newline.
- Multiple records: `OK ...`, data records, and an `END` line.
- Error: `ERR <code> [metadata...]` followed by a newline.
- Empty multi-record replies still require END.
- Unknown success fields and error codes must be retained.
- Error metadata can include `retry_after_ms`; clients do not retry mutations.

Current multi-record headers use `count`, `verses`, `results`, `books`,
`commands`, or `connections`. Live push responses use `event=verse` and a numeric
`translations` field. Ordinary translation lists also use `translations`, but
as a comma-separated string in a single-record response. Account translation
list/add/remove also include `count` without an END marker. HTTP and CLI SSH exec
use `DecodeCommandResponse` to apply that command-specific framing rule. Generic
`DecodeResponse` cannot disambiguate count-only headers. Never use a field
alone to infer framing. A future protocol should make envelope framing explicit.

Account information currently includes notification preferences formatted as an
opaque Erlang map. The encoder can wrap this value across physical lines.
The Go parser retains balanced compound fields as text, including line breaks;
it never evaluates them. Newlines outside compound fields remain invalid.
Original logical records and unknown fields remain available in typed results.

## Fixture format

`fixtures/responses-v1.json` is a JSON array. Each case has:

- `name`: stable descriptive name.
- `wire`: complete response, including newlines.
- `records`: expected parsed record types and string fields for success.
- `error_code` and `error_fields`: expected server error and metadata.
- `invalid: true`: malformed or incomplete data that must fail decoding.

Go tests consume these fixtures now. The other language clients should reuse
this file. Fixtures were derived from `bibleit-server/src/protocol/bibleit_protocol.erl`
and its protocol tests; 27 request fixtures and 18 response encodings are now verified against compiled
server source with `python3 scripts/check_server.py`. Malformed and future-error
response cases remain client-decoder robustness fixtures. Server code has not been modified by this extraction.

## Server review status (2026-10-10)

The server now has organization workspaces, separate CLI credential quotas,
additional SSH key algorithms, request byte limits, and browser management
WebSockets. The current client fixtures cover finite protocol replies only.
See [the revised plan](../docs/plan.md) for the operation inventory and integration
testing work required before publishing clients.

The new server protocol reference documents `SECRET SET`, while its parser still
rejects it. The CLI now rejects `secret set` until server support exists;
the documentation/parser mismatch still needs a server-side resolution. Browser-only workspace
and event operations are not supported bearer-token client APIs.

## Next increments

The tracked Go core now passes complete isolated HTTP/SSH integration, including
all typed results and authorization transport. See docs/status.md for counts.

1. Resolve the remaining SECRET SET and repeated stats-field discrepancies.
2. Finalize shell completion/destructive-command UX and native platform CI;
   endpoint-bound profiles and versioned JSON/NDJSON are implemented.
3. Define public bearer-authenticated workspace and event contracts with the server.
4. Validate the core contract with Python, then Ruby and Rust; settle stable
   repository/package paths before publishing independent releases.

## Verification and progress

See [features.md](features.md) for operation/transport support and
[../docs/status.md](../docs/status.md) for item-by-item progress.
`fixtures/requests-v1.json` contains wire strings and expected Erlang decoder
terms in `server_term`; those terms are parsed as data, not evaluated. Response
fixtures with `server_response_term` are checked against the real server encoder.
Source fingerprints are recorded in `server-baseline.json`.

```sh
python3 scripts/check_server.py
python3 scripts/check_server.py --integration
```

Identical repeated response fields are accepted for compatibility with current
Live stats; conflicting repeated values are rejected.

## Translation metadata encoder issue

The assessment session fixed the HTTP 500 from optional metadata: `fields/1`
now accepts both atom and binary field names. The shared metadata encoder
fixture exercises binary keys, and the real metadata/catalogue HTTP checks
pass against a fresh snapshot. This CLI work did not edit server files.


## Token metadata (2026-10-10)

`ACCOUNT TOKEN LIST` requires `token.get` and emits an `OK actor=... count=N`
header, N `TOKEN` records and END. IDs, source, issue timestamp and optional
issuer/label/scopes/last-use/expiry/retirement metadata are retained. No bearer
value is returned. Listings filter inactive credentials and do not expose other
actors' tokens. A scoped credential still needs token.get to list metadata.

The assessment fixed nonempty scope encoding using the permissions CSV
convention. A compiled encoder fixture and real HTTP listing now verify that
representation, with scoped authority checks and active-only metadata filtering.
The assessment also fixed an intermediate SSH Live-deletion closure regression.
The complete integration run passes and the verified baseline is updated.

## Authorization HTTP transport

`POST /api/cli/token` exchanges form fields code, code_verifier and optional
device_name. HTTP 200 returns actor, identity_name, auth_provider, token_id and
access_token. Errors are JSON with HTTP status (e.g. 400 for invalid/reused code
or invalid verifier, 403 for username onboarding, 409 for CLI credential quota).
Codes are one-use; a bad verifier also consumes the code. No automatic retries.

`POST /api/cli/logout` uses the credential's bearer header. HTTP 204 acknowledges
revocation; an already invalid credential returns 401. The Go library retains
error status/code/metadata and leaves local storage decisions to the application.
The CLI retains its profile on failed revocation and clears it after 204 or 401.
Both methods share HTTPS/loopback endpoint rules, reject redirects, accept
contexts and bound response bodies. Real HTTP checks verify exchange, replay,
bad-verifier consumption, logout and post-logout rejection.
