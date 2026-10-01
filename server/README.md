# bibleit-server

`bibleit-server` is Bibleit's OTP service. It owns translations, persistent
authorization, LiveSession state, the versioned line-based TCP protocol, and
the browser-facing HTTP/WebSocket Live endpoint. The raw TCP listener remains
a protocol endpoint for CLI and service clients; it is not an HTTP server.

This document is the protocol reference for version 1. A running server is the
final authority: use `HELP`, `HELP AUTH`, `HELP TRANSLATION`, and `HELP LIVE`
to discover commands visible to the current connection.

## Contents

- [Start a server](#start-a-server)
- [Versioning](#versioning)
- [Protocol at a glance](#protocol-at-a-glance)
- [Responses, events, and errors](#responses-events-and-errors)
- [Command summary](#command-summary)
- [Server commands](#server-commands)
- [Authentication and authorization](#authentication-and-authorization)
- [Translation commands](#translation-commands)
- [Live commands](#live-commands)
- [HTTP and WebSocket Lives](#http-and-websocket-lives)
- [Pipelining and live events](#pipelining-and-live-events)
- [Transport limits](#transport-limits)
- [TLS and Fly.io](#tls-and-flyio)
- [Persistence and deployment](#persistence-and-deployment)
- [OTP release shape](#otp-release-shape)

## Start a server

From the repository root:

```sh
make -C server test
make -C server run
```

The project uses [rebar3](https://rebar3.org/) for dependency resolution,
development builds, and production releases. Install it globally (for example,
`brew install rebar3`) or run `make -C server install-rebar3` once. The latter
follows Rebar3's local-install flow and places the runner in
`~/.cache/rebar3/bin/rebar3`, which the Makefile discovers automatically.
`make compile` incrementally rebuilds `libbibleit`, the NIF, and Erlang modules
only when their inputs change. `make run` starts the TCP server, HTTP server,
and native SSH listener without an interactive Erlang shell, using the same
environment-driven bootstrap as the production release. Its local defaults are
a local data directory. To create the first administrator, configure one
OpenSSH Ed25519 public key:

```text
BIBLEIT_BOOTSTRAP_PUBLIC_KEY="$(cat ~/.ssh/id_ed25519.pub)" \\
BIBLEIT_BOOTSTRAP_ACTOR=admin \\
make run
```

Press `Ctrl-C` to stop it. `make shell` opens an Erlang shell with the compiled
application and its dependencies on the code path, so you can set custom
configuration and call `bibleit_server:start().` yourself.
`make run-tls` also starts the native TLS listener on `localhost:7443`,
creating the local self-signed certificate if needed.

Environment variables supplied to `make run` are passed to the bootstrap. For
example, test Google sign-in locally with:

```sh
BIBLEIT_GOOGLE_CLIENT_ID=... \
BIBLEIT_GOOGLE_CLIENT_SECRET=... \
BIBLEIT_PUBLIC_URL=http://localhost:8080 \
make run
```

For local email/password testing, add Resend credentials and an authorized
sender to the same command:

```sh
BIBLEIT_RESEND_API_KEY=re_... \
BIBLEIT_EMAIL_FROM='Bibleit <accounts@your-domain.example>' \
BIBLEIT_PUBLIC_URL=http://localhost:8080 \
make run
```

The default listener is `127.0.0.1:7070`. Connect with `nc`:

```sh
nc 127.0.0.1 7070
```

Every connection receives a greeting:

```text
OK server="bibleit" protocol_version=1 version="0.0.1" auth=false
```

`BIBLEIT_BOOTSTRAP_PUBLIC_KEY` seeds a `server_admin` actor once the
authorization store opens. It must be an `ssh-ed25519` public-key line; private
keys never enter Bibleit configuration or storage.

Use the native TLS CLI to sign in with the same local key:

```sh
make cli
./cli/cli --ca-file server/priv/local-cert.pem auth login
```

## Source layout

The OTP application is grouped by responsibility rather than by transport
implementation detail:

- `src/auth/` owns account records, authorization, email/password accounts,
  and outbound email delivery.
- `src/ssh/` owns the supervised native SSH listener, SSH public-key callback,
  channel shell, and connection-to-account identity registry.
- `src/http/` owns Cowboy listeners, browser sessions, OAuth callbacks, HTTP
  pages, and WebSocket handling.
- `src/transport/` owns the raw TCP/TLS line-protocol listeners, connection
  processes, rate limiter, and PROXY protocol parsing.
- `src/live/`, `src/translations/`, and `src/protocol/` contain the respective
  domain state and command handling.

SSH usernames are intentionally not account identifiers. A registered public
key authenticates its owning account regardless of the username supplied to
`ssh`; an unknown or missing key is rejected.

## Versioning

[`VERSION`](VERSION) is the single version source for `bibleit_server` and its
OTP release. To make a release, change that file to the next semantic version,
then build and verify it:

```sh
cd server
make version
# edit VERSION, for example: 0.0.2
make test
make release
```

The resulting artifact is named `bibleit_server-<version>` under
`_build/prod/rel/`. The application also reports the same version through
`server info`.

### Rebar3 utilities

```sh
make deps                    # Resolved dependency tree
make rebar3 ARGS="version"  # Rebar3, OTP, and ERTS versions
make rebar3 ARGS="tree"     # Equivalent to make deps
```

## Protocol at a glance

The protocol is UTF-8, newline-delimited, and space based. Command keywords are
case-insensitive. A command is one line; use double quotes around an argument
that contains whitespace.

```text
read NVIPT Salmos 23
read KJV "Song of Songs" 2 1
live create "Sunday Service"
live abc123 set reference "John 3:16"
```

The grammar notation in this reference is:

| Notation | Meaning |
| --- | --- |
| `<value>` | Required argument |
| `[value]` | Optional argument |
| `a\|b` | Choose one alternative |
| `...` | One or more additional values |

The server parses quoted text as one argument and removes the quotes. There is
no JSON-lines framing. Clients must buffer TCP input and split it into complete
newline-delimited records; a socket read is not necessarily one record.

### Session example

```text
auth login SHA256:your-key-fingerprint
OK challenge="..." nonce="..." algorithm="ssh-ed25519" expires_at=...

translation list
OK translations="KJV,NVIPT"

read nvipt Salmos 23 1
OK translation="nvipt" book=19 chapter=23 verse=1 text="Salmos 23:1 O Senhor é o meu pastor; de nada terei falta."

quit
OK closing=true
```

## Responses, events, and errors

Each command produces exactly one response envelope.

| Shape | Meaning |
| --- | --- |
| `OK key=value ...` | Successful single-record response |
| `OK ...` then records then `END` | Successful multi-record response |
| `ERR code` | Command was not performed |
| `EVENT ...` | Unsolicited live-subscription update |

String fields are quoted and escaped when required. Booleans are written as
`true` or `false`; counts and timestamps are integers. Clients should accept
additional fields in successful responses so protocol additions remain
compatible.

### Multi-record response example

```text
read nvipt Salmos 23
OK translation="nvipt" book=19 chapter=23 verses=6
VERSE text="Salmos 23:1 O Senhor é o meu pastor; de nada terei falta."
VERSE text="Salmos 23:2 Em verdes pastagens me faz repousar..."
END
```

### Important error codes

| Error | Meaning and client action |
| --- | --- |
| `bad_command` | Grammar is invalid; correct the command. |
| `forbidden` | Valid command, but the authenticated actor lacks permission. |
| `unauthorized` | Login is required for this operation. |
| `invalid_token` | Token is unknown or revoked. |
| `not_found` | Requested live or resource does not exist; do not retry blindly. |
| `book_not_found` / `invalid_reference` | Translation or reference cannot be resolved. |
| `live_stopped` | Start the live before changing its displayed reading. |
| `rate_limited retry_after_ms=<n>` | Back off for at least `<n>` milliseconds. |
| `response_too_large` | Narrow or paginate the client request where supported. |
| `subscriber_limit_reached` | The live has reached its audience cap. |
| `slow_consumer` | The connection was too far behind on live events and is closed. |

`HELP` and errors are permission-aware. A TCP/TLS client must authenticate
before it can run commands; its only pre-authentication requests are the
short-lived public-key challenge steps required to establish an actor.

## Command summary

| Group | Purpose |
| --- | --- |
| `HELP [topic]` | Discover commands exposed to this session. |
| `SERVER INFO`, `PING`, `WHOAMI`, `QUIT` | Inspect or control the connection. |
| `AUTH ...` | Login, actor hierarchy, roles, tokens, quotas. |
| `READ`, `SEARCH`, `TRANSLATION ...` | Read and manage Bible translations. |
| `LIVE ...` | Create, present, subscribe to, and manage Lives. |

## Server commands

### `HELP [server|auth|translation|live]`

Lists commands available to the connection. Omitting the topic returns the root
summary. Each `COMMAND` record includes a `usage`, authorization category, and
short summary.

```text
help live
OK auth=true commands=...
COMMAND usage="live list" auth=permission summary="List lives owned by the actor or its child actors."
...
END
```

Use `HELP` for feature detection instead of hard-coding a command list in a
client. The README explains semantics; `HELP` explains the currently enabled
surface.

### `SERVER INFO`

Returns the protocol and application version and stable capability names.

```text
server info
OK protocol_version=1 version="0.0.1" capabilities="help,auth,translation,read,search,live"
```

Unauthenticated TCP/TLS connections receive `ERR unauthorized`.

### `PING`

Returns `OK pong=true`. It is appropriate for a client health check.

### `WHOAMI` and `AUTH INFO`

Both inspect the current authenticated session:

```text
whoami
OK actor="felipe" display_name="Felipe" auth=true ...
```

After login, the response includes the actor, effective permissions, direct
actor count, and how many tokens the actor has issued.

### `QUIT` and `EXIT`

Return `OK closing=true`, then close the TCP connection. Neither changes server
state.

## Authentication and authorization

### Model

An **actor** is a persistent principal and account. An **SSH-style Ed25519 public key**
authenticates a TCP connection as an actor. A **permission** has a resource and verb, such as
`live.create` or `translation.search`. A **role** is a reusable permission set.

Global permissions authorize server-wide actions. A Live with a secret uses it
for audience access.

Every authenticated actor receives the built-in `default` role:

```text
token.get, help.get, server.get, translation.read
```

It allows help, server discovery, session inspection, and reads. It does
not allow searching, installation, Live management, or actor administration.

Browser-created email, Google, and GitHub accounts receive the `member` role.
It adds search, personal Live management, personal tokens, and SSH-key
management. A member does not administer actors, roles, or server-wide
translation installation.

### Personal account commands

Members use `ACCOUNT` for resources owned by the current account; no internal
actor ID is required:

```text
account info
account quota list
account token create "Presentation laptop"
account token list
account token revoke <id|all>
account key add ssh-ed25519 AAAA... laptop
account key list
account key revoke SHA256:...
```

### Plans and subscriptions

Every account has one persisted subscription. The initial subscription is:

```text
plan=free
status=active
billing_cycle=none
```

The `free` plan is the current product definition: price `USD 0`, limits of 3
Lives, 5 access tokens, and 5 SSH keys, plus SSH access, Live presentations,
and translation search. A subscription records `plan`, `status`, `started_at`,
`trial_ends_at`, and `billing_cycle`; a plan records `id`, `name`, `price`,
`limits`, and `features`. `ACCOUNT INFO` exposes the subscription fields and
`ACCOUNT QUOTA LIST` reports each applicable limit with its current usage.

The plan module is deliberately separate from billing-provider integration.
Future paid plans can change a subscription's plan and limits without changing
the account identity or the resource APIs. An operator may still apply a
specific account quota override where needed.

### Login and session commands

#### `AUTH LOGIN <key-fingerprint>`

Starts a one-use, 60-second Ed25519 challenge for an authorized public key.
The client signs the exact bytes defined by the protocol and submits the
result with `AUTH LOGIN PROVE`.

```text
auth login SHA256:exampleFingerprint
OK challenge="..." nonce="..." algorithm="ssh-ed25519" expires_at=...
auth login prove <challenge> <base64-ssh-signature>
OK actor="felipe" key_fingerprint="SHA256:exampleFingerprint"
```

Unknown keys, invalid signatures, expired challenges, and replayed challenges
return distinct `ERR` responses. Repeated failures
are subject to the shared IP-based throttle described in
[Transport limits](#transport-limits).

For raw TCP, this is the only login flow. The private key remains on the
client; the server stores and checks its public half only. The signature is an
OpenSSH `SSHSIG` envelope with the `bibleit@bibleit.app` namespace, which
prevents a proof for another protocol from being replayed here. Browser
sessions remain separate and are created by browser sign-in.

The native CLI creates the proof with local `ssh-keygen`; it never sends
or prints a private key:

```sh
# Terminal 1: starts the TLS listener using the local development certificate.
make -C server run-tls

# Terminal 2: authenticate with the native Go CLI and its default ~/.ssh/id_ed25519 key.
make cli
./cli/cli --ca-file server/priv/local-cert.pem auth login
```

Use `--identity /path/to/another/id_ed25519` to use a different private key.

#### `AUTH INFO`

Requires an authenticated connection and reports only its actor, effective
roles and permissions, plus the public-key fingerprint used by this
connection. `WHOAMI` is its top-level alias.

#### `AUTH LOGOUT`

Clears the authenticated actor and all Live subscriptions from this connection.
It does not revoke a public key.

### RBAC discovery

#### `AUTH LIST RESOURCE`

Lists resources recognized by the authorization model, including `actor`,
`authorization`, `token`, `live`, `quota`, `role`, and `translation`.
Requires `authorization.list`.

#### `AUTH LIST PERMISSION`

Lists the recognized resource-verb permission pairs. Requires
`authorization.list`.

#### `AUTH LIST ROLE`

Lists roles and their effective permission sets. Requires `role.list`.

Built-in roles are `presenter`, `live_operator`, `translation_manager`,
`identity_manager`, `authorization_manager`, and `server_admin`.

`server_admin` is the all-permissions role. It dynamically includes future
permissions and is the only role permitted to delegate `server_admin` itself.
There is deliberately no global `*.*` permission. A resource wildcard such as
`live.*` is dynamic: it grants every current and future verb for `live`.

### Actors

Actors form a direct creation hierarchy. Outside `server_admin`, an actor may
manage only itself and direct children it created. This scopes ordinary
provisioning to its own tenant.

#### `AUTH ACTOR CREATE <actor>`

Creates an actor with only the immutable `default` role. Requires
`actor.create`; actor quotas can cap the number of direct children.

#### `AUTH ACTOR INFO <actor>`

Shows metadata for a managed actor: creator, creation timestamp, assigned
roles, effective permissions, and token/quota counts. Requires `actor.get`.

#### `AUTH ACTOR LIST [limit [cursor]]`

Lists direct children for ordinary actors or all actors for `server_admin`.
The default page size is 10 and the maximum is 100. A response may include
`next="<actor>"`; supply it as the cursor to continue.

#### `AUTH ACTOR DELETE <actor>`

Deletes a managed actor and revokes its issued tokens. Requires
`actor.delete`. This is irreversible.

### Permission, role, and quota bindings

#### `AUTH ACTOR GRANT <actor> PERMISSION <resource.verb...>`

Adds global permissions. The caller must have `actor.update`, be allowed to
manage the target actor, and already possess every delegated permission.

```text
auth actor grant presenter permission live.create live.update live.subscribe
auth actor grant presenter permission live.*
```

#### `AUTH ACTOR REVOKE <actor> PERMISSION <resource.verb...>`

Removes global permissions under the same actor-management boundary.

#### `AUTH ACTOR GRANT|REVOKE <actor> ROLE <role>`

Adds or removes a role. `default` cannot be bound or removed explicitly.
Delegation requires the caller to hold the role's permissions; delegating
`server_admin` additionally requires `role.bind`.

#### `AUTH ACTOR GRANT <actor> QUOTA <resource.verb> <limit>`

Sets a persistent creation quota. Supported quotas are `actor.create`,
`token.create`, `key.create`, and `live.create`; an actor must effectively have the
corresponding permission before receiving a quota.

#### `AUTH ACTOR QUOTA LIST <actor>`

Lists configured quotas for a managed actor. `AUTH ACTOR REVOKE <actor> QUOTA
<resource.verb>` removes one. Quotas are unlimited unless explicitly set.

### Tokens

#### `AUTH TOKEN CREATE <actor> [label]` (operator)

Issues a token for an existing managed actor. The secret is shown exactly
once:

```text
auth token create presenter "Presentation laptop"
OK actor="presenter" id="..." token="bt_..."
```

Only its SHA-256 hash is persisted. The `bt_` prefix identifies a Bibleit
token; the rest is 256 bits of cryptographically random material encoded
as Base62. The optional label identifies the client or intended use. Requires
`token.create`.

#### `AUTH TOKEN LIST <actor>`

Lists token IDs and metadata, never secrets. Metadata includes its label,
issuance source (`manual`), issue time, issuer, and `last_used_at`
when it has logged in. Requires `token.get`.

`token.create` quotas cap active tokens issued by that actor. Revoking a token
frees one quota slot. Members should prefer `ACCOUNT TOKEN` commands above;
the `AUTH TOKEN` form is reserved for an operator managing an actor.

#### `AUTH TOKEN REVOKE <actor> <id|all>`

Revokes one token by ID or all issued tokens only when `all` is explicit.
Requires `token.delete`. Revocation blocks future login
immediately; already authenticated connections retain their current identity
until they disconnect or log off.

### Custom roles

```text
auth role create service_reader permission live.get live.subscribe
auth role update service_reader permission live.get live.subscribe live.update
auth role delete service_reader
```

Custom roles contain existing permissions only. Creating, replacing, and
deleting them requires `role.create`, `role.update`, and `role.delete`.

## Translation commands

Translations are read from `~/.bibleit` by default. Set `translations_dir` to
override it. A translation consists of `.bt` and `.bidx` data; the server uses a
resource-backed NIF linked with `libbibleit` and reuses native handles by
translation. Search indexes (`.bt.bsearch`) are built beside translations.

### `READ <translation> <book> [chapter] [verse]`

Reads a book, chapter, or verse. `<book>` may be a numeric book ID or localized
name; quote a multi-word name. Book matching is case- and accent-insensitive.
Use `chapter:verse` as a compact alternative to separate chapter and verse
arguments.

```text
read KJV 19
read KJV 19 23
read KJV 43 3 16
read KJV 43 3:16
read NVIPT Salmos 23
read NVIPT "o evangelho de joao" 3:16
read KJV "Song of Songs" 2 1
```

One verse returns a single `OK` record. A chapter or book streams `VERSE`
records and terminates with `END`. Requires `translation.read`, included in the
default role.

### `SEARCH <translation> <query>`

Searches verse text only; it does not match book/reference labels. It is
case-insensitive and accent-insensitive for common Latin characters, so `joao`
matches `João` in verse text. The query may contain spaces.

```text
search NVIPT pastor
search NVIPT "love your enemies"
```

Results have the `OK` / `VERSE` / `END` shape and are capped by
`search_max_results` (100 by default, at most 1000). Requires
`translation.search` because it is potentially expensive.

### `TRANSLATION LIST [ALL]`

`TRANSLATION LIST` returns installed slugs. `TRANSLATION LIST ALL` returns the
union of installed slugs and translations known to the upstream catalog.
Requires `translation.list`.

### `TRANSLATION INFO <slug>`

Returns upstream metadata such as `short_name`, `full_name`, and `updated`.
Requires `translation.get`.

### `TRANSLATION CATALOG <slug>`

Streams an installed translation's complete client-side reference catalog:

```text
translation catalog NVIPT
OK translation="NVIPT" books=...
BOOK book=19 name="Salmos" chapters=150
CHAPTER book=19 chapter=23 verses=6
...
END
```

Use it to implement autocomplete without hard-coding a canon. Requires
`translation.get`.

### `TRANSLATION FETCH <slug>`

Downloads and installs a known translation, builds its index, and makes it
available without restarting the server. Requires `translation.create`.

At startup, `available_translations.json` is seeded in the translations
directory from bundled language data when it does not already exist.

### `TRANSLATION DELETE <slug|all>`

Deletes an installed translation and associated indexes. `all` deletes all
installed translations but retains the available-translation catalog cache.
Requires `translation.delete`.

## Live commands

A Live is a persistent presentation session with an owner, translations,
current payload, an optional hashed audience secret, and subscribers. Live IDs
are URL-safe Base62 identifiers, not tokens.

### Lifecycle and discovery

#### `LIVE CREATE [name]`

Creates a running, open Live owned by the current actor. Requires
`live.create`.

```text
live create "Sunday Service"
OK id="7kF3xQ9a" name="Sunday Service" status=running
```

#### `LIVE LIST`

Lists lives owned by the actor or its direct children. Requires `live.list` and
authentication. Each `LIVE` record includes its ID, status, and available
options; privileged callers receive `created_by`.

#### `LIVE <id> INFO`

Returns a permitted Live's configuration and visible state: name, status,
pause state, reference, configured translations, and creation time. Privileged
callers also receive `created_by`. Requires `live.get`.

#### `LIVE <id> STATS`

Returns the owner-only operational view of a Live. The summary includes running
time, revision, stack size, and total, actor-authenticated, and anonymous
connection counts. Each `CONNECTION` record identifies an actor when one is
known; browser viewers and secret-authorized viewers are reported as
`actor="anonymous"`, without exposing the secret.

```text
live 7kF3xQ9a stats
OK id="7kF3xQ9a" connections=2 actor_connections=1 anonymous_connections=1 stack_entries=3 revision=12 running_for_seconds=42
CONNECTION actor="presenter" access=actor connected_at=1790954648 connected_for_seconds=42
CONNECTION actor="anonymous" access=open connected_at=1790954650 connected_for_seconds=40
END
```

It requires `live.get`, but only the Live owner can retrieve it.

#### `LIVE <id> START|STOP`

`STOP` prevents new live reads while retaining the displayed payload. `START`
resumes reads. Requires update authority.

#### `LIVE <id> DELETE` and `LIVE DELETE ALL`

Deletes one managed Live, or all Lives the actor manages. Deletion notifies
subscribers, removes persisted state, and is irreversible. Requires
`live.delete`.

### Live configuration

#### `LIVE <id> SET NAME <name>`

Changes its display name.

#### `LIVE <id> SET REFERENCE <reference>`

Stores a descriptive reference. It does not itself read or display verses.

#### `LIVE <id> SET TRANSLATIONS <translation...>`

Sets default translations used by `LIVE <id> STACK PUSH` when the command omits an explicit
translation. For a multi-translation read, the server resolves the named book
in the first configured translation that recognizes it, then uses its canonical
book ID in each other translation.

All `SET` operations require update authority.

### Presentation payload

#### `LIVE <id> STACK PUSH [translation] <book> [chapter] [verse]`

Reads verses and pushes them onto the Live stack. With an explicit translation
it reads only that translation. Without one, it uses configured translations.
Newly pushed entries appear at the bottom of the audience display.
Book names are case- and accent-insensitive, and the final chapter and verse
may be written together as `chapter:verse`.

```text
live 7kF3xQ9a stack push NVIPT Salmos 23 1
live 7kF3xQ9a stack push Salmos 23 1
live 7kF3xQ9a stack push Salmos 23:1
```

#### `LIVE <id> STACK POP [count]`

Pops entries from the stack. The default count is `1`; a positive count removes
the most recently pushed entries (the bottom of the audience display). A
negative count removes entries from the oldest side instead.

```text
live 7kF3xQ9a stack pop
live 7kF3xQ9a stack pop 2
live 7kF3xQ9a stack pop -1
```

#### `LIVE <id> STACK INFO`

Shows the current stack in audience-display order, including each entry’s
position, translation, reference, and text. Requires `live.get`.

#### `LIVE <id> STACK CLEAR`

Empties the entire stack. `LIVE <id> CLEAR` remains a shorthand for the same
operation.

#### `LIVE <id> CLEAR`

Destroys the current payload and sends a clear event to subscribers.

#### `LIVE <id> PAUSE` and `LIVE <id> RESUME`

`PAUSE` blanks the audience display without discarding the stack and sends a
“we’ll be right back” state to viewers. `RESUME` rebroadcasts the retained
stack. `RESUME` returns `ERR nothing_to_resume` if the stack is empty. A
stopped Live must be started before it can be resumed.

All presentation-payload operations require update authority. A Live must be
running for stack pushes and pops.

### Live secrets

A Live without a secret is open to subscribers with `live.subscribe`. Setting
a secret restricts audience access to viewers that know it. Keep secrets out of
public URLs and logs.

```text
live 7kF3xQ9a secret set a-long-private-secret
OK id="7kF3xQ9a" secret="a-long-private-secret"
```

The Live owner can replace a secret or generate a new one. Both operations
require `live.update` and ownership of that Live:

```text
live 7kF3xQ9a secret set a-long-private-secret
live 7kF3xQ9a secret rotate
live 7kF3xQ9a secret delete
```

Changing or rotating a secret immediately disconnects viewers that entered with
the old secret. `SECRET DELETE` also disconnects those viewers and makes the
Live open again. Only a SHA-256 hash of the secret is persisted.

#### `LIVE <id> SUBSCRIBE`

Subscribes the connection to Live events. An open Live requires global
`live.subscribe`. For a secret-protected Live, first authorize this TCP
connection with its secret; no actor login is required:

```text
live 7kF3xQ9a secret a-long-private-secret
live 7kF3xQ9a subscribe
```

Successful subscribers may immediately receive the currently showing verse
payload.

The built-in HTTP adapter converts these protocol events into WebSocket
messages. Browsers use that endpoint, never the raw TCP port.

## HTTP and WebSocket Lives

The OTP application starts an HTTP listener on `127.0.0.1:8080` by default,
alongside the raw TCP listener on `127.0.0.1:7070`. Its browser assets live in
[`priv/static`](priv/static), the OTP application's release-packaged static
resource directory, so one deployable service owns the browser and TCP
surfaces.

### Application API and transports

Bibleit is modeled as an OTP application first. [`bibleit_api`](src/bibleit_api.erl)
is the transport-neutral application façade: it speaks in actors, translations,
Lives, and subscriptions. TCP is a line-protocol adapter which parses commands,
calls the application API, and encodes responses. Cowboy is another adapter;
its handlers and WebSocket process call the same API directly inside the BEAM.

```text
TCP line protocol ─┐
Cowboy HTTP / WS ──┼──► bibleit_api ───► OTP domain actors
future CLI SDK ────┘        │
                             ├── authorization
                             ├── translations
                             └── LiveSession actors
```

No HTTP handler opens a loopback TCP connection. This keeps parsing, TCP rate
limits, and response formatting at the edge while authorization and domain
state remain reusable by every transport.

| Endpoint | Purpose |
| --- | --- |
| `GET /healthz` | Load-balancer health check; returns `{"ok":true}`. |
| `GET` / `POST /auth/login` | Browser sign-in by email/password. |
| `GET` / `POST /auth/signup` | Email/password account creation and verification request. |
| `GET /auth/email/verify/<token>` | Consumes a one-time email-verification link and signs the browser in. |
| `GET` / `POST /auth/password/reset` | Requests a password-reset link. |
| `GET` / `POST /auth/password/reset/<token>` | Consumes a one-time password-reset link. |
| `GET /auth/google` | Starts Google OAuth sign-in or sign-up. |
| `GET /auth/google/callback` | Google OAuth callback. |
| `GET /auth/github` | Starts GitHub OAuth sign-in or sign-up. |
| `GET /auth/github/callback` | GitHub OAuth callback. |
| `POST /auth/logout` | Revokes the current browser session, clears its cookie, and redirects to sign-in. |
| `GET /dashboard` | Authenticated account dashboard. |
| `GET /lives/<live-id>` | Canonical Live presentation URL. |
| `GET /<live-id>` | Short Live URL; redirects to `/lives/<live-id>`. |
| `POST /auth/<live-id>` | Validate a Live secret and set its HttpOnly Live cookie. |
| `GET /ws?live=<live-id>` | Browser WebSocket stream. |
| `GET /assets/...` | Packaged CSS and JavaScript. |

Create a Live over TCP, then open its canonical URL:

```sh
# In another terminal, after `make -C server run-tls`:
make cli
./cli/cli --ca-file server/priv/local-cert.pem live create "Sunday Service"
# Open http://127.0.0.1:8080/lives/<id>
```

The browser page subscribes directly to its `LiveSession`. A visitor joins a
secret-protected Live by posting its secret to `POST /auth/<live-id>`; the
secret is held in a same-site, HttpOnly, per-Live cookie. Set
`http_secure_cookies` to `true` when the public site is HTTPS. Widgets remain available with `?widget=1`;
`translation=slug` or `translations=slug1,slug2` limits the rendered
translations.

Browser account onboarding endpoints are intentionally the only public HTTP
surface: sign-up, sign-in, OAuth callbacks, email verification, password
reset, and the health check. They exist solely to establish or recover a
browser account session; dashboard mutations require that session. The public
Live page remains an audience presentation endpoint and continues to use its
per-Live secret when configured.

### Browser authentication

The HTTP surface has its own short-lived browser-session layer. `POST
/auth/login` accepts an email/password account, resolves it to an actor
through in-process Erlang actors, and returns a
`Secure` (when configured), `HttpOnly`, `SameSite=Lax` cookie. Passwords are
never placed in JavaScript, local storage, or a WebSocket message.

The Cowboy handlers and WebSocket endpoint resolve that cookie directly through
Erlang actors; they never make a loopback raw-TCP connection or parse the TCP
protocol. Browser sessions are intentionally memory-only and expire after
eight hours by default (`http_session_ttl_seconds`), so restarting the OTP app
requires browser sign-in again. Durable tokens remain the mechanism for CLI
and automation clients.

### Email/password sign-up and Resend

Email accounts are optional. A sign-up records an unverified account, hashes
the password with Argon2id, then sends a single-use verification link. Opening
the link creates the corresponding Bibleit actor, marks the email verified, and
starts a browser session. Verification and password-reset links expire after
30 minutes; stored records contain only SHA-256 hashes of those link secrets.

Email addresses and password hashes are private account data. They are not
included in `AUTH ACTOR LIST` or actor metadata. The actor gets a random
`email-...` identifier and the display name selected at sign-up.

Configure Resend with all three values:

```text
BIBLEIT_RESEND_API_KEY=re_...
BIBLEIT_EMAIL_FROM="Bibleit <accounts@example.com>"
BIBLEIT_PUBLIC_URL=https://bibleit.app
```

`BIBLEIT_EMAIL_FROM` must be a sender authorized in Resend. For development,
use a Resend test sender/recipient allowed by your account. The server sends
email through Resend's `POST https://api.resend.com/emails` API. The Docker
builder already installs the C compiler required by the Argon2id Erlang NIF.

### Google sign-in and sign-up

Google OAuth is optional. When configured, `/auth/login` and `/auth/signup`
offer the same Google path. On the first successful Google sign-in, Bibleit
creates an actor from Google’s stable subject identifier; later sign-ins reuse
that actor. The Google access token is used only during the callback exchange
and is never stored.

Configure the three values together in deployment:

```text
BIBLEIT_GOOGLE_CLIENT_ID=...
BIBLEIT_GOOGLE_CLIENT_SECRET=...
BIBLEIT_PUBLIC_URL=https://bibleit.app
```

Register `https://bibleit.app/auth/google/callback` as the authorized redirect
URI in Google Cloud. The public URL must be the externally visible HTTPS origin.

### GitHub sign-in and sign-up

GitHub OAuth is optional and follows the same browser-session flow. The first
successful sign-in creates an actor from GitHub's stable numeric user ID; later
sign-ins reuse it. Bibleit requests only GitHub's `read:user` scope and does
not persist the GitHub access token.

Configure these values together with the same public URL:

```text
BIBLEIT_GITHUB_CLIENT_ID=...
BIBLEIT_GITHUB_CLIENT_SECRET=...
BIBLEIT_PUBLIC_URL=https://bibleit.app
```

Create a GitHub **OAuth App** (not a GitHub App) and register
`https://bibleit.app/auth/github/callback` as its authorization callback URL.
For local testing, use `http://localhost:8080/auth/github/callback` and set
`BIBLEIT_PUBLIC_URL=http://localhost:8080`.


## Pipelining and live events

A client may send several complete commands without waiting for replies. The
server processes one connection's commands in FIFO order and emits replies in
the same order. Protocol v1 has no request IDs, `PIPELINE`, or `MULTI` command:
associate replies with sent commands by order.

`EVENT` records are asynchronous and can appear between command response
envelopes. They never appear inside a multi-record envelope (`OK`, records,
`END`). Clients with both requests and subscriptions must therefore maintain two
streams of meaning: ordered command replies and unsolicited events.

Live mutations are serialized by their LiveSession actor. A future protocol
revision may add revision-based conditional updates if competing controllers
need compare-and-set semantics.

## Transport limits

The server uses a shared in-memory, per-IP limiter. Reconnecting does not reset
connection, request, or failed-login budgets. These are operational protections,
not persistent actor quotas.

When throttled, the server returns a retry hint:

```text
ERR rate_limited retry_after_ms=45000
```

At admission, the listener may send that response and close immediately. Once
the failed-login threshold is exceeded, it does the same. A client should not
retry until the supplied duration has elapsed.

Malformed commands have their own shared `bad_commands_per_ip` budget (twenty
per minute by default). This prevents an invalid-command loop from bypassing
the normal parsed-request budget; once exhausted, it also returns
`ERR rate_limited` with a retry hint.

Default limits are configured as one application environment map:

```erlang
application:set_env(bibleit_server, limits, #{
  max_connections => 1000,
  max_connections_per_ip => 20,
  max_unauthenticated_connections_per_ip => 5,
  new_connections_per_ip => #{limit => 30, window_ms => 60000},
  max_requests_per_connection => #{limit => 120, window_ms => 60000},
  max_requests_per_ip => #{limit => 600, window_ms => 60000},
  bad_commands_per_ip => #{limit => 20, window_ms => 60000},
  failed_logins_per_ip => #{limit => 5, window_ms => 60000},
  idle_timeout_ms => 300000,
  authenticated_idle_timeout_ms => 3600000,
  max_command_bytes => 8192,
  max_response_bytes => 1048576,
  max_subscribers_per_live => 500,
  max_event_queue_per_connection => 100
}).
```

`max_command_bytes` may also be configured through the top-level application
setting. TCP/TLS clients may connect only long enough to complete the
public-key login challenge; every other command returns `ERR unauthorized`
until an actor is established. They expire after `idle_timeout_ms` (five
minutes by default); authenticated connections use
`authenticated_idle_timeout_ms` (one hour by default). Logging in or off
immediately refreshes the applicable idle timer.
An authentication deadline is disabled by default; deployments that require
every TCP client to authenticate may opt in with
`authentication_timeout_ms => 30000`. The listener uses active-once delivery, so a connection
process handles one decoded request before reading another. Event pressure is
bounded separately: a subscriber beyond `max_subscribers_per_live` receives
`ERR subscriber_limit_reached`; a backed-up event connection is closed with
`ERR slow_consumer`. Responses larger than `max_response_bytes` return
`ERR response_too_large`.

The HTTP WebSocket listener uses a five-minute idle timeout by default. The
browser automatically reconnects after an interrupted connection, with a
backoff from one to fifteen seconds. Set `websocket_idle_timeout_ms` under the
`http` application configuration to change that server-side timeout:

```erlang
application:set_env(bibleit_server, http, #{port => 8080, websocket_idle_timeout_ms => 300000}).
```

## TLS and Fly.io

The standard listener is plaintext TCP. Keep it private, local, or behind a
TLS terminator before allowing public-key authentication on an untrusted network. The server
also supports an **optional native TLS listener** for local development and
deployments that need it. Native TLS is disabled unless the `tls` application
configuration is complete.

### Local TLS test

Generate a short-lived, self-signed development certificate. The generated
files are ignored by Git:

```sh
cd server
make cert
```

Or use `make run-tls` to generate the certificate and start both local
listeners in one command.

Start both plaintext TCP (`7070`) and native TLS (`7443`) listeners:

```erlang
application:set_env(bibleit_server, bootstrap_keys, #{
  <<"ssh-ed25519 AAAA... admin@host">> => #{actor => <<"admin">>, roles => [server_admin]}
}),
application:set_env(bibleit_server, tls, #{
  port => 7443,
  certfile => "priv/local-cert.pem",
  keyfile => "priv/local-key.pem",
  handshake_timeout_ms => 10000
}),
bibleit_server:start().
```

In another terminal, verify the certificate and use the normal line protocol:

```sh
openssl s_client -connect localhost:7443 \
  -servername localhost \
  -CAfile server/priv/local-cert.pem
```

```text
auth login SHA256:...
OK challenge="..." nonce="..." algorithm="ssh-ed25519" expires_at=...
server info
OK protocol_version=1 version="0.0.1" capabilities="help,auth,translation,read,search,live"
```

The native listener accepts TLS 1.2 and TLS 1.3 only. TLS handshakes have a
bounded timeout before a connection process is created. For a real public
native-TLS deployment, provide certificate and key files through the deployment
secret mechanism; do not commit them.

### SSH shell

Bibleit’s public SSH front door is an OTP SSH listener in the Bibleit release.
It verifies the OpenSSH public-key proof and resolves the key directly to its
owning account through `bibleit_authorization`. SSH has its own encrypted
transport, so it does not wrap the public TLS line-protocol endpoint or make an
internal network hop.

Only registered public keys may open an SSH session. The SSH username is
ignored: it is local transport metadata, not a Bibleit account. A key added in
the dashboard resolves to its owning actor automatically, regardless of
whether the user connects as `ssh bibleit.app`, `ssh laptop@bibleit.app`, or
another local username.

The initial terminal UI intentionally remains a command-focused shell: its
header identifies the verified member, command output remains in normal
terminal scrollback, and it uses the same permission-aware commands as every
other Bibleit transport. This is the stable Phase 0 interaction model before a
richer full-screen TUI is introduced.

Members gain account-specific commands such as `account info`, `account quota
list`, `live create`, and `search`. Ordinary commands such as `read NVIPT
salmos 23:1` continue to work unchanged.

For local development, `make run` starts the OTP application and its SSH
listener together:

```sh
# terminal 1
make -C server run

# terminal 2
ssh -p 2222 localhost
```

To try a member session, sign into `/dashboard`, add the contents of
`~/.ssh/id_ed25519.pub` under **SSH keys**, then reconnect:

```sh
ssh -p 2222 any-local-name@localhost
```

Port `2222` is deliberately the local-development port: binding the standard
SSH port (`22`) normally requires elevated privileges and may collide with the
machine's own SSH daemon. To avoid repeatedly specifying the port, use an
OpenSSH host alias in `~/.ssh/config`:

```sshconfig
Host bibleit-local
  HostName localhost
  Port 2222
  User admin
  IdentityFile ~/.ssh/id_ed25519
  IdentitiesOnly yes
```

Then connect with:

```sh
ssh bibleit-local
```

`ssh localhost` itself is also possible by using `Host localhost` in that
configuration, but the alias is safer: it does not replace the configuration
for every other SSH service that might later run on localhost.

The first connection asks OpenSSH to trust the development host key. Then use
the normal protocol commands interactively:

```text
admin> live list
admin> live create "Sunday Service"
admin> exit
```

`exit` and `quit` close the SSH session cleanly.

For a fresh development data directory, bootstrap the first administrator
explicitly. `make run` and `make run-tls` never automatically
import `~/.ssh/id_ed25519.pub`:

```sh
BIBLEIT_BOOTSTRAP_PUBLIC_KEY="$(cat ~/.ssh/id_ed25519.pub)" \\
BIBLEIT_BOOTSTRAP_ACTOR=admin \\
make -C server run-tls
```

The SSH host key must be durable and private. Generate an Ed25519 host key
before the first start:

```sh
ssh-keygen -t ed25519 -f /data/ssh/ssh_host_ed25519_key -N ''
```

Only public-key authentication is used for member sessions. Passwords, port
forwarding, and Erlang shell evaluation are disabled.

#### Public SSH on the standard port

For a public endpoint such as `ssh admin@bibleit.app`, the public TCP port
should be `22`. The application does **not** need to run as root to achieve
this: keep Bibleit listening on an unprivileged internal port (for example,
`2222`) and let the platform map public port `22` to it.

On Fly.io, map public port `22` to the OTP listener’s unprivileged internal
port `2222`. `server/fly.toml` includes this raw TCP service:

```toml
[[services]]
  internal_port = 2222
  protocol = "tcp"
  auto_stop_machines = false
  auto_start_machines = true
  min_machines_running = 1

  [[services.ports]]
    port = 22
    handlers = []
```

Do not attach TLS or HTTP handlers to this service—SSH already encrypts and
authenticates its transport. The Fly app needs an IP configuration that can
accept public TCP port 22; ensure its assigned addresses support that before
enabling the service. After DNS points `bibleit.app` at the app, clients use:

```sh
ssh bibleit.app
```

### Fly.io: recommended edge TLS termination

For Fly.io, prefer Fly-managed certificates and edge TLS termination. The
server continues to listen privately on plaintext port `7070`; Fly accepts TLS
on port `443` and forwards the decrypted TCP stream over Fly's private
backhaul. This avoids distributing Let’s Encrypt private keys into the Erlang
application.

Use a custom domain/certificate for the TCP endpoint, for example
`tcp.bibleit.app`, and configure a TCP service like:

```toml
[[services]]
  internal_port = 7070
  protocol = "tcp"

  [[services.ports]]
    port = 443
    handlers = ["tls", "proxy_proto"]
    proxy_proto_options = { version = "v1" }
    tls_options = { versions = ["TLSv1.2", "TLSv1.3"] }
```

The `tls` handler uses Fly-managed application certificates. `proxy_proto`
preserves the original client address in a HAProxy PROXY protocol v1 header,
which the server consumes before protocol framing. This is important: otherwise
the server's IP-based connection and login limits would see only Fly proxy
addresses. Enable it only behind a trusted proxy:

```erlang
application:set_env(bibleit_server, proxy_protocol, true).
```

Do **not** set `proxy_protocol=true` on a directly exposed plaintext listener:
an arbitrary peer could forge the header and evade IP limits. A Fly deployment
that later exposes raw TCP should use `handlers = ["tls", "proxy_proto"]`.
The default Fly configuration keeps the raw server private, so it does not
enable PROXY protocol. Fly terminates HTTPS for the built-in browser endpoint,
for example `https://live.bibleit.app/lives/<live-id>`. Keep raw TCP separate (such
as `tcp.bibleit.app:443`) only when trusted CLI or service clients genuinely
need public access.

### Fly.io deployment

[`server/fly.toml`](fly.toml) deploys one OTP application as
`bibleit-server`. It serves public HTTPS on internal port `8080`, listens for
raw TCP only on Fly’s private IPv6 network at `fly-local-6pn:7070`, and persists
translations and DETS state at `/data`. Seed its first administrator with an
OpenSSH public key, never a private key.

Deploy the single application:

```sh
fly apps create bibleit-server
fly volumes create bibleit_data --app bibleit-server --region ams --size 1
fly secrets set BIBLEIT_BOOTSTRAP_PUBLIC_KEY="$(cat ~/.ssh/id_ed25519.pub)" --app bibleit-server
fly deploy --config server/fly.toml
```

Point `live.bibleit.app` at this Fly application. The raw TCP service is not
public in the supplied configuration.

## Persistence and deployment

By default, persistent data lives under `~/.bibleit`:

| Data | Default path | Notes |
| --- | --- | --- |
| Translation files and indexes | `~/.bibleit` | Override with `translations_dir`. |
| Actor, role, public-key, token, quota state | `~/.bibleit/authorization.dets` | DETS, owned by one authorization process. |
| Lives, hashed secrets, presentation payload | `~/.bibleit/lives.dets` | DETS, restored when the server starts. |

Public keys are safe to store and are persisted with their fingerprint and
usage metadata. Legacy issued tokens remain hashed at rest but are no longer
accepted by the TCP or browser login flows. Rate-limit counters intentionally
are not persisted and reset on server restart.

Expose the raw TCP listener only to trusted clients or private infrastructure.
Put TLS, DNS, and HTTP reverse-proxy concerns in front of the built-in HTTP
listener (for example, `live.bibleit.app/lives/<live-id>`), not in front of the raw
TCP protocol port.

## OTP release shape

The long-term deployment unit is one `rebar3` release, not an `erl -eval`
command. The release contains the BEAM runtime, the application, Cowboy, the
NIF, browser assets, and bundled translation metadata. Runtime configuration
and secrets remain environment variables.

```sh
cd server
make release

BIBLEIT_BOOTSTRAP_PUBLIC_KEY="$(cat ~/.ssh/id_ed25519.pub)" \
BIBLEIT_DATA_DIR=/var/lib/bibleit \
BIBLEIT_SERVER_PORT=7070 \
BIBLEIT_HTTP_PORT=8080 \
BIBLEIT_SERVER_BIND_ADDRESS=127.0.0.1 \
BIBLEIT_HTTP_BIND_ADDRESS=0.0.0.0 \
_build/prod/rel/bibleit_server/bin/bibleit_server foreground
```

`make release` is the build-time command. Fly runs it inside the Docker build
stage; the running Machine receives only the assembled release and starts it
with `bin/bibleit_server foreground`.

`bibleit_server_app` applies environment configuration before its OTP
supervisor starts. The supervisor owns authorization, translation and Live
actors, bounded TCP connection workers, the raw TCP listener, optional native
TLS listener, and Cowboy HTTP listener. This gives browser and TCP clients the
same LiveSession actors without a network hop.

The container [`Dockerfile`](Dockerfile) builds that release and runs
`bin/bibleit_server foreground`; it is the production entrypoint. Keep a
separate HTTP edge only if a future scaling, isolation, or independent
web-product boundary makes it useful. It is not needed for the current Live
presentation or a future dashboard.
