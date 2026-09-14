from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
import webbrowser

from aiohttp import web

from bibleit import qr
from bibleit.config import config_value, load_config, save_config
from bibleit.integrations.aiohttp import API_PREFIX, SERVICE_KEY, add_operator_routes
from bibleit.live import HUB_KEY, LIVE_APP_TITLE, TITLE_KEY, add_live_routes
from bibleit.live_publisher import LivePublisher
from bibleit.operator import (
    HubTarget,
    NativeTranslationCatalog,
    OperatorCapabilities,
    OperatorError,
    OperatorService,
    OperatorSession,
    RelayTarget,
)
from bibleit.webui import assets

OPERATOR_PATH = "/operator"
STATIC_PREFIX = f"{OPERATOR_PATH}/static"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000
VIEWER_POLL_SECONDS = 1.0
RELAY_RETRY_SECONDS = 3.0

HOST_KEY = web.AppKey("bibleit_standalone_host", str)
LOCAL_KEY = web.AppKey("bibleit_standalone_local", bool)
TASKS_KEY = web.AppKey("bibleit_standalone_tasks", list)
RELAY_KEY = web.AppKey("bibleit_standalone_relay", object)


class LocalConfigStore:
    async def read(self) -> dict[str, str]:
        return await asyncio.to_thread(load_config)

    async def write(self, values: dict[str, str]) -> None:
        await asyncio.to_thread(save_config, values)


def publish_targets(hub) -> tuple[list, RelayTarget | None]:
    targets = [HubTarget(hub)]
    relay = None
    if config_value("LIVE_URL").strip():
        relay = RelayTarget(LivePublisher())
        targets.append(relay)
    return targets, relay


def is_loopback(request: web.Request) -> bool:
    peer = request.transport.get_extra_info("peername") if request.transport else None
    host = peer[0] if peer else ""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@web.middleware
async def operator_guard(request: web.Request, handler):
    guarded = request.path.startswith(OPERATOR_PATH) or request.path.startswith(API_PREFIX)
    if guarded and request.app[LOCAL_KEY] and not is_loopback(request):
        raise web.HTTPForbidden(reason="The Bibleit operator is only available on the machine running it")
    return await handler(request)


async def operator_index(request: web.Request) -> web.Response:
    return assets.page_response(request.app[TITLE_KEY])


async def operator_static(request: web.Request) -> web.Response:
    return assets.static_response(request.match_info["name"])


async def operator_addresses(request: web.Request) -> web.Response:
    return web.json_response(addresses(request.app[HOST_KEY], request.url.port or DEFAULT_PORT))


async def operator_qr(request: web.Request) -> web.Response:
    found = addresses(request.app[HOST_KEY], request.url.port or DEFAULT_PORT)
    return web.Response(
        body=qr.svg(found["audience"][-1]),
        content_type="image/svg+xml",
        headers={"Cache-Control": assets.CACHE_CONTROL},
    )


async def watch_viewers(app: web.Application) -> None:
    service = app[SERVICE_KEY]
    hub = app[HUB_KEY]
    previous = None
    while True:
        count = hub.client_count()
        if count != previous:
            await service.set_viewers("local", count, connected=True)
            previous = count
        await asyncio.sleep(VIEWER_POLL_SECONDS)


async def watch_relay(app: web.Application, relay: RelayTarget) -> None:
    service = app[SERVICE_KEY]
    while True:
        async for status in relay.publisher.status_events():
            await service.set_viewers(
                "relay",
                int(status.get("clients") or 0),
                connected=bool(status.get("connected")),
            )
        await service.set_viewers("relay", 0, connected=False)
        await asyncio.sleep(RELAY_RETRY_SECONDS)


async def start_standalone(app: web.Application) -> None:
    service = app[SERVICE_KEY]
    slug = config_value("DEFAULT_TRANSLATION").strip()
    if slug:
        try:
            await service.open_translation(slug)
        except OperatorError:
            pass
    tasks = [asyncio.create_task(watch_viewers(app))]
    relay = app[RELAY_KEY]
    if isinstance(relay, RelayTarget):
        tasks.append(asyncio.create_task(watch_relay(app, relay)))
    app[TASKS_KEY] = tasks


async def stop_standalone(app: web.Application) -> None:
    for task in app[TASKS_KEY]:
        task.cancel()
    if app[TASKS_KEY]:
        await asyncio.gather(*app[TASKS_KEY], return_exceptions=True)
    await app[SERVICE_KEY].close()


def create_operator_app(
    *,
    title: str | None = None,
    local: bool = True,
    host: str = DEFAULT_HOST,
    service: OperatorService | None = None,
) -> web.Application:
    title = title or os.getenv("BIBLEIT_LIVE_TITLE", LIVE_APP_TITLE)
    app = web.Application(middlewares=[operator_guard])
    app[HOST_KEY] = host
    app[LOCAL_KEY] = local
    add_live_routes(app, title=title)
    relay = None
    if service is None:
        targets, relay = publish_targets(app[HUB_KEY])
        service = OperatorService(
            session=OperatorSession(targets=targets),
            catalog=NativeTranslationCatalog(),
            config_store=LocalConfigStore(),
            capabilities=OperatorCapabilities(
                install_translations=True,
                remove_translations=True,
                write_config=True,
            ),
        )
    else:
        service.add_publish_target(HubTarget(app[HUB_KEY]))
    app[RELAY_KEY] = relay
    add_operator_routes(app, service=service)
    app.router.add_get(OPERATOR_PATH, operator_index)
    app.router.add_get(f"{STATIC_PREFIX}/{{name}}", operator_static)
    app.router.add_get(f"{API_PREFIX}/addresses", operator_addresses)
    app.router.add_get(f"{API_PREFIX}/qr.svg", operator_qr)
    app.on_startup.append(start_standalone)
    app.on_cleanup.append(stop_standalone)
    return app


def lan_address() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.settimeout(0.2)
            probe.connect(("8.8.8.8", 80))
            return probe.getsockname()[0]
    except OSError:
        return None


def addresses(host: str, port: int) -> dict[str, list[str]]:
    local = f"http://127.0.0.1:{port}"
    audience = [f"{local}/"]
    if host not in {"127.0.0.1", "localhost", "::1"}:
        address = lan_address()
        if address:
            audience.append(f"http://{address}:{port}/")
    return {"operator": [f"{local}{OPERATOR_PATH}"], "audience": audience}


def banner(host: str, port: int) -> str:
    found = addresses(host, port)
    lines = ["", "bibleit web", "", f"  Operator  {found['operator'][0]}"]
    for index, url in enumerate(found["audience"]):
        label = "  Audience  " if index == 0 else "            "
        share = "  (share this one)" if index and len(found["audience"]) > 1 else ""
        lines.append(f"{label}{url}{share}")
    return "\n".join([*lines, "", "  Press Ctrl+C to stop.", ""])


def main(host: str | None = None, port: str | int | None = None, *, open_browser: bool = True) -> None:
    host = host or os.getenv("BIBLEIT_WEB_HOST", DEFAULT_HOST)
    port = int(port or os.getenv("BIBLEIT_WEB_PORT", DEFAULT_PORT))
    app = create_operator_app(host=host)
    if open_browser:

        async def launch(_app: web.Application) -> None:
            webbrowser.open(f"http://127.0.0.1:{port}{OPERATOR_PATH}")

        app.on_startup.append(launch)
    print(banner(host, port))
    web.run_app(app, host=host, port=port, print=None)


if __name__ == "__main__":
    main()
