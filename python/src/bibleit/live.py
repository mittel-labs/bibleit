from __future__ import annotations

import html
import hmac
import asyncio
import json
import os
import re
from dataclasses import asdict, dataclass
from importlib.resources import files

from aiohttp import web

from bibleit.config import config_value

LIVE_APP_TITLE = "bibleit live"
HTML_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class LiveVerse:
    translation: str
    book: str
    chapter: int
    verse: int
    text: str

    @property
    def reference(self) -> str:
        return f"{self.book} {self.chapter}:{self.verse}"

    def to_payload(self) -> dict:
        return asdict(self) | {"reference": self.reference}


def clean_verse_text(value: str) -> str:
    value = html.unescape(value)
    value = value.replace("<br>", " ").replace("<br/>", " ").replace("<br />", " ")
    value = re.sub(r"<S>.*?</S>", "", value, flags=re.IGNORECASE | re.DOTALL)
    value = HTML_TAG_RE.sub("", value)
    return re.sub(r"\s+", " ", value).strip()


def parse_verse_line(translation: str, value: str) -> LiveVerse | None:
    match = re.match(
        r"^(?P<book>.+)\s+(?P<chapter>\d+):(?P<verse>\d+)\s+(?P<text>.*)$",
        value.strip(),
        flags=re.DOTALL,
    )
    if not match:
        return None

    return LiveVerse(
        translation=translation,
        book=match.group("book"),
        chapter=int(match.group("chapter")),
        verse=int(match.group("verse")),
        text=clean_verse_text(match.group("text")),
    )


class LiveHub:
    def __init__(self):
        self.current: dict | None = None
        self.publisher_id: str | None = None
        self.sequence = 0
        self.live = False
        self.clients: set[web.WebSocketResponse] = set()
        self.monitors: set[web.WebSocketResponse] = set()

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
    template = files("bibleit").joinpath("live.html").read_text(encoding="utf-8")
    return template.replace("{{ title }}", html.escape(title))


async def index(request: web.Request) -> web.Response:
    return web.Response(
        text=viewer_html(request.app[TITLE_KEY]),
        content_type="text/html",
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
        pass
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

        if not is_monitor and not is_publisher:
            await hub.broadcast_client_count()

    return ws


def create_app(title: str = LIVE_APP_TITLE) -> web.Application:
    app = web.Application()
    app[HUB_KEY] = LiveHub()
    app[TITLE_KEY] = title
    app[TOKEN_KEY] = config_value("LIVE_TOKEN")
    app.router.add_get("/", index)
    app.router.add_get("/api/current", current)
    app.router.add_post("/api/publish", publish)
    app.router.add_post("/api/live", live_mode)
    app.router.add_get("/ws", websocket)
    return app


def main() -> None:
    host = os.getenv("BIBLEIT_LIVE_HOST", "0.0.0.0")
    port = int(os.getenv("BIBLEIT_LIVE_PORT", "8000"))
    title = os.getenv("BIBLEIT_LIVE_TITLE", LIVE_APP_TITLE)
    web.run_app(create_app(title), host=host, port=port)


if __name__ == "__main__":
    main()
