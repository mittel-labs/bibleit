#!/bin/sh
set -e

case "$1" in
    serve)
        .venv/bin/textual serve --host ${BIBLEIT_SERVE_HOST:-localhost} --port ${BIBLEIT_SERVE_PORT:-8000} "python -m bibleit"
        ;;
    *)
        .venv/bin/python -m bibleit
        ;;
esac