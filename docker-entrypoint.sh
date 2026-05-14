#!/bin/sh
set -e

case "$1" in
    serve)
        .venv/bin/python -m bibleit.serve
        ;;
    *)
        .venv/bin/python -m bibleit
        ;;
esac