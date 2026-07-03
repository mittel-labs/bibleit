# bibleit

Interactive Bible reading for the terminal, plus a lightweight live web viewer,
built with Python, Textual, and libbibleit.

## Features

- Terminal Bible reader with keyboard-first navigation.
- Multiple translations open side by side or stacked vertically.
- Synchronized cursor across open translation panes.
- Go-to navigation with `g` or `@`, supporting verse, chapter/verse, and fuzzy book names.
- Text Find with `Ctrl+F`, result browsing, and visual translation toggles.
- Strong's references with linked entries via `Ctrl+G`.
- Live web viewer for sharing the active verse with viewers.
- Live viewer controls for light/dark theme, font size, presentation mode, and translation selection.
- Listening mode with Vosk speech recognition for spoken Bible references.
- Listen History and live transcripts saved under `~/.bibleit/recordings`.
- Persistent local config for live URL/token, theme, default translation, and listening model.
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

Run the live web viewer:

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
| `Ctrl+Shift+L` | Toggle listening mode |
| `Ctrl+Shift+H` | Open listen history |
| `Ctrl+Shift+R` | Open listening transcripts |
| `Ctrl+D` | Toggle theme |
| `Ctrl+P` | Open config |
| `?` | Show shortcuts |

At startup bibleit shows a small welcome screen with the most useful
shortcuts. Press any shortcut to dismiss it and continue.

## Configuration

bibleit reads configuration from `~/.bibleit/config` as TOML. Environment
variables with the `BIBLEIT_` prefix take precedence.
Downloaded translations are cached in `~/.bibleit/translations`.

| Config | Environment variable | Description |
|---|---|---|
| `LIVE_URL` | `BIBLEIT_LIVE_URL` | Live server URL used by the terminal app |
| `LIVE_TOKEN` | `BIBLEIT_LIVE_TOKEN` | Optional token used to protect live control requests |
| `DEFAULT_TRANSLATION` | `BIBLEIT_DEFAULT_TRANSLATION` | Default translation slug for CLI verse lookup |
| `LISTENING_MODEL` | `BIBLEIT_LISTENING_MODEL` | Vosk model directory used by listening mode |
| `THEME` | `BIBLEIT_THEME` | `light` or `dark` |

Open the config screen with `Ctrl+P`.

Example:

```toml
LIVE_URL = "https://bibleit.example.com"
THEME = "dark"
```

Empty values are not written to the config file.

## Listening Mode

bibleit can listen for spoken Bible references and keep a searchable listen
history. The feature uses [Vosk](https://alphacephei.com/vosk/) locally, so it
does not send microphone audio to a remote service.

Download a model from the [Vosk model list](https://alphacephei.com/vosk/models)
and extract it under:

```text
~/.bibleit/models
```

For example:

```text
~/.bibleit/models/vosk-model-small-pt-0.3
~/.bibleit/models/vosk-model-small-en-us-0.15
~/.bibleit/models/vosk-model-small-de-0.15
```

Open config with `Ctrl+P`, choose `LISTENING_MODEL`, then press
`Ctrl+Shift+L` to toggle listening mode. Switching between Portuguese, English,
and German is just a matter of selecting a matching Vosk model; bibleit accepts
common chapter/verse phrases in those languages, while recognition quality still
depends on the model and microphone.

Recognized references are stored in Listen History (`Ctrl+Shift+H`). Transcripts
are written as text files in `~/.bibleit/recordings` and can be opened with
`Ctrl+Shift+R`. Vosk diagnostics are appended to:

```text
~/.bibleit/recordings/vosk.debug.log
```

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
