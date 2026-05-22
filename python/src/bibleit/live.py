from __future__ import annotations

import html
import hmac
import json
import os
import re
from dataclasses import asdict, dataclass

from aiohttp import web

from bibleit.serve import server

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

    async def broadcast(self, message: dict) -> None:
        encoded = json.dumps(message)

        stale = []
        for ws in self.clients:
            if ws.closed:
                stale.append(ws)
                continue
            await ws.send_str(encoded)

        for ws in stale:
            self.clients.discard(ws)

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
        await self.broadcast({"type": "mode", "live": self.live})


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
    escaped_title = html.escape(title)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_title}</title>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #f7f3ea;
      --fg: #201c18;
      --muted: #756c61;
      --accent: #bf6b21;
      --button-bg: rgba(255, 255, 255, 0.7);
      --button-border: rgba(32, 28, 24, 0.16);
    }}

    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg: #151311;
        --fg: #f5efe6;
        --muted: #b7ab9e;
        --accent: #f3a65d;
        --button-bg: rgba(255, 255, 255, 0.08);
        --button-border: rgba(245, 239, 230, 0.18);
      }}
    }}

    :root[data-theme="light"] {{
      color-scheme: light;
      --bg: #f7f3ea;
      --fg: #201c18;
      --muted: #756c61;
      --accent: #bf6b21;
      --button-bg: rgba(255, 255, 255, 0.7);
      --button-border: rgba(32, 28, 24, 0.16);
    }}

    :root[data-theme="dark"] {{
      color-scheme: dark;
      --bg: #151311;
      --fg: #f5efe6;
      --muted: #b7ab9e;
      --accent: #f3a65d;
      --button-bg: rgba(255, 255, 255, 0.08);
      --button-border: rgba(245, 239, 230, 0.18);
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--fg);
      font-family: ui-serif, Georgia, Cambria, "Times New Roman", serif;
    }}

    iframe {{
      width: 100vw;
      height: 100vh;
      border: 0;
      display: block;
      background: var(--bg);
    }}

    main {{
      min-height: 100vh;
      width: min(100%, 46rem);
      padding: clamp(1.5rem, 7vw, 4rem);
      display: grid;
      align-content: center;
      margin: 0 auto;
    }}

    [hidden] {{
      display: none !important;
    }}

    button {{
      position: fixed;
      top: max(1rem, env(safe-area-inset-top));
      right: max(1rem, env(safe-area-inset-right));
      min-width: 2.75rem;
      height: 2.75rem;
      border: 1px solid var(--button-border);
      border-radius: 999px;
      background: var(--button-bg);
      color: var(--fg);
      font: 700 1rem/1 ui-sans-serif, system-ui, sans-serif;
    }}

    .translation {{
      color: var(--accent);
      font: 700 0.78rem/1.2 ui-sans-serif, system-ui, sans-serif;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}

    .reference {{
      margin-top: 0.6rem;
      color: var(--muted);
      font: 700 clamp(1rem, 4vw, 1.35rem)/1.2 ui-sans-serif, system-ui, sans-serif;
    }}

    .verse {{
      margin-top: 1.2rem;
      font-size: clamp(2rem, 10vw, 4.5rem);
      line-height: 1.08;
      overflow-wrap: anywhere;
    }}

    .status {{
      margin-top: 2rem;
      color: var(--muted);
      font: 500 0.92rem/1.4 ui-sans-serif, system-ui, sans-serif;
    }}
  </style>
</head>
<body>
  <button id="theme" type="button" aria-label="Toggle color theme">◐</button>
  <iframe id="textual" src="/textual/" title="bibleit"></iframe>
  <main id="live" hidden>
    <div class="translation" id="translation">bibleit live</div>
    <div class="reference" id="reference">Waiting for presenter</div>
    <div class="verse" id="verse"></div>
    <div class="status" id="status">Connected viewers follow the active verse automatically.</div>
  </main>
  <script>
    const translation = document.getElementById("translation");
    const reference = document.getElementById("reference");
    const verse = document.getElementById("verse");
    const status = document.getElementById("status");
    const theme = document.getElementById("theme");
    const live = document.getElementById("live");
    const textual = document.getElementById("textual");

    function applyMode(isLive) {{
      live.hidden = !isLive;
      textual.hidden = isLive;
      if (!isLive) status.textContent = "Normal mode";
    }}

    function setTheme(value) {{
      document.documentElement.dataset.theme = value;
      localStorage.setItem("bibleit-theme", value);
      theme.textContent = value === "dark" ? "☀" : "☾";
    }}

    const savedTheme = localStorage.getItem("bibleit-theme");
    setTheme(savedTheme || "light");

    theme.addEventListener("click", () => {{
      setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
    }});

    function applyVerse(data) {{
      translation.textContent = data.translation || "bibleit";
      reference.textContent = data.reference || "";
      verse.textContent = data.text || "";
      status.textContent = "Live";
    }}

    function connect() {{
      const scheme = location.protocol === "https:" ? "wss" : "ws";
      const socket = new WebSocket(`${{scheme}}://${{location.host}}/ws`);

      socket.addEventListener("open", () => {{
        status.textContent = "Connected";
      }});

      socket.addEventListener("message", (event) => {{
        const message = JSON.parse(event.data);
        if (message.type === "mode") applyMode(message.live);
        if (message.type === "verse") applyVerse(message.verse);
      }});

      socket.addEventListener("close", () => {{
        status.textContent = "Reconnecting...";
        setTimeout(connect, 1000);
      }});
    }}

    connect();
  </script>
</body>
</html>
"""


async def index(request: web.Request) -> web.Response:
    return web.Response(
        text=viewer_html(request.app[TITLE_KEY]),
        content_type="text/html",
    )


async def current(request: web.Request) -> web.Response:
    hub = request.app[HUB_KEY]
    return web.json_response({"live": hub.live, "verse": hub.current})


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
    return web.json_response({"ok": True, "live": live})


async def websocket(request: web.Request) -> web.WebSocketResponse:
    hub: LiveHub = request.app[HUB_KEY]
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    hub.clients.add(ws)

    await ws.send_str(json.dumps({"type": "mode", "live": hub.live}))

    if hub.current:
        await ws.send_str(json.dumps({"type": "verse", "verse": hub.current}))

    try:
        async for _ in ws:
            pass
    finally:
        hub.clients.discard(ws)

    return ws


def create_app(title: str = LIVE_APP_TITLE) -> web.Application:
    app = web.Application()
    app[HUB_KEY] = LiveHub()
    app[TITLE_KEY] = title
    app[TOKEN_KEY] = os.getenv("BIBLEIT_LIVE_TOKEN", "")
    app.router.add_get("/", index)
    app.router.add_get("/api/current", current)
    app.router.add_post("/api/publish", publish)
    app.router.add_post("/api/live", live_mode)
    app.router.add_get("/ws", websocket)
    return app


async def create_live_app(title: str = LIVE_APP_TITLE) -> web.Application:
    app = create_app(title)
    server.title = "bibleit"
    server.public_url = os.getenv("BIBLEIT_SERVE_PUBLIC_URL", "http://127.0.0.1:8000")
    app.add_subapp("/textual", await server._make_app())
    return app


def main() -> None:
    host = os.getenv("BIBLEIT_LIVE_HOST", "0.0.0.0")
    port = int(os.getenv("BIBLEIT_LIVE_PORT", "8000"))
    title = os.getenv("BIBLEIT_LIVE_TITLE", LIVE_APP_TITLE)
    web.run_app(create_live_app(title), host=host, port=port)


if __name__ == "__main__":
    main()
