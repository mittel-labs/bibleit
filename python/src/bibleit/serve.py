import os
import sys
from textual_serve.server import Server

host = os.getenv("BIBLEIT_SERVE_HOST") or "0.0.0.0"
port = os.getenv("BIBLEIT_SERVE_PORT") or "8000"
public_url = os.getenv("BIBLEIT_SERVE_PUBLIC_URL") or "http://localhost:8000"

server = Server(
    f"{sys.executable} -m bibleit",
    host=host,
    port=int(port),
    public_url=public_url,
)

server.serve()
