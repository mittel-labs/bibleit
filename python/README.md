# bibleit

Interactive Bible reading for the terminal and the browser, plus a lightweight
live view for audiences, built with Python, Textual, aiohttp, and libbibleit.

## Features

- Terminal Bible reader with keyboard-first navigation.
- Web operator with the same reading, searching and live control, for people who would rather not use a terminal.
- Multiple translations open side by side or stacked vertically.
- Synchronized cursor across open translation panes.
- Go-to navigation with `g` or `@`, supporting verse, chapter/verse, and fuzzy book names.
- Text Find with `Ctrl+F`, result browsing, and visual translation toggles.
- Strong's references with linked entries via `Ctrl+G`.
- Live web viewer for sharing the active verse with viewers.
- Live viewer controls for light/dark theme, font size, presentation mode, and translation selection.
- Persistent local config for live URL/token and theme.
- Docker and Fly.io deployment support.

## Requirements

- Python 3.11+
- GNU Make

## Installation

Clone the repository:

```bash
git clone https://github.com/mittel-labs/bibleit.git
cd bibleit/python
```

Install development dependencies:

```bash
make install
```

Install the package locally:

```bash
make local-install-test
```

## Usage

Run the terminal application:

```bash
make run
```

Run the web operator and the audience view together:

```bash
make web
```

Run only the relay, with no reader attached:

```bash
make live
```

Then open:

```text
http://localhost:8000
```

Run the installed package directly:

```bash
python -m bibleit
```

Read a verse from the command line:

```bash
bibleit -t NVIPT dani 9.2
python -m bibleit -t KJV "john 3:16"
python -m bibleit -t NVIPT,KJV dani 9:2-15
bibleit -t KJV --strongs genesis 1.1
```

With no arguments, `bibleit` and `python -m bibleit` open the terminal app.
With a reference, they print matching verse text to stdout. Set a default
translation with `BIBLEIT_DEFAULT_TRANSLATION`, `BIBLEIT_TRANSLATION`, or
`DEFAULT_TRANSLATION` in `~/.bibleit/config`.

## Keyboard

| Shortcut | Action |
|---|---|
| `↑` / `↓` | Previous / next verse |
| `g` / `G` / `@` | Go to verse, chapter, or book reference |
| `Tab` / `Shift+Tab` | Next / previous open translation |
| `Tab` in Go To | Cycle go-to matches |
| `Ctrl+F` | Find verse text |
| `←` / `→` in Find | Switch Find translation |
| `Ctrl+T` | Open translations |
| `Ctrl+G` | Toggle Strong's |
| `Ctrl+H` | Open history |
| `Ctrl+A` / `Ctrl+E` | Beginning / end of current chapter |
| `<` / `>` | Previous / next chapter |
| `Ctrl+W` | Close the active translation pane |
| `Ctrl+M` | Maximize / restore the active translation pane |
| `Ctrl+Tab` | Rotate translations |
| `Ctrl+1`-`Ctrl+9` | Select a translation while maximized |
| `Esc` | Restore panes when a translation is maximized |
| `F2` | Toggle split layout |
| `Ctrl+L` | Toggle live mode |
| `Ctrl+D` | Toggle theme |
| `Ctrl+P` | Open config |
| `?` | Show shortcuts |

At startup bibleit shows a small welcome screen with the most useful
shortcuts. Press any shortcut to dismiss it and continue.

## Web operator

```bash
bibleit --web
```

This starts one server and opens the operator in your browser. It prints two
addresses: the operator, and the one to hand to the room.

```text
bibleit web

  Operator   http://127.0.0.1:8000/operator
  Audience   http://127.0.0.1:8000/
             http://192.168.1.24:8000/   (share this one)
```

Pick a translation from the library the first time; it downloads once and then
works offline, and becomes your default so the next launch opens straight into
it. Press **Go live** and the verse you select follows onto every screen in the
room. The share panel carries the address and a QR code for it.

The server listens on every interface, because the audience view has to reach
the phones and the projector. **The operator does not:** it can change settings
and read the publish token, so `/operator` and `/api/v1` answer only on the
machine running bibleit. Everything else answers to the whole network.

