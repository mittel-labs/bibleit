# Implementation status

Updated 2026-10-10. Counts describe explicit acceptance items, not estimated
percentages of the entire project. The full plan is in `plan.md`.

## Milestone 1: verify the integration contract

| Item | Status | Evidence / remaining work |
| --- | --- | --- |
| Operation and transport inventory | Complete | `contract/features.md` separates server availability, authentication, and client support |
| Shared request/response fixtures checked against source | Complete | 27 decoder cases and 18 encoder cases verified by compiling current Erlang source |
| Client safeguards for known incompatibilities | Complete | SECRET SET no longer becomes authentication; identical stats fields accepted, conflicts rejected; request size and JSON errors covered; command-aware framing handles single-record translation replies with count |
| Isolated server authentication/security checks | Complete for targeted coverage | 7 security cases (including SSH revocation), 4 PKCE cases, and 4 SSH cases; isolated source/dependency snapshot and disposable container/database; no developer .env |
| Go client against a real HTTP listener | Complete for core smoke coverage | Ping, identity, translation add/remove/list, named verse/numeric chapter reads, search, Live create/list/info/stats/start/stop/pause/delete/push, quota errors, expired credentials, and not-found handling |
| Complete integration coverage required by milestone gate | Complete for named core operations | HTTP translation/Live/expiry/quota checks plus actual CLI OpenSSH verse/pause/disconnect/reconnect/closure; assessment fixed normal deletion during stream authorization changes |
| Resolve server documentation/parser and encoder discrepancies | Waiting on server changes | SECRET SET mismatch and repeated connections in stats; assessment fixed scoped-token encoding and SSH deletion closure |

Progress: **6 of 7 tracked milestone-1 items complete**. Source fixtures,
targeted server security checks, all Go HTTP checks and the CLI OpenSSH
subscription check pass against the updated baseline. The assessment fixed
both scoped-token encoding and the intermediate normal-deletion regression.

The milestone gate remains open until the server contract discrepancies are
resolved. These checks cover the named core operations, not the full security
assessment or future workspace/event APIs.

## Remaining milestones

| Milestone | Status | Progress |
| --- | --- | --- |
| 2. Complete verified Go client surface | Complete for tracked core | 5/5 acceptance items and complete HTTP/SSH integration pass; future API expansion remains separate |
| 3. Customer CLI profiles/auth/output | In progress | 4/5 tracked items complete: profiles, credentials, output and completion/destructive UX; native Windows execution remains |
| 4. Workspace and event integration APIs | Pending server contract | Existing browser endpoints are not bearer-token client APIs |
| 5. Python, Ruby, Rust clients | Not started | Wait for verified core contract |
| 6. Independent publication | Not started | Stable package paths and monorepo/TUI migration decision required |

## Reproduce verification

```sh
go test -race ./...
go vet ./...
python3 scripts/check_server.py
python3 scripts/check_server.py --integration --baseline contract/server-baseline.json
```

The source check needs Erlang/OTP with its JSON module. Integration additionally
needs Go 1.27.1, Docker with the local `postgres:17-alpine` image, built server
dependencies/NIF, and the sibling server checkout. It creates a uniquely named
loopback-only temporary container and random database, compiles source into a
temporary source/dependency snapshot, skips asset symlinks, detects concurrent Erlang source edits during copying, and removes its container on success or failure. It does
not build or modify the server checkout or load the development .env.

The regular Go test run skips live-server integration; the isolated harness runs
it explicitly. Server tests and client HTTP tests are separate evidence, both
reported by the harness. Shared malformed/future-response fixtures are decoder
tests, not claims that the server encoder emits malformed or hypothetical data.

## Previous increment and assessment coordination

The server security assessment chat is `01a12273-bf8b-7e30-826c-6354f7307511`.
Its latest completed turn reports fixes for unverified OAuth emails and disabled
user/account authority. This client work reads that checkout and uses a copied
snapshot; it does not edit the server or its assessment files.

Completed in this increment:

- Fixed finite reply framing for account translation list/add/remove. These
  responses contain `count` but have no `END`. HTTP and CLI SSH exec now pass
  the validated command into the decoder; truncated multi-record replies still fail.
