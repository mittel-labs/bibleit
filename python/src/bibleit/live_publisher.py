from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlencode, urlsplit, urlunsplit
import uuid
from collections.abc import AsyncIterator
from typing import Sequence

import aiohttp

from bibleit.config import config_value
from bibleit.live import parse_verse_line

WEB_DRIVER = "textual.drivers.web_driver:WebDriver"


def running_in_browser() -> bool:
    return os.getenv("TEXTUAL_DRIVER") == WEB_DRIVER


def live_publish_url() -> str:
    host = os.getenv("BIBLEIT_LIVE_HOST") or "0.0.0.0"
    port = os.getenv("BIBLEIT_LIVE_PORT") or "8000"
    return (config_value("LIVE_URL") or f"http://{host}:{port}").rstrip("/")


class LivePublisher:
    def __init__(self):
        self.url = live_publish_url()
        self.timeout = float(os.getenv("BIBLEIT_LIVE_TIMEOUT", "0.5"))
        self.token = config_value("LIVE_TOKEN")
        self.publisher_id = uuid.uuid4().hex
        self.sequence = 0
        self._publish_session: aiohttp.ClientSession | None = None
        self._publish_ws: aiohttp.ClientWebSocketResponse | None = None
        self._publish_key: tuple[str, str | None] | None = None

    @property
    def enabled(self) -> bool:
        self.refresh_config()
        return bool(self.url)

    def refresh_config(self) -> None:
        self.url = live_publish_url()
        self.token = config_value("LIVE_TOKEN")

    def verse_payload(self, value: str, translation_slug: str) -> dict | None:
        if not self.enabled:
            return None

        verses = self._parse_verses([(translation_slug, value)])

        if not verses:
            return None

        self.sequence += 1
        primary = verses[0]
        return primary | {
            "translations": verses,
            "publisher_id": self.publisher_id,
            "sequence": self.sequence,
        }

    def bundle_payload(self, values: Sequence[tuple[str, str]]) -> dict | None:
        if not self.enabled:
            return None

        verses = self._parse_verses(values)

        if not verses:
            return None

        self.sequence += 1
        primary = verses[0]
        return primary | {
            "translations": verses,
            "publisher_id": self.publisher_id,
            "sequence": self.sequence,
        }

    def _parse_verses(self, values: Sequence[tuple[str, str]]) -> list[dict]:
        verses = []

        for translation_slug, value in values:
            verse = parse_verse_line(translation_slug, value)

            if verse is not None:
                verses.append(verse.to_payload())

        return verses

    async def publish_payload(self, payload: dict) -> bool:
        if not self.enabled:
            return False

        if await self._publish_over_websocket(payload):
            return True

        return await self._post("/api/publish", payload)

    async def set_live(self, live: bool) -> None:
        if not self.enabled:
            return

        await self._post("/api/live", {"live": live})

    async def close(self) -> None:
        await self._close_publisher_websocket()

    async def status_events(self) -> AsyncIterator[dict[str, bool | int]]:
        if not self.enabled:
            yield {"connected": False, "live": False, "clients": 0}
            return

        try:
            timeout = aiohttp.ClientTimeout(total=None, sock_connect=self.timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.ws_connect(self._websocket_url(role="monitor")) as ws:
                    async for message in ws:
                        if message.type != aiohttp.WSMsgType.TEXT:
                            continue

                        try:
                            payload = json.loads(message.data)
                        except (TypeError, ValueError):
                            continue

                        if payload.get("type") not in {"clients", "mode"}:
                            continue

                        yield {
                            "connected": True,
                            "live": bool(payload.get("live", True)),
                            "clients": int(payload.get("clients") or 0),
                        }
        except (aiohttp.ClientError, asyncio.TimeoutError, TypeError, ValueError):
            yield {"connected": False, "live": False, "clients": 0}

    def set_live_blocking(self, live: bool) -> bool:
        if not self.enabled:
            return False

        payload = json.dumps({"live": live}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.url}/api/live",
            data=payload,
            headers=self._headers(),
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return 200 <= response.status < 300
        except (OSError, TimeoutError, urllib.error.URLError):
            return False

    async def _post(self, path: str, payload: dict) -> bool:
        try:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    f"{self.url}{path}",
                    json=payload,
                    headers=self._headers(),
                ) as response:
                    return 200 <= response.status < 300
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False

    async def _publish_over_websocket(self, payload: dict) -> bool:
        try:
            ws = await self._publisher_websocket()
            await ws.send_json({"type": "publish", "payload": payload})
            return True
        except (aiohttp.ClientError, asyncio.TimeoutError, TypeError, ValueError):
            await self._close_publisher_websocket()
            return False

    async def _publisher_websocket(self) -> aiohttp.ClientWebSocketResponse:
        key = (self.url, self.token)

        if self._publish_key != key:
            await self._close_publisher_websocket()

        if self._publish_ws is not None and not self._publish_ws.closed:
            return self._publish_ws

        timeout = aiohttp.ClientTimeout(total=None, sock_connect=self.timeout)
        self._publish_session = aiohttp.ClientSession(timeout=timeout)
        self._publish_ws = await self._publish_session.ws_connect(
            self._websocket_url(role="publisher"),
            headers=self._headers(),
        )
        self._publish_key = key
        return self._publish_ws

    async def _close_publisher_websocket(self) -> None:
        if self._publish_ws is not None and not self._publish_ws.closed:
            await self._publish_ws.close()

        if self._publish_session is not None and not self._publish_session.closed:
            await self._publish_session.close()

        self._publish_ws = None
        self._publish_session = None
        self._publish_key = None

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}

        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        return headers

    def _websocket_url(self, **query: str) -> str:
        parsed = urlsplit(self.url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        path = parsed.path.rstrip("/") + "/ws"
        return urlunsplit(
            (
                scheme,
                parsed.netloc,
                path,
                urlencode(query),
                "",
            )
        )
