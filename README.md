# bibleit

A fast Bible reader for the terminal and the browser.

bibleit is an open source Bible reading project. It combines a keyboard-first terminal UI, a web operator for everyone else, a small command-line reader, a live view for audiences, and `libbibleit`, the native library that powers fast translation access.

## Why bibleit

- Read from a clean Textual terminal interface, or run the whole thing in a browser.
- Open multiple translations and keep them synchronized on the same verse.
- Jump quickly with fuzzy references like `dan 9.2`, `john 3:16`, or whole chapters.
- Find remembered verse text in the active translation.
- Browse go-to history and common shortcuts without leaving the app.
- Share the current verse with an audience through bibleit live, over your own network or the hosted relay.
- Use the CLI in scripts or from stdout.

## Install

```sh
pip install bibleit
```

Or, without installing anything permanently:

```sh
uvx bibleit --web
```

PyPI: [pypi.org/project/bibleit](https://pypi.org/project/bibleit/)

## Quick Start

### In a browser, in three steps

```sh
pip install bibleit
bibleit --web
```

1. `bibleit --web` opens the operator in your browser.
2. Pick a translation. It downloads once and then works offline.
3. Press **Go live** and share the address or QR code with the room.

Everyone on your network can open the audience view; nothing else needs
installing, and no account is involved. The operator itself answers only on the
machine running it.

### In the terminal

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

Start the operator and the audience view together:

```sh
bibleit --web 0.0.0.0 8000
```

Start only the relay, with no reader attached — what the hosted deployment runs:

```sh
bibleit --live 0.0.0.0 8000
```

## libbibleit

`libbibleit` is the native core used by the Python package to read indexed Bible translation files efficiently. The Python package builds and bundles this library so users can install `bibleit` from PyPI and run the TUI or CLI without manually compiling the native layer.

The native code lives in [`libbibleit/`](libbibleit/) and the Python package lives in [`python/`](python/).

## Website

The project website is published with GitHub Pages from [`docs/`](docs/):

[mittel-labs.github.io/bibleit](https://mittel-labs.github.io/bibleit/)

## Project Layout

- [`python/`](python/) - Python package, Textual app, web operator, CLI, live server, tests.
- [`libbibleit/`](libbibleit/) - Native translation/index reader.
- [`docs/`](docs/) - Static project website for GitHub Pages.

## Contributing

Issues, ideas, and pull requests are welcome. bibleit is MIT licensed and intentionally small enough to understand, extend, and shape.