- Added synthetic translation data to the disposable fixture, with real native
  indexes. No external translation download is needed.
- Verified expired bearer rejection and Live quota errors through the Go client;
  manual token quota rejection is a separate server fixture assertion.
- Added SSH revocation and key tests. Server tests cover Ed25519, RSA SHA-2,
  ECDSA P-256/P-384/P-521, and rejection of weak/legacy algorithms. They do not
  yet prove the CLI accepts every server-supported key type.
- Copied source, dependencies, native binaries, and selected public runtime assets
  into the temporary harness directory; local certificates, SSH keys and
  development data are excluded.
- Passed Go race tests and vet on Go 1.27.1.

## Previous increment: CLI SSH identity and subscriptions

- CLI explicit identities now accept Ed25519, RSA >=2048 bits, and ECDSA
  P-256/P-384/P-521. OpenSSH validates the public-key contents. Generated-key
  tests exercise all accepted types and rejection of weak RSA.
- Subscription decoding requires an initial acknowledgement, preserves server
  error metadata, rejects incomplete records and unexpected envelopes, and
  accepts verse records larger than the previous scanner's 64 KiB limit.
- Unexpected disconnects fail explicitly. Live closure succeeds; revoked access
  fails. Ctrl-C cancels the OpenSSH child, and all exit paths reap it.
- A new root-package integration test uses a disposable RSA identity and
  temporary known_hosts file. It receives a pushed verse, pauses the Live,
  disconnects, reconnects to a fresh paused snapshot, and receives closure
  after deletion. This proves explicit reconnect, not automatic replay.
- Go race tests, vet, build, 17 decoder fixtures, 7 encoder fixtures, 7 security
  cases, 8 PKCE/SSH cases, Go HTTP checks, and the CLI SSH test pass.

The assessment chat is active again and is changing server resilience behavior.
One snapshot failed to compile while those edits were underway; a fresh snapshot
then compiled and all integration checks passed. No server edits were made here.

Milestone 1 still awaits the server SECRET SET documentation/parser discrepancy
and duplicate stats field resolution.

## Previous increment: discovery and account results

| Milestone 2 acceptance item | Status | Evidence / remaining work |
| --- | --- | --- |
| Server info and permission-aware discovery | Complete | Typed GetServerInfo/Help; builders; CLI server help; real HTTP checks |
| Personal account and effective quotas | Complete | Typed GetAccountInfo/ListQuotas; CLI account info/quotas; numeric/count validation, zero/unlimited distinction and raw fields |
| Translation metadata and reference catalogue | Complete | Typed Go methods and CLI; real metadata/catalogue checks, source ID preservation and strict hierarchy validation |
| Typed identity, reading, Live and token metadata | In progress | Identity, readings and Live results verified; token metadata remains |
| Library PKCE exchange and credential revocation | Pending | Browser interaction stays in CLI; extract the transport methods |

Milestone 2 progress: **3 of 5 tracked acceptance items complete**. Milestone 1
remains **6 of 7**, awaiting server discrepancies.

Account notifications revealed that the server emits opaque Erlang maps with
spaces and, for larger maps, physical line breaks. The decoder now preserves
balanced compound values without evaluating them. Regression checks reject
malformed maps and newlines outside compounds. Typed results retain Raw for
future fields and original logical wire records.

The disposable PostgreSQL readiness probe now waits for TCP, avoiding the
initialization-only Unix socket which can briefly report ready before restart.
No server checkout changes were made.

## Previous increment: translation metadata and reference catalogue

| Item | Status | Evidence |
| --- | --- | --- |
| Validated INFO/CATALOG command builders | Complete | Reject empty/injected arguments; shared server decoder fixtures |
| Typed translation metadata | Complete | Names, edition, rights, attribution/trademark and unknown fields retained; real HTTP checks pass after assessment fix |
| Typed reference catalogue | Complete | Ordered source IDs, localized names, sparse chapter numbers and verse counts; strict hierarchy/count/duplicate validation |
| CLI translation info/catalog | Complete | Same builders and existing HTTP/SSH adapters; local CLI tests pass |
| Live catalogue and existing core integration | Passing | Installed synthetic data, 19 books, Psalms 1 and 23, missing translation; existing HTTP/SSH/security checks pass |
| Live metadata integration | Passing | Assessment session fixed binary encoder keys; fresh snapshot verification passes; no server files edited here |
| Documentation and shared fixtures | Complete | 21 decoder fixtures and 12 server encoder fixtures, including binary metadata keys |

