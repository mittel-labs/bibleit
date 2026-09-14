from __future__ import annotations

import html
from importlib.resources import files

from aiohttp import web

CACHE_CONTROL = "no-cache"
STATIC_TYPES = {"operator.css": "text/css", "operator.js": "application/javascript"}


def static_bytes(name: str) -> bytes:
    if name not in STATIC_TYPES:
        raise web.HTTPNotFound()
    return files("bibleit.webui").joinpath("static", name).read_bytes()


def static_response(name: str) -> web.Response:
    return web.Response(
        body=static_bytes(name),
        content_type=STATIC_TYPES[name],
        headers={"Cache-Control": CACHE_CONTROL},
    )


def page_response(title: str) -> web.Response:
    template = files("bibleit.webui").joinpath("static", "operator.html").read_text(encoding="utf-8")
    return web.Response(
        text=template.replace("{{ title }}", html.escape(title)),
        content_type="text/html",
        headers={"Cache-Control": CACHE_CONTROL},
    )
