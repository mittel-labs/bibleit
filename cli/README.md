# bibleit CLI

bibleit is the native Go client for Bibleit Server protocol version 1. It
implements a useful, typed subset of the API instead of providing a raw-command
escape hatch, so shell input cannot accidentally become protocol input.

The CLI supports two cached authentication profiles:

- `bibleit auth login` opens a dedicated Bibleit CLI sign-in flow, completes email or OAuth sign-in,
  and stores a revocable access token.
- `bibleit auth login ssh` verifies a native SSH connection using the identities
  selected by OpenSSH configuration and your SSH agent. Use `--identity <path>`
  only to select a specific private key.

Every later typed command automatically uses the active profile.

Build and test it from the repository root:

    make cli
    make cli-test

## Versioning

The CLI and server are released independently:

- [`cli/VERSION`](VERSION) is the Bibleit CLI version.
- [`server/VERSION`](../server/VERSION) is the Bibleit Server version.
- Protocol compatibility is reported separately as `protocol_version`.

Use the local version command to inspect the installed client, and server info
to inspect the server to which it is authenticated:

    bibleit version
    # bibleit CLI version 0.1.0

    bibleit server info
    # includes version=<server version> and protocol_version=1

From the repository root, `make versions` prints both release versions. The
root build injects only `cli/VERSION` into the CLI binary; changing the server
version no longer changes a CLI build.

Commands:

    bibleit version
    bibleit auth login
    bibleit auth login ssh [--identity <private-key>]
    bibleit auth logout|info|whoami
    bibleit ping
    bibleit server info
    bibleit translation list
    bibleit translation add|remove <translation>
    bibleit read <translation> <book> [chapter] [verse]
    bibleit search <translation> <query>
    bibleit live list|create [name]|delete all
    bibleit live <id> info|stats|start|stop|pause|resume|subscribe|clear|delete
    bibleit live <id> set name|reference|translations <value...>
    bibleit live <id> secret <secret>|set <secret>|rotate|delete
    bibleit live <id> stack info|clear|pop [count]
    bibleit live <id> stack push [translation] <book> [chapter] [verse]

For web authentication, the CLI starts a temporary loopback callback, opens
the built-in Bibleit web URL in the default browser, and asks the signed-in
account to approve the terminal. The authorization code is protected with PKCE
and exchanged for a persistent account token; the token never appears in the
browser URL.

For SSH authentication, the CLI first delegates identity selection to OpenSSH,
including matching `~/.ssh/config` entries and keys loaded in your SSH agent.
When `--identity` is supplied, the private key and its `.pub` file must both
exist and the public key must be Ed25519. Its fingerprint must already be
registered with an account. The SSH transport username is `bibleit-cli`; the
server identifies the account from the key fingerprint, not that username.

For the local SSH development server, generate a dedicated key and run:

    ssh-keygen -t ed25519 -f ~/.ssh/bibleit_local_dev -C bibleit-local-dev
    make -C server run
    make cli CLI_SSH_SERVER=127.0.0.1:2222 CLI_WEB_URL=http://127.0.0.1:8080
    ./cli/cli auth login

After web sign-in, open the dashboard and add the contents of
`~/.ssh/bibleit_local_dev.pub` under **SSH keys**. Only then will SSH login
succeed:

    cat ~/.ssh/bibleit_local_dev.pub
    ./cli/cli auth login ssh
    # If OpenSSH does not select the intended key:
    ./cli/cli auth login ssh --identity ~/.ssh/bibleit_local_dev
    ./cli/cli live list

On the first connection, OpenSSH saves a previously unseen server host key in
`known_hosts`; it still rejects a host whose saved key later changes. Every
SSH-backed command creates a fresh authenticated SSH connection using the
cached settings.

With email or OAuth configured, the equivalent web flow is:

    ./cli/cli auth login
    ./cli/cli live list

`bibleit auth logout` revokes the cached web token on the server and clears the
active local profile. Remote web URLs must use HTTPS; plain HTTP is accepted
only for loopback local development. The SSH server and web URL are compiled
into the binary, not accepted as runtime flags. Local builds can override them
with `CLI_SSH_SERVER` and `CLI_WEB_URL` as shown above.

Output defaults to a readable table. Use --format raw to preserve the server's
line protocol records, or --format json for a JSON object containing a records
array:

    bibleit live list
    bibleit --format raw live list
    bibleit --format json live list

The CLI stores its active profile in `~/.bibleit/config.json` with directory
mode `0700` and file mode `0600`. Set `BIBLEIT_CONFIG` to use another location
in automation. A web profile contains only its revocable access token. An SSH
profile may contain an explicitly selected identity path; it never contains the
private key itself.

For example:

```json
{
  "access_token": "bt_..."
}
```

Because the file contains a web access token, do not commit or share it.

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
