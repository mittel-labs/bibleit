from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
import uuid
from typing import Sequence

import aiohttp

from bibleit.config import config_value
from bibleit.live import parse_verse_line

WEB_DRIVER = "textual.drivers.web_driver:WebDriver"


def running_in_browser() -> bool:
    return os.getenv("TEXTUAL_DRIVER") == WEB_DRIVER


def live_publish_url() -> str:
    host = os.getenv("BIBLEIT_SERVE_HOST") or "0.0.0.0"
    port = os.getenv("BIBLEIT_SERVE_PORT") or "8000"
    return (config_value("LIVE_URL") or os.getenv("BIBLEIT_SERVE_PUBLIC_URL") or f"http://{host}:{port}").rstrip("/")


class LivePublisher:
    def __init__(self):
        self.url = live_publish_url()
        self.timeout = float(os.getenv("BIBLEIT_LIVE_TIMEOUT", "0.5"))
        self.token = config_value("LIVE_TOKEN")
        self.publisher_id = uuid.uuid4().hex
        self.sequence = 0

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

        return await self._post("/api/publish", payload)

    async def set_live(self, live: bool) -> None:
        if not self.enabled:
            return

        await self._post("/api/live", {"live": live})

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

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}

        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        return headers
