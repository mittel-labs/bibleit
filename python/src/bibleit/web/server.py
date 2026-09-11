from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
import webbrowser

from aiohttp import web

from bibleit.config import config_value
from bibleit.live import HUB_KEY, LIVE_APP_TITLE, TITLE_KEY, add_live_routes
from bibleit.live_publisher import LivePublisher
from bibleit.operator import HubTarget, OperatorError, OperatorSession, RelayTarget
from bibleit.web import assets
from bibleit.web.api import API_PREFIX, LOCAL_KEY, SESSION_KEY, add_operator_routes

OPERATOR_PATH = "/operator"
OPERATOR_PAGE = "operator.html"
STATIC_PREFIX = f"{OPERATOR_PATH}/static"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000
VIEWER_POLL_SECONDS = 1.0
RELAY_RETRY_SECONDS = 3.0

TASKS_KEY = web.AppKey("operator_tasks", list)
HOST_KEY = web.AppKey("operator_host", str)


def publish_targets(hub) -> list:
    """Always drive the local hub; add the relay only when one is configured.

    `LivePublisher` falls back to the live host and port when `LIVE_URL` is
    unset, which is this process — publishing to ourselves over HTTP. Only an
    explicit `LIVE_URL` means a real remote relay.
    """
    targets = [HubTarget(hub)]

    if config_value("LIVE_URL").strip():
        targets.append(RelayTarget(LivePublisher()))

    return targets


def is_loopback(request: web.Request) -> bool:
    peer = request.transport.get_extra_info("peername") if request.transport else None
    host = peer[0] if peer else ""

    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@web.middleware
async def operator_guard(request: web.Request, handler):
    """Keep the operator on this machine while the audience viewer stays open.

    The viewer has to reach every device on the network, so the server binds
    every interface. The operator can change settings and read the publish
    token, so it answers loopback only.
    """
    guarded = request.path.startswith(OPERATOR_PATH) or request.path.startswith(API_PREFIX)

    if guarded and request.app.get(LOCAL_KEY) and not is_loopback(request):
        raise web.HTTPForbidden(
            reason="The bibleit operator is only available on the machine running it",
        )

    return await handler(request)


async def operator_index(request: web.Request) -> web.Response:
    return assets.page_response(OPERATOR_PAGE, request.app[TITLE_KEY])


async def operator_addresses(request: web.Request) -> web.Response:
    """Where to send the audience.

    The operator is served on loopback, so the browser cannot work out an
    address worth sharing on its own.
    """
    port = request.url.port or DEFAULT_PORT

    return web.json_response(addresses(request.app[HOST_KEY], port))


async def operator_static(request: web.Request) -> web.Response:
    return assets.static_response(request.match_info["name"])


async def watch_viewers(app: web.Application) -> None:
    session = app[SESSION_KEY]
    hub = app[HUB_KEY]

    while True:
        count = hub.client_count()

        if session.viewer_counts.get("local") != count:
            session.set_viewers("local", count)
            await session.notify_state()

        await asyncio.sleep(VIEWER_POLL_SECONDS)


async def watch_relay(app: web.Application, target: RelayTarget) -> None:
    session = app[SESSION_KEY]

    while True:
        async for status in target.publisher.status_events():
            session.set_viewers("relay", int(status.get("clients") or 0))
            session.connected = bool(status.get("connected"))
            await session.notify_state()

        session.set_viewers("relay", 0)
        session.connected = False
        await session.notify_state()
        await asyncio.sleep(RELAY_RETRY_SECONDS)


async def open_default_translation(session: OperatorSession) -> None:
    slug = config_value("DEFAULT_TRANSLATION").strip()

    if not slug:
        return

    try:
        await session.open_translation(slug)
    except OperatorError:
        return


async def start_session(app: web.Application) -> None:
    session = app[SESSION_KEY]
    await open_default_translation(session)

    tasks = [asyncio.create_task(watch_viewers(app))]

    for target in session.targets:
        if isinstance(target, RelayTarget):
            tasks.append(asyncio.create_task(watch_relay(app, target)))

    app[TASKS_KEY] = tasks


async def stop_session(app: web.Application) -> None:
    for task in app.get(TASKS_KEY) or []:
        task.cancel()

    await app[SESSION_KEY].close()


def create_operator_app(
    *,
    title: str | None = None,
    local: bool = True,
    host: str = DEFAULT_HOST,
) -> web.Application:
    title = title or os.getenv("BIBLEIT_LIVE_TITLE", LIVE_APP_TITLE)
    app = web.Application(middlewares=[operator_guard])
    app[HOST_KEY] = host
    add_live_routes(app, title=title)
    add_operator_routes(
        app,
        session=OperatorSession(targets=publish_targets(app[HUB_KEY])),
        local=local,
    )
    app.router.add_get(OPERATOR_PATH, operator_index)
    app.router.add_get(f"{STATIC_PREFIX}/{{name}}", operator_static)
    app.router.add_get(f"{API_PREFIX}/addresses", operator_addresses)
    app.on_startup.append(start_session)
    app.on_cleanup.append(stop_session)
    return app


def lan_address() -> str | None:
    """The address other devices on this network can reach, if any.

    Connecting a UDP socket sends nothing; it only asks the routing table which
    local address would be used to reach the internet.
    """
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
    lines = ["", "bibleit web", "", f"  Operator   {found['operator'][0]}"]

    for index, url in enumerate(found["audience"]):
        label = "  Audience  " if index == 0 else "            "
        share = "   (share this one)" if index and len(found["audience"]) > 1 else ""
        lines.append(f"{label} {url}{share}")

    lines += ["", "  Press Ctrl+C to stop.", ""]
    return "\n".join(lines)


def main(
    host: str | None = None,
    port: str | int | None = None,
    *,
    open_browser: bool = True,
) -> None:
    host = host or os.getenv("BIBLEIT_WEB_HOST", DEFAULT_HOST)
    port = int(port or os.getenv("BIBLEIT_WEB_PORT", DEFAULT_PORT))
    app = create_operator_app(host=host)

    if open_browser:

        async def launch(_: web.Application) -> None:
            webbrowser.open(f"http://127.0.0.1:{port}{OPERATOR_PATH}")

        app.on_startup.append(launch)

    print(banner(host, port))
    web.run_app(app, host=host, port=port, print=None)


if __name__ == "__main__":
    main()
