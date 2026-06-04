# bibleit

Interactive Bible reading for the terminal and browser, built with Python,
Textual, and libbibleit.

## Features

- Terminal Bible reader with keyboard-first navigation.
- Browser access through Textual Web, with mobile-friendly touch controls.
- Multiple translations open side by side or stacked vertically.
- Synchronized cursor across open translation panes.
- Go-to navigation with `g`, supporting verse, chapter/verse, and fuzzy book names.
- Text Find with `Ctrl+F`, result browsing, and visual translation toggles.
- Strong's references with linked entries via `Ctrl+G`.
- Live web presentation mode for sharing the active verse with viewers.
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

Run the browser version:

```bash
make serve
```

Then open:

```text
http://localhost:8000
```

Run the installed package directly:

```bash
python -m bibleit
```

## Keyboard

| Shortcut | Action |
|---|---|
| `↑` / `↓` | Previous / next verse |
| `g` | Go to verse, chapter, or book reference |
| `Tab` | Cycle go-to matches |
| `Ctrl+F` | Find verse text |
| `←` / `→` in Find | Switch Find translation |
| `Ctrl+T` | Open translations |
| `Ctrl+G` | Toggle Strong's |
| `Ctrl+A` / `Ctrl+E` | Beginning / end of current chapter |
| `<` / `>` | Previous / next chapter |
| `Ctrl+W` | Close the active translation pane |
| `F2` | Toggle split layout |
| `Ctrl+L` | Toggle live mode |
| `Ctrl+D` | Toggle theme |
| `Ctrl+P` | Open config |
| `?` | Show shortcuts |

At startup bibleit shows a small welcome screen with the most useful
shortcuts. Press `Enter`, `Esc`, `q`, or `?` to dismiss it.

## Configuration

bibleit reads configuration from `~/.bibleit/config` as TOML. Environment
variables with the `BIBLEIT_` prefix take precedence.

| Config | Environment variable | Description |
|---|---|---|
| `LIVE_URL` | `BIBLEIT_LIVE_URL` | Live server URL used by the terminal app |
| `LIVE_TOKEN` | `BIBLEIT_LIVE_TOKEN` | Optional token used to protect live control requests |
| `THEME` | `BIBLEIT_THEME` | `light` or `dark` |

Open the config screen with `Ctrl+P`.

Example:

```toml
LIVE_URL = "https://bibleit.example.com"
THEME = "dark"
```

Empty values are not written to the config file.

## Live Mode

Start the web server:

```bash
make serve
```

Run the terminal app and point it at the live server:

```bash
BIBLEIT_LIVE_URL=http://localhost:8000 make run
```

Press `Ctrl+L` in the terminal app to publish the active verse to the web
viewer. When live mode is off, the browser loads the interactive Textual app.

## Development

Run with Textual development tools:

```bash
make run-dev
```

Run browser version with hot reload:

```bash
make serve-dev
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

Install local wheel:

```bash
make install-local
```

Run the local installation test:

```bash
make local-install-test
```

## Browser server configuration

The browser server supports the following environment variables:

| Variable | Default | Description |
|---|---|---|
| `BIBLEIT_SERVE_HOST` | `0.0.0.0` | Bind address |
| `BIBLEIT_SERVE_PORT` | `8000` | Server port |
| `BIBLEIT_SERVE_PUBLIC_URL` | `http://localhost:8000` | Public URL used by the browser/websocket client |
| `BIBLEIT_FIND_INDEX_CACHE_SIZE` | `4` | Max number of translation text indexes cached by Find |

Example:

```bash
export BIBLEIT_SERVE_HOST=0.0.0.0
export BIBLEIT_SERVE_PORT=8000
export BIBLEIT_SERVE_PUBLIC_URL=http://localhost:8000

make serve
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

Run browser mode:

```bash
docker run -p 8000:8000 bibleit serve
```

Then open:

```text
http://localhost:8000
```
