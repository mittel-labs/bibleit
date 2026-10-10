# bibleit CLI

bibleit is the Go CLI for Bibleit Server protocol version 1, built on the
[Go client](clients/go/README.md). It
implements a useful, typed subset of the API instead of providing a raw-command
escape hatch, so shell input cannot accidentally become protocol input.

The CLI supports named profiles, each bound to one server endpoint and transport:

```sh
bibleit profile add production --endpoint https://bibleit.example
bibleit --profile production auth login
bibleit profile add local-ssh --endpoint 127.0.0.1:2222 --transport ssh
bibleit --profile local-ssh auth login --identity ~/.ssh/bibleit_local_dev
bibleit profile use production
bibleit profile list
```

`--profile` selects a profile for one command. Otherwise `BIBLEIT_PROFILE`, then
the saved active profile, selects it. Adding the first profile makes it active;
adding another does not switch the active profile. Existing profile names cannot
be overwritten with another endpoint. HTTP commands use only that profile's
bearer credential; SSH commands use its endpoint and OpenSSH configuration/agent.

`auth login` opens browser authorization for an HTTP profile and verifies SSH
for an SSH profile. `auth login ssh` remains an explicit SSH alias. Use
`--identity` only with SSH. Web logout keeps the cached credential if revocation
fails; successful revocation or an already unauthorized credential clears it.
Logout retains the profile's endpoint/transport and leaves other profiles intact.
SSH logout clears the cached identity selection; registered keys and the SSH
agent remain under your control.

For automation, set `BIBLEIT_TOKEN` through your environment/secret store and
select an HTTP profile. It overrides the cached bearer for data commands and
`auth info`, without being saved or printed in profile listings. Login/logout
operate on cached credentials rather than the environment token. Use `--` before
literal command arguments that would otherwise be interpreted as global flags.

Use Go 1.27.1 or newer. Build and test it from the repository root:

    go build -ldflags "-X main.cliVersion=$(cat VERSION)" -o cli .
    go test ./...

## Versioning

The CLI and server are released independently:

- [`VERSION`](VERSION) is the Bibleit CLI version.
- [`bibleit-server/VERSION`](../bibleit-server/VERSION) is the Bibleit Server version.
- Protocol compatibility is reported separately as `protocol_version`.

Use the local version command to inspect the installed client, and server info
to inspect the server to which it is authenticated:

    bibleit version
    # bibleit CLI version 0.1.0

    bibleit server info
    bibleit server help [topic]
    bibleit account info
    bibleit account quotas
    bibleit account tokens
    bibleit translation info <translation>
    bibleit translation catalog <translation>
    # includes version=<server version> and protocol_version=1

The build above injects only this repository’s `VERSION` into the CLI binary;
changing the server version does not change a CLI build.

Commands:

    bibleit version
    bibleit auth login
    bibleit auth login ssh [--identity <private-key>]
    bibleit auth logout|info|whoami
    bibleit ping
    bibleit server info
    bibleit account info|quotas|tokens
    bibleit translation list
    bibleit translation add|remove <translation>
    bibleit read <translation> <book> [chapter] [verse]
    bibleit search <translation> <query>
    bibleit live list|create [name]|delete all
    bibleit live <id> info|stats|start|stop|pause|resume|subscribe|clear|delete
    bibleit live <id> set name|reference|translations <value...>
    bibleit live <id> secret <secret>|create|rotate|delete
    bibleit live <id> stack info|clear|pop [count]
    bibleit live <id> stack push [translation] <book> [chapter] [verse]

For web authentication, the CLI starts a temporary loopback callback, opens
the selected HTTP profile’s URL in the default browser, and asks the signed-in
account to approve the terminal. The authorization code is protected with PKCE
and exchanged for a persistent account token; the token never appears in the
browser URL.

For SSH authentication, the CLI first delegates identity selection to OpenSSH,
including matching `~/.ssh/config` entries and keys loaded in your SSH agent.
When `--identity` is supplied, the private key and its `.pub` file must both
exist. The CLI uses `ssh-keygen` to validate Ed25519, RSA (at least 2048 bits),
and ECDSA P-256/P-384/P-521 public keys. Its fingerprint must already be
registered with an account. The SSH transport username is `bibleit-cli`; the
server identifies the account from the key fingerprint, not that username.

For the local SSH development server, generate a dedicated key and run:

    ssh-keygen -t ed25519 -f ~/.ssh/bibleit_local_dev -C bibleit-local-dev
    make -C ../bibleit-server run
    go build -o cli .
    ./cli profile add local-http --endpoint http://127.0.0.1:8080
    ./cli profile add local-ssh --endpoint 127.0.0.1:2222 --transport ssh
    ./cli --profile local-http auth login

After web sign-in, open the dashboard and add the contents of
`~/.ssh/bibleit_local_dev.pub` under **SSH keys**. Only then will SSH login
succeed:

    cat ~/.ssh/bibleit_local_dev.pub
    ./cli --profile local-ssh auth login --identity ~/.ssh/bibleit_local_dev
    ./cli --profile local-ssh live list

On the first connection, OpenSSH saves a previously unseen server host key in
`known_hosts`; it still rejects a host whose saved key later changes. Every
SSH-backed command creates a fresh authenticated SSH connection using the
cached settings.

With email or OAuth configured, the equivalent web flow is:

    ./cli --profile local-http auth login
    ./cli --profile local-http live list