Milestone 2 is now **3/5 complete**. Milestone 1 remains **6/7** pending its
server protocol discrepancies. Both metadata and catalogue now pass against a
fresh server snapshot after the assessment's encoder fix.

The original metadata failure was left visible, and the assessment was messaged
at the user's request. The harness now finishes independent HTTP/SSH/EUnit
checks before reporting client failures; failing runs do not overwrite the
passing baseline. Go race tests, vet, build, 21 request decoder fixtures,
12 response encoder fixtures, 7 security cases, 8 PKCE/SSH cases, and HTTP/CLI SSH
integration pass.



## Previous increment: typed identity, reading and Live results

| Item | Status | Evidence |
| --- | --- | --- |
| Identity model | Complete | GetIdentity preserves provider, display identity, roles/permissions and unknown fields; strict auth boolean; real HTTP check |
| Reading/search models | Complete | Single verse, chapter, whole book, search and empty search; coordinates remain optional where absent; real indexed data |
| Live state models | Complete | Typed create/get/list/settings; omitted manager fields distinct from false/zero; real HTTP checks |
| Live statistics and stack | Complete | Connection counters/details verified with a real SSH subscriber, durations/revision, stack positions; malformed counts/positions rejected |
| Live mutation results | Complete | Push/pop payloads and start/stop/pause/resume/clear/delete acknowledgements; real lifecycle checks; no retries |
| Raw API compatibility and example | Complete | Existing raw methods retained; standalone read example uses typed values |
| Token metadata | Pending | Still required by the broader milestone-2 typed-results acceptance item |

Requested slice: **3/3 domains complete** (identity, reading, Live). Milestone 2
remains **3/5 acceptance items complete**: token metadata is the remaining part
of item 4; library PKCE exchange/revocation is item 5. Milestone 1 remains 6/7.

Go race tests, vet, build, 26 request fixtures, 15 encoder fixtures and isolated
HTTP/security/PKCE/SSH integration pass. No server files were edited here.
Next at that point: typed personal token metadata, then library authentication transport.


## Previous increment: typed token metadata

| Item | Status | Evidence |
| --- | --- | --- |
| Token command builder and CLI listing | Complete | AccountTokensCommand and account tokens; existing HTTP/SSH adapters and output modes |
| Typed token metadata | Complete locally | ListTokens/TokenList/TokenMetadata; nil versus zero/false/empty, timestamps, scopes, issuer/source and raw fields |
| Decoder compatibility | Complete | Server control-character escaping; Unicode labels; count/type/ID/numeric/boolean validation and error preservation |
| Compiled source fixtures | Passing | 27 request cases and 17 response encoder cases, including empty token list and control escapes |
| Real scoped-token listing | Blocked by server | HTTP 500: permission tuples passed as character-list text; active scoped and restricted credentials expose regression |
| Existing integration | Passing | Other HTTP operations, CLI SSH subscription, 7 security cases and 8 PKCE/SSH cases |

Progress: **3/4 requested implementation/verification items complete** (command,
model, decoder; real token integration remains blocked). Milestone 2 remains
**3/5** until its typed-results acceptance item is fully verified. Milestone 1
remains **6/7** and now also tracks the token scope encoder discrepancy.

Local Go race tests, vet and build pass on Go 1.27.1. The failing scoped-list integration leaves the
last passing baseline untouched. No server files were changed here. Server
fixes stay with the assessment. On 2026-10-10, the user authorized messaging
the assessment; the confirmed scoped-token encoder failure and suggested CSV
fix were sent to chat 01a12273-bf8b-7e30-826c-6354f7307511. Next: verify the assessment fix, then extract library PKCE
exchange and revocation.


## Previous increment: authorization transport and token verification

