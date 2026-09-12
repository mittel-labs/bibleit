from __future__ import annotations

import hmac
import asyncio
import json
import os
from importlib.resources import files

from aiohttp import WSCloseCode, web

from bibleit.config import config_value
from bibleit.live_payload import LiveVerse, parse_verse_line
from bibleit import qr
from bibleit.verse import clean_verse_text
from bibleit.web import assets

LIVE_APP_TITLE = "bibleit live"
VIEWER_PAGE = "viewer.html"

__all__ = [
    "LiveVerse",
    "add_live_routes",
    "LiveHub",
    "clean_verse_text",
    "create_app",
    "main",
    "parse_verse_line",
    "viewer_html",
]


class LiveHub:
    def __init__(self):
        self.current: dict | None = None
        self.publisher_id: str | None = None
        self.sequence = 0
        self.live = False
        self.clients: set[web.WebSocketResponse] = set()
        self.monitors: set[web.WebSocketResponse] = set()
        self.publishers: set[web.WebSocketResponse] = set()

    def sockets(self) -> set[web.WebSocketResponse]:
        return self.clients | self.monitors | self.publishers

    def client_count(self) -> int:
        stale = {ws for ws in self.clients if ws.closed}
        self.clients.difference_update(stale)
        return len(self.clients)

    async def broadcast(self, message: dict) -> None:
        encoded = json.dumps(message)

        stale = []
        targets = list(self.clients | self.monitors)
        send_tasks = []

        for ws in targets:
            if ws.closed:
                stale.append(ws)
                continue

            send_tasks.append((ws, asyncio.create_task(ws.send_str(encoded))))

        for ws, task in send_tasks:
            try:
                await task
            except (ConnectionError, RuntimeError):
                stale.append(ws)

        for ws in stale:
            self.clients.discard(ws)
            self.monitors.discard(ws)

    async def publish(self, payload: dict) -> None:
        publisher_id = payload.get("publisher_id")
        sequence = payload.get("sequence")

        if publisher_id is not None and sequence is not None:
            try:
                sequence = int(sequence)
            except (TypeError, ValueError):
                sequence = 0

            if publisher_id == self.publisher_id and sequence < self.sequence:
                return

            self.publisher_id = publisher_id
            self.sequence = sequence

        self.current = payload
        await self.broadcast({"type": "verse", "verse": payload})

    async def set_live(self, live: bool) -> None:
        self.live = live
        await self.broadcast(
            {
                "type": "mode",
                "live": self.live,
                "clients": self.client_count(),
            }
        )

    async def broadcast_client_count(self) -> None:
        await self.broadcast(
            {
                "type": "clients",
                "clients": self.client_count(),
            }
        )


HUB_KEY = web.AppKey("hub", LiveHub)
TITLE_KEY = web.AppKey("title", str)
TOKEN_KEY = web.AppKey("token", str)


def request_is_authorized(request: web.Request) -> bool:
    token = request.app[TOKEN_KEY]

    if not token:
        return True

    header = request.headers.get("Authorization", "")

    if not header.startswith("Bearer "):
        return False

    return hmac.compare_digest(header.removeprefix("Bearer ").strip(), token)


def require_authorized(request: web.Request) -> None:
    if not request_is_authorized(request):
        raise web.HTTPUnauthorized(text="Unauthorized")


def viewer_html(title: str) -> str:
    return assets.render_page(VIEWER_PAGE, title)


async def index(request: web.Request) -> web.Response:
    return assets.page_response(VIEWER_PAGE, request.app[TITLE_KEY])


async def viewer_asset(request: web.Request) -> web.Response:
    return assets.static_response(f"viewer.{request.match_info['kind']}")


def viewer_url(request: web.Request) -> str:
    """The address this page was reached at, which is the one worth sharing.

    Behind a proxy that terminates TLS the request itself looks like plain
    HTTP, so the forwarded scheme wins when it is present. A spoofed header
    only changes the scheme inside a QR image.
    """
    forwarded = request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip()
    scheme = forwarded or request.url.scheme

    return str(request.url.with_scheme(scheme).with_path("/").with_query(None))


async def qr_code(request: web.Request) -> web.Response:
    return web.Response(
        body=qr.svg(viewer_url(request)),
        content_type="image/svg+xml",
        headers={"Cache-Control": assets.CACHE_CONTROL},
    )


