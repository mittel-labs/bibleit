import os
import sys
from textual_serve.server import Server

command = os.getenv("BIBLEIT_SERVE_COMMAND") or f"{sys.executable} -m bibleit"
host = os.getenv("BIBLEIT_SERVE_HOST") or "0.0.0.0"
port = os.getenv("BIBLEIT_SERVE_PORT") or "8000"
title = os.getenv("BIBLEIT_SERVE_TITLE") or "bibleit"
public_url = os.getenv("BIBLEIT_SERVE_PUBLIC_URL") or "http://localhost:8000"

server = Server(
    command,
    title=title,
    host=host,
    port=int(port),
    public_url=public_url,
)

if __name__ == "__main__":
    server.serve()