| Item | Status | Evidence |
| --- | --- | --- |
| Token metadata server compatibility | Complete | Assessment's scope CSV fix; real manual/scoped listings, permission denial, escaped labels and expired/revoked filtering |
| Library code exchange | Complete | NewAuthClient/ExchangeCode, typed result and retained JSON fields; bounded form/response, cancellation and redirect rejection |
| Library revocation | Complete | RevokeCredential; HTTP 204 acknowledgement, status/code/metadata errors and no retries |
| CLI delegation and failed logout | Complete | Browser exchange and logout use library methods; failed revocation preserves memory/disk profile; 401 clears unusable profile |
| Real authentication lifecycle | Passing | Exchange/use, code reuse, bad verifier consumption, revoke/use-after-revoke and repeat-revoke denial |
| Full integration gate | Passing | Fresh snapshot: all HTTP, CLI SSH, 7 security cases, 8 PKCE/SSH cases; baseline updated after assessment fixed normal closure |

Requested increment: **5/5 implementation/verification items complete**.
Milestone 2 has **5/5 tracked acceptance items complete** and its full
integration checks pass. Milestone 1 is back to **6/7**, awaiting the existing
SECRET SET documentation/parser mismatch and duplicate stats field resolution.

The user authorized ongoing coordination of integration regressions with the
assessment. The assessment fixed both scope encoding and normal SSH closure;
a fresh full run passes and updates server-baseline.json. Go 1.27.1 race tests,
vet and build pass; 27 request and 18 response encodings verify against compiled
source. No server files were changed here. Next: endpoint-bound named CLI
profiles and stable output; retain the unresolved protocol safeguards.


## Previous increment: endpoint-bound profiles and stable output

| Requested item | Status | Evidence |
| --- | --- | --- |
| Profile storage and migration | Complete | Version-1 named profiles, explicit transport/endpoint, active selection, atomic 0600 writes; legacy credentials bind to binary defaults and migrate on write |
| Selection, authentication and automation | Complete | Profile add/use/list/show/remove; --profile/BIBLEIT_PROFILE precedence; HTTP-only BIBLEIT_TOKEN is never saved; logout retains binding and other profiles; no HTTP-to-SSH fallback |
| Stable finite JSON | Complete | Schema version 1, typed record fields, absent versus empty distinction, unknown string retention, structured stderr errors and exit codes; profile listings omit tokens |
| Subscription NDJSON | Complete | Per-record envelopes, event names, native base64-JSON verse payload, retained raw record, unexpected EOF/revocation handling and cancellation on output failure |
| Verification and documentation | Complete | Race/vet/build; full isolated HTTP/SSH/security integration; matching HTTP/SSH JSON; six cross-compilation targets; output contract and profile examples |

Requested increment: **5/5 complete**. Milestone 2 remains **5/5** and milestone 1
remains **6/7**. Milestone 3 is **3/5 tracked acceptance items complete**:

| Milestone 3 item | Status | Remaining work |
| --- | --- | --- |
| Named endpoint-bound profiles and explicit transport | Complete | Implemented and real-server routing verified |
| Browser/SSH authentication and automation credentials | Complete for current server surface | Library transport, cached revocation semantics, scopes/expiry/quota and SSH validation checked |
| Stable table/raw/JSON/NDJSON output and errors | Complete for documented version 1 | See output.md; JSON is typed protocol records, not Go domain struct serialization |
| Release UX, shell completion and destructive-command behavior | In progress | Add completion and finalize destructive-command UX; subscriptions already support Ctrl-C and explicit reconnect |
| Native supported-platform validation | Partial | Native macOS/arm64 and Linux/arm64 race/vet/process checks pass; Fish runtime passes; Windows native and hosted runs pending |

The expanded harness tests CLI JSON on real HTTP account/discovery/translation/
reading/Live replies, verifies HTTP/SSH Ping envelopes match, and renders actual
SSH verse/pause/reconnect/closure events through NDJSON. All existing 7 security
and 8 PKCE/SSH cases pass; the successful baseline is updated. No server files
were edited here. The existing SECRET SET/stats safeguards remain.

