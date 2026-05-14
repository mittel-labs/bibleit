# bibleit python

Interactive Bible reading application for the terminal, built with Python and Textual.

## Features

- Interactive terminal UI
- Browser access using Textual Web
- Docker support
- Development workflow with Make

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

## Browser server configuration

The browser server supports the following environment variables:

| Variable | Default | Description |
|---|---|---|
| `BIBLEIT_SERVE_HOST` | `0.0.0.0` | Bind address |
| `BIBLEIT_SERVE_PORT` | `8000` | Server port |
| `BIBLEIT_SERVE_PUBLIC_URL` | `http://localhost:8000` | Public URL used by the browser/websocket client |

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