async def icon(_: web.Request) -> web.Response:
    return web.Response(
        body=files("bibleit").joinpath("bibleit-icon.png").read_bytes(),
        content_type="image/png",
    )


async def current(request: web.Request) -> web.Response:
    hub = request.app[HUB_KEY]
    return web.json_response(
        {
            "live": hub.live,
            "verse": hub.current,
            "clients": hub.client_count(),
        }
    )


async def publish(request: web.Request) -> web.Response:
    require_authorized(request)
    payload = await request.json()
    await request.app[HUB_KEY].publish(payload)
    return web.json_response({"ok": True})


async def live_mode(request: web.Request) -> web.Response:
    require_authorized(request)
    payload = await request.json()
    live = bool(payload.get("live"))
    await request.app[HUB_KEY].set_live(live)
    return web.json_response(
        {
            "ok": True,
            "live": live,
            "clients": request.app[HUB_KEY].client_count(),
        }
    )


async def handle_publisher_message(hub: LiveHub, message: web.WSMessage) -> None:
    if message.type != web.WSMsgType.TEXT:
        return

    try:
        payload = json.loads(message.data)
    except (TypeError, ValueError):
        return

    if payload.get("type") == "publish" and isinstance(payload.get("payload"), dict):
        await hub.publish(payload["payload"])
    elif payload.get("type") == "live":
        await hub.set_live(bool(payload.get("live")))


async def websocket(request: web.Request) -> web.WebSocketResponse:
    hub: LiveHub = request.app[HUB_KEY]
    is_monitor = request.query.get("role") == "monitor"
    is_publisher = request.query.get("role") == "publisher"

    if is_publisher:
        require_authorized(request)

    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    if is_monitor:
        hub.monitors.add(ws)
    elif is_publisher:
        hub.publishers.add(ws)
    else:
        hub.clients.add(ws)
        await hub.broadcast_client_count()

    await ws.send_str(
        json.dumps(
            {
                "type": "mode",
                "live": hub.live,
                "clients": hub.client_count(),
            }
        )
    )

    if hub.current:
        await ws.send_str(json.dumps({"type": "verse", "verse": hub.current}))

    try:
        async for message in ws:
            if is_publisher:
                await handle_publisher_message(hub, message)
    finally:
        hub.clients.discard(ws)
        hub.monitors.discard(ws)
        hub.publishers.discard(ws)

        if not is_monitor and not is_publisher:
            await hub.broadcast_client_count()

    return ws


async def close_hub_sockets(app: web.Application) -> None:
    """Close viewer and publisher sockets so shutdown is not blocked.

    aiohttp waits for request handlers to return before it finishes shutting
    down, and a WebSocket handler only returns when its socket closes. Without
    this, Ctrl+C hangs for as long as anyone is connected.
    """
    for ws in list(app[HUB_KEY].sockets()):
        await ws.close(code=WSCloseCode.GOING_AWAY, message=b"bibleit is shutting down")


def add_live_routes(app: web.Application, *, title: str = LIVE_APP_TITLE) -> web.Application:
    """Mount the viewer, the hub and the publish endpoints onto an application.

    Kept separate from `create_app` so one process can serve the audience
    viewer and the operator from the same port.
    """
    app[HUB_KEY] = LiveHub()
    app[TITLE_KEY] = title
    app[TOKEN_KEY] = config_value("LIVE_TOKEN")
    app.router.add_get("/", index)
    app.router.add_get("/viewer.{kind:css|js}", viewer_asset)
    app.router.add_get("/qr.svg", qr_code)
    app.router.add_get("/bibleit-icon.png", icon)
    app.router.add_get("/api/current", current)
    app.router.add_post("/api/publish", publish)
    app.router.add_post("/api/live", live_mode)
    app.router.add_get("/ws", websocket)
    app.on_shutdown.append(close_hub_sockets)
    return app


def create_app(title: str = LIVE_APP_TITLE) -> web.Application:
    return add_live_routes(web.Application(), title=title)


def main(host: str | None = None, port: str | int | None = None) -> None:
    host = host or os.getenv("BIBLEIT_LIVE_HOST", "0.0.0.0")
    port = int(port or os.getenv("BIBLEIT_LIVE_PORT", "8000"))
    title = os.getenv("BIBLEIT_LIVE_TITLE", LIVE_APP_TITLE)
    web.run_app(create_app(title), host=host, port=port)


if __name__ == "__main__":
    main()
