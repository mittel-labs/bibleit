# bibleit

A fast Bible reader for the terminal.

bibleit is an open source Bible reading project built for people who like focused, keyboard-first tools. It combines a Python terminal UI, a small command-line reader, a live web viewer for audiences, and `libbibleit`, the native library that powers fast translation access.

## Why bibleit

- Read from a clean Textual terminal interface.
- Open multiple translations and keep them synchronized on the same verse.
- Jump quickly with fuzzy references like `dan 9.2`, `john 3:16`, or whole chapters.
- Find remembered verse text in the active translation.
- Browse go-to history and common shortcuts without leaving the app.
- Share the current verse with an audience through bibleit live.
- Use the CLI in scripts or from stdout.

## Install

```sh
pip install bibleit
```

PyPI: [pypi.org/project/bibleit](https://pypi.org/project/bibleit/)

## Quick Start

Open the terminal reader:

```sh
bibleit
```

Read a verse from stdout:

```sh
bibleit -t KJV john 3:16
```

Read a chapter:

```sh
bibleit -t KJV dan 9
```

## Bibleit server and Live web application

[`server/`](server/) contains `bibleit_server`, the Erlang/OTP service for
translation access, live sessions, permissions, optional Live secrets, the
space-based TCP protocol, native SSH access, and the Cowboy HTTP/WebSocket
application that presents Lives to browsers.

For local development, start the OTP service and open
`http://localhost:8080/lives/<id>`. Detailed configuration, command examples,
and browser URLs are in the [server README](server/README.md).

## libbibleit

`libbibleit` is the native core used by the Python package to read indexed Bible translation files efficiently. The Python package builds and bundles this library so users can install `bibleit` from PyPI and run the TUI or CLI without manually compiling the native layer.

The native code lives in [`libbibleit/`](libbibleit/) and the Python package
lives in [`python/`](python/). The existing Python live endpoint remains
available while `bibleit_server` evolves independently.

## Native server CLI

The `cli/` directory contains the native Go client for the TLS line protocol.
It proves possession of an OpenSSH Ed25519 private key against a server
challenge; it does not use browser device login or save bearer credentials.
Build it with `make cli`; see [`cli/README.md`](cli/README.md) for connection
and key setup.

## Website

The project website is published with GitHub Pages from [`docs/`](docs/):

[mittel-labs.github.io/bibleit](https://mittel-labs.github.io/bibleit/)

## Project Layout

- [`python/`](python/) - Python package, Textual app, CLI, and tests.
- [`server/`](server/) - Erlang/OTP multi-live service, TCP/TLS/SSH protocols, and Cowboy web application.
- [`libbibleit/`](libbibleit/) - Native translation/index reader and search engine.
- [`docs/`](docs/) - Static project website for GitHub Pages.

## Contributing

Issues, ideas, and pull requests are welcome. bibleit is MIT licensed and intentionally small enough to understand, extend, and shape.