Profiles are stored in `~/.bibleit/config.json`, with newly created directories
mode `0700` and file writes mode `0600` on Unix. On Windows, each new config
file receives a current-user-only ACL before credentials are written; failed
ACL setup aborts saving. Existing files are hardened on the next successful
write. `BIBLEIT_CONFIG` selects another
file. The versioned file stores active_profile and a profiles map; each entry
contains transport, endpoint and optional access_token/identity. SSH private keys
are never stored in this file. Legacy token/identity files load as `default`,
bound to the current binary’s configured default endpoint, and are migrated on the next write.
A new installation has an implicit local HTTP default; creating a profile
replaces that implicit default. Built-in defaults can still be set at build time.

`profile show [name]` inspects metadata; `profile use <name>` selects an active
profile. `profile remove <name>` requires another active profile and, for cached
HTTP credentials, logout first. List/show never reveal bearer values.

Output defaults to a readable table. Use `--format raw` to preserve finite
protocol records, `--format json` for a version-1 typed record envelope, or
`--format ndjson` for an SSH subscription with one object per record. Finite
commands reject ndjson; subscriptions reject json. Error envelopes go to stderr
and retain server metadata. Human tables escape embedded control characters.
See [the stable output contract](docs/output.md) for types and examples.

```sh
bibleit --profile production --format json account tokens
bibleit --profile local-ssh --format ndjson live <id> subscribe
bibleit --profile production --format raw live list
```

Exit codes are stable:

| Code | Meaning |
| --- | --- |
| 0 | Success |
| 1 | Network, server, or local failure |
| 2 | Invalid CLI usage |
| 3 | Authentication required or credential rejected |
| 4 | Permission denied |
| 5 | Requested resource not found |
| 6 | Conflict or quota rejection |
| 7 | Rate limited |

## Client development

See the [item-by-item progress](docs/status.md),
[operation inventory](contract/features.md), and [revised implementation plan](docs/plan.md), reviewed against the server
working tree on 2026-10-09. The current CLI is a development draft; organization
management and bearer-authenticated event watching are not implemented.

The reusable [Go client](clients/go/README.md) owns validated customer commands,
HTTP transport, and finite response decoding. The CLI owns browser login,
profiles, terminal output, and its OpenSSH adapter. The shared protocol contract
and response fixtures are documented in [contract/README.md](contract/README.md).

The client currently shares this Go module; independent client modules and the
move into a client monorepo are planned follow-up work. Python, Ruby, and Rust
clients have not been implemented yet.

Run a standalone client example with an existing account token:

```sh
BIBLEIT_ENDPOINT=https://your-server BIBLEIT_TOKEN=your-token go run ./examples/go/read
```

`secret set <value>` is rejected until the server command API supports custom
secret setting. Use `secret create` or `secret rotate` to
generate a server-managed secret. Live subscriptions require an SSH profile.

Subscriptions begin with a current Live snapshot, then emit live changes. Live
closure ends the watch successfully; revoked access and unexpected disconnects
return errors. Ctrl-C stops the SSH child cleanly. After a disconnect, run the
subscription command again to obtain a fresh snapshot. Protocol v1 does not
provide event replay or a resume cursor, so intervening events are not replayed.
Arguments containing embedded double quotes are rejected because the server's
current request tokenizer cannot represent them reliably.

## Shell completion

Generate scripts with `bibleit completion bash`, `bibleit completion zsh`, or
`bibleit completion fish`. Generation works without authentication or a valid
profile file. It prints the script and does not change your shell settings.

For the current Bash session:

```sh
source <(bibleit completion bash)
```

For Zsh, initialize completion first:

```sh
autoload -Uz compinit
compinit
source <(bibleit completion zsh)
```

Alternatively, save Zsh output as `_bibleit` in a directory on `$fpath` before
running `compinit`. For Fish:

```fish
mkdir -p ~/.config/fish/completions
bibleit completion fish > ~/.config/fish/completions/bibleit.fish
```

Completion covers command words, flags, format/transport values and local
profile names. Use separate words for option-value completion, for example
`--profile prod`. Completion never contacts the server, writes configuration,
or suggests tokens, secrets, Live IDs or translation/reference data. An invalid
profile file yields no profile suggestions. Script generation accepts the
normal or raw format; JSON/NDJSON are not script formats.

## Destructive commands

Live deletion (including `live delete all`), stack clear/pop, and secret
rotation/removal require confirmation before a request is sent. A terminal
prompt shows the profile, transport, endpoint and affected target. Type `yes`
for a single target, or `delete all` for bulk deletion. An empty answer, another
answer, EOF or an overlong answer cancels without sending a request.

Both stdin and stderr must be terminals for prompting. JSON output and
noninteractive use require `--yes`:

```sh
bibleit --profile production live session-id delete --yes
bibleit --profile production --format json live delete all --yes
```

`--yes` confirms the command once; server authentication and permissions still
apply, and failed mutations are not retried. It takes no value (`--yes=false`
is rejected). Options after `--` are literal command arguments.

Cancellation exits **1**. Missing confirmation exits **2**, with error code
`confirmation_required` in JSON; cancellation uses `cancelled`. Errors go to
stderr and leave stdout empty. Read commands, reversible Live controls/settings,
translation library removal, logout and removal of a logged-out inactive profile
retain their existing behavior. Creating a secret cannot replace an existing
secret; use guarded rotation to replace one.


## Native platform checks

The [native CI workflow](.github/workflows/native.yml) pins Go 1.27.1 and runs
race tests, vet, builds and executable smoke checks on Ubuntu, Windows and macOS.
Linux also runs actual Bash/Zsh/Fish completion. See
[native validation](docs/native-validation.md) for commands, coverage and pending
hosted/Windows execution. Native macOS/arm64 and Linux/arm64 checks pass locally;
Windows cross-builds pass, but native Windows execution has not yet been run.
