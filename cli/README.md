# bibleit CLI

bibleit is the native Go client for Bibleit Server protocol version 1. It
implements a useful, typed subset of the API instead of providing a raw-command
escape hatch, so shell input cannot accidentally become protocol input.

The public SSH listener is implemented directly by the OTP server. This module
contains only standalone CLI tooling.

The CLI connects over TLS and authenticates with an OpenSSH Ed25519 key. For
each command it asks local `ssh-keygen` to sign a fresh server challenge. Your
private key is never sent to, printed by, or stored by Bibleit.

Build and test it from the repository root:

    make cli
    make cli-test

Commands:

    bibleit [--server host:port] [--identity path] [--ca-file path] auth login
    bibleit [--server host:port] auth logout|info|whoami
    bibleit [--server host:port] ping
    bibleit [--server host:port] server info
    bibleit [--server host:port] translation list [all]|info|catalog|fetch|delete <translation>
    bibleit [--server host:port] read <translation> <book> [chapter] [verse]
    bibleit [--server host:port] search <translation> <query>
    bibleit [--server host:port] live list|create [name]|delete all
    bibleit [--server host:port] live <id> info|stats|start|stop|pause|resume|subscribe|clear|delete
    bibleit [--server host:port] live <id> set name|reference|translations <value...>
    bibleit [--server host:port] live <id> secret <secret>|set <secret>|rotate|delete
    bibleit [--server host:port] live <id> stack info|clear|pop [count]
    bibleit [--server host:port] live <id> stack push [translation] <book> [chapter] [verse]

`auth login` verifies the configured SSH identity. The default identity is
`~/.ssh/id_ed25519`, with its public half expected at
`~/.ssh/id_ed25519.pub`. Its fingerprint must already be registered with an
actor on the server. There is no saved bearer credential and no device polling
flow.

For the local TLS development server, run:

    make -C server run-tls
    make cli
    ./cli/cli --ca-file server/priv/local-cert.pem auth login
    ./cli/cli --ca-file server/priv/local-cert.pem live list

Use `--identity /path/to/id_ed25519` for a non-default key. `--insecure` is
available only for local development when certificate verification is not
practical; use `--ca-file` or the system trust store in normal use.

Output defaults to a readable table. Use --format raw to preserve the server's
line protocol records, or --format json for a JSON object containing a records
array:

    bibleit live list
    bibleit --format raw live list
    bibleit --format json live list

The CLI reads optional connection defaults from
`$XDG_CONFIG_HOME/bibleit/config.json` (or the operating system’s config
directory). It does not persist a private key, signature, or bearer credential.
Set `BIBLEIT_CONFIG` to use another configuration location in automation.

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