Next: shell completion and destructive-command UX, then native platform CI and
publication/package-path decisions. Workspace APIs still await a public server
contract; no organization/browser endpoint wrappers were introduced.


## Previous increment: shell completion and destructive-command UX

| Item | Status | Evidence |
| --- | --- | --- |
| Command/flag/profile completion | Complete | Shared local candidate helper; values, nested Live verbs, local names, terminator handling; no server requests or profile writes |
| Bash, Zsh and Fish script generation | Complete with runtime caveat | Bash/Zsh syntax and actual executable candidate forwarding pass; Zsh source/autoload supported; Fish is unavailable locally and its runtime check remains pending |
| Scoped destructive-command confirmation | Complete | Live delete/all, stack clear/pop, secret rotate/delete; endpoint/profile/target prompt; bulk deletion requires `delete all`; cancellation/EOF sends no request |
| Automation and stable errors | Complete | Strict boolean --yes; JSON/noninteractive confirmation_required exit 2; cancellation exit 1; dispatch exactly once, invalid commands rejected, credentials never displayed |
| Verification and documentation | Complete for available local tools | Go 1.27.1 race/vet/build, native macOS PTY cancellation, six CGO-free cross-builds; README/help/output contract updated |

Requested implementation increment: **5/5 complete**, with **Fish runtime
verification pending** because Fish is not installed locally. Milestone 3 is now
**4/5 acceptance items complete**; native Linux/Windows validation remains its
platform gate. Cross-compilation is not native platform validation. Milestones
1 and 2 remain **6/7** and **5/5**, respectively.

The destructive guard runs after command validation and before the shared
HTTP/SSH request path. Request-boundary tests prove missing confirmation sends
zero requests and --yes dispatches once. Existing client/server transport code
and server files are unchanged; this increment uses local tests and shell/PTY
checks and does not claim a new full server-integration run.

Next: native platform CI (including Fish runtime validation), then independent
publication and package-path decisions.


## Latest increment: native validation and Fish runtime

| Item | Status | Evidence / remaining work |
| --- | --- | --- |
| Native CI and reproducible process harness | Complete locally | Ubuntu/Windows/macOS matrix; exact Go 1.27.1; race/vet/build; profile replacement, spaced paths, loopback HTTP, JSON and destructive guards; workflow YAML parsed |
| Native Linux validation | Passing on arm64 | Disposable official Go Linux container on Docker's Linux/arm64 VM; race/vet/build and actual CLI/PTY checks pass (PTY, not emulation of Windows) |
| Fish runtime validation | Passing | Fish 3.6.0 syntax and nine actual complete -C cases; no HTTP fixture requests or profile writes; Bash/Zsh same cases pass |
| Windows-specific correctness and tests | Implemented, cross-compiled | User-only config ACL before writing credentials; actual saved DACL checks before/after replacement; real console-handle/CRLF test; Windows test binary compiles |
| Native Windows execution and hosted CI evidence | Pending environment | No Windows host; GitHub CLI unauthenticated; local checkout uncommitted. Ready workflow must be published/run before this item can pass |

Progress: **4/5 requested tracked items delivered; native Windows execution is
pending**. Milestone 3 stays **4/5 acceptance items complete** until the native
platform gate passes. Milestones 1/2 stay **6/7** and **5/5**. The user was asked
which Windows execution environment to use; publication has not been assumed.

The successful Linux log is `/tmp/bibleit-linux-native.log`. macOS native process,
HTTP-fixture, PTY and shell checks also pass. Native process smoke fixtures are
separate from real-server integration; no fresh full server suite is claimed by
this increment. See `native-validation.md` for exact coverage and reproduction.
No server files were edited. The disposable Linux container is removed after
execution, and its read-only source snapshot excludes Git/config/developer data.


## Publication preparation

The user selected GitHub Actions after publishing this checkout. The initial
commit is prepared on `codex/native-validation`; the native workflow will
run on push. GitHub SSH returned `Repository not found` for the configured
`mittel-labs/bibleit-cli` remote, and GitHub CLI is unauthenticated. This does not
establish whether the repository is absent or inaccessible to the current SSH
identity. The user selected a different repository; its URL and authenticated access are
required before publication and native Windows execution.