By default the verse goes to this machine's own hub, which is all you need when
the screens are on the same network. Set `LIVE_URL` and it goes to that relay as
well, so viewers anywhere can follow; the viewer count is reported for each
separately.

| Shortcut | Action |
|---|---|
| `↑` / `↓` | Previous / next verse |
| `,` / `.` | Previous / next chapter |
| `Home` / `End` | Start / end of chapter |
| `g` | Go to a reference |
| `l` | Go live, or stop |
| `t` | Library |
| `b` | Books |
| `f` | Find text |
| `s` | Share |
| `h` | Show Strong's numbers |
| `d` | Light or dark |
| `?` | Shortcuts |
| `Esc` | Close |

Single letters rather than the TUI's `Ctrl` combinations, because a browser
keeps `Ctrl+T` and `Ctrl+L` for itself.

Options:

```bash
bibleit --web 0.0.0.0 9000   # choose the address and port
bibleit --web --no-browser   # start the server without opening a browser
```

## Configuration

bibleit reads configuration from `~/.bibleit/config` as TOML. Environment
variables with the `BIBLEIT_` prefix take precedence.

| Config | Environment variable | Description |
|---|---|---|
| `LIVE_URL` | `BIBLEIT_LIVE_URL` | Live server URL used by the terminal app |
| `LIVE_TOKEN` | `BIBLEIT_LIVE_TOKEN` | Optional token used to protect live control requests |
| `DEFAULT_TRANSLATION` | `BIBLEIT_DEFAULT_TRANSLATION` | Default translation slug for CLI verse lookup |
| `THEME` | `BIBLEIT_THEME` | `light` or `dark` |

Open the config screen with `Ctrl+P`.

Example:

```toml
LIVE_URL = "https://bibleit.example.com"
THEME = "dark"
```

Empty values are not written to the config file.

## Live Mode

Start the live web server:

```bash
make live
```

Run the terminal app and point it at the live server:

```bash
BIBLEIT_LIVE_URL=http://localhost:8000 make run
```

Press `Ctrl+L` in the terminal app to publish the active verse to the web
viewer. When live mode is off, the browser shows a waiting splash screen.

## Development

Run with Textual development tools:

```bash
make run-dev
```

Open a Python shell inside the virtual environment:

```bash
make shell
```

Run tests:

```bash
make test
```

Run the browser tests, which drive the operator in a real headless Chromium:

```bash
make test-ui
```

`make test` skips them unless the browser is installed, so it stays fast and
needs no download.

Run lint:

```bash
make lint
```

Format code:

```bash
make lint-fix
```

Build distribution packages:

```bash
make build
```

bibleit package versions are derived from Git tags via `hatch-vcs`. To publish
a release, create a tag such as `v0.5.1` and build from that tag instead of
editing `pyproject.toml`.

Install local wheel:

```bash
make install-local
```

Run the local installation test:

```bash
make local-install-test
```

## Live server configuration

The live server supports the following environment variables:

| Variable | Default | Description |
|---|---|---|
| `BIBLEIT_LIVE_HOST` | `0.0.0.0` | Bind address |
| `BIBLEIT_LIVE_PORT` | `8000` | Server port |
| `BIBLEIT_LIVE_URL` | unset | Public live server URL used by the terminal app |
| `BIBLEIT_LIVE_TOKEN` | unset | Optional token used to protect live control requests |
| `BIBLEIT_LIVE_TITLE` | `bibleit live` | Browser page title |
| `BIBLEIT_WEB_HOST` | `0.0.0.0` | Bind address for `--web` |
| `BIBLEIT_WEB_PORT` | `8000` | Port for `--web` |
| `BIBLEIT_FIND_INDEX_CACHE_SIZE` | `4` | Max number of translation text indexes cached by Find |

Example:

```bash
export BIBLEIT_LIVE_HOST=0.0.0.0
export BIBLEIT_LIVE_PORT=8000
export BIBLEIT_LIVE_URL=http://localhost:8000

make live
```

## Docker

Build the image:

```bash
docker build -t bibleit .
```

Run terminal mode:

```bash
docker run -it bibleit
```

Run live web mode:

```bash
docker run -p 8000:8000 bibleit live
```

Then open:

```text
http://localhost:8000
```
