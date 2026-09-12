from __future__ import annotations

import html
from importlib.resources import files

from aiohttp import web

STATIC_TYPES = {
    "operator.css": "text/css",
    "operator.js": "application/javascript",
    "viewer.css": "text/css",
    "viewer.js": "application/javascript",
}

# The page and its assets ship together and change together. Revalidating keeps
# a browser from running last version's script against this version's API.
CACHE_CONTROL = "no-cache"


def static_bytes(name: str) -> bytes:
    return (files("bibleit.web") / "static" / name).read_bytes()


def static_text(name: str) -> str:
    return static_bytes(name).decode("utf-8")


def static_response(name: str) -> web.Response:
    content_type = STATIC_TYPES.get(name)

    if content_type is None:
        raise web.HTTPNotFound()

    return web.Response(
        body=static_bytes(name),
        content_type=content_type,
        headers={"Cache-Control": CACHE_CONTROL},
    )


def render_page(name: str, title: str) -> str:
    return static_text(name).replace("{{ title }}", html.escape(title))


def page_response(name: str, title: str) -> web.Response:
    return web.Response(
        text=render_page(name, title),
        content_type="text/html",
        headers={"Cache-Control": CACHE_CONTROL},
    )
