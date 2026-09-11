from __future__ import annotations

import asyncio
import functools
import json
from dataclasses import asdict

from aiohttp import WSCloseCode, WSMsgType, web

from bibleit import reader, translation
from bibleit.config import CONFIG_NAMES, env_overrides, load_config, save_config
from bibleit.navigation import (
    navigation_completion_candidates,
    navigation_suggestion_value,
    parse_navigation_ref,
)
from bibleit.operator import OperatorError, OperatorSession
from bibleit.text_find import find_translation_text

API_PREFIX = "/api/v1"
DEFAULT_FIND_LIMIT = 100
MAX_FIND_LIMIT = 500

SESSION_KEY = web.AppKey("operator_session", OperatorSession)
LOCAL_KEY = web.AppKey("operator_local", bool)
INSTALLS_KEY = web.AppKey("operator_installs", set)
SOCKETS_KEY = web.AppKey("operator_sockets", set)


async def blocking(function, *args, **kwargs):
    """Run library code that touches the network, the disk or the native index."""
    loop = asyncio.get_running_loop()

    if kwargs:
        function = functools.partial(function, **kwargs)

    return await loop.run_in_executor(None, function, *args)


def error_response(message: str, status: int = 400) -> web.Response:
    return web.json_response({"error": message}, status=status)


def int_param(request: web.Request, name: str) -> int | None:
    raw = request.query.get(name)

    if raw is None:
        return None

    try:
        return int(raw)
    except ValueError:
        return None


def session_of(request: web.Request) -> OperatorSession:
    return request.app[SESSION_KEY]


def require_local(request: web.Request) -> None:
    if not request.app[LOCAL_KEY]:
        raise web.HTTPForbidden(reason="Settings are only available to a local operator")


def opened_translation(request: web.Request, slug: str | None = None):
    session = session_of(request)
    slug = slug or request.query.get("translation") or ""

    if not slug:
        active = session.active()

        if active is None:
            return None, error_response("Open a translation first")

        return active, None

    opened = session.find(slug)

    if opened is None:
        return None, error_response(f"Translation not open: {slug}")

    return opened, None


# -- translations ----------------------------------------------------------


def translations_payload() -> dict:
    installed = {slug for slug, header in translation.get_installed().items() if header is not None}
    languages = []

    for language in translation.get_languages_available():
        entries = [
            {"slug": header.slug, "name": header.name, "installed": header.slug in installed}
            for header in language.translations
            if header is not None
        ]

        if entries:
            languages.append({"name": language.name, "translations": entries})

    return {"installed": sorted(installed), "languages": languages}


async def translations_index(request: web.Request) -> web.Response:
    try:
        payload = await blocking(translations_payload)
    except (LookupError, OSError) as error:
        return error_response(f"Could not reach the translation catalogue: {error}", status=502)

    return web.json_response(payload)


async def translation_install(request: web.Request) -> web.Response:
    slug = request.match_info["slug"]
    installs = request.app[INSTALLS_KEY]

    if translation.is_installed(slug):
        return web.json_response({"slug": slug, "state": "installed"})

    if slug not in installs:
        installs.add(slug)
        asyncio.create_task(run_install(request.app, slug))

    return web.json_response({"slug": slug, "state": "installing"}, status=202)


async def remember_default_translation(app: web.Application, slug: str) -> bool:
    """Make the first translation someone installs the one that opens next time.

    Only when nothing is configured yet, so it cannot quietly overwrite a
    choice, and never for a remotely served operator, which has no business
    writing this machine's configuration.
    """
    if not app[LOCAL_KEY]:
        return False

    if "DEFAULT_TRANSLATION" in env_overrides():
        return False

    if (await blocking(load_config)).get("DEFAULT_TRANSLATION"):
        return False

    await blocking(save_config, {"DEFAULT_TRANSLATION": slug})
    return True


async def run_install(app: web.Application, slug: str) -> None:
    session = app[SESSION_KEY]

    try:
        await blocking(translation.install, slug)
        await blocking(translation.get_index, slug)
    except Exception as error:
        await session.notify({"type": "install", "slug": slug, "state": "failed", "error": str(error)})
    else:
        await session.notify(
            {
                "type": "install",
                "slug": slug,
                "state": "installed",
                "default": await remember_default_translation(app, slug),
            }
        )
    finally:
        app[INSTALLS_KEY].discard(slug)


async def translation_uninstall(request: web.Request) -> web.Response:
    slug = request.match_info["slug"]
    session = session_of(request)

    await session.close_translation(slug)
    await blocking(translation.uninstall, slug)
    await session.notify({"type": "install", "slug": slug, "state": "removed"})

    return web.json_response({"slug": slug, "state": "removed"})


# -- reading ---------------------------------------------------------------


async def state(request: web.Request) -> web.Response:
    return web.json_response(session_of(request).snapshot())


async def verses(request: web.Request) -> web.Response:
    session = session_of(request)

    return web.json_response(
        session.verses(
            before=int_param(request, "before"),
            total=int_param(request, "total"),
        )
    )


async def books(request: web.Request) -> web.Response:
    opened, failure = opened_translation(request)

    if failure is not None:
        return failure

    return web.json_response(
        {
            "translation": opened.slug,
            "books": [asdict(book) for book in reader.books(opened)],
        }
    )


async def resolve(request: web.Request) -> web.Response:
    session = session_of(request)
    active = session.active()

    if active is None:
        return error_response("Open a translation first")

    value = request.query.get("q", "")
    payload = {
        "candidates": navigation_completion_candidates(value, active),
        "suggestion": navigation_suggestion_value(value, active),
    }

    try:
        ref = parse_navigation_ref(value, active, session.state)
    except ValueError as error:
        return web.json_response(payload | {"ref": None, "exists": False, "error": str(error)})

    return web.json_response(
        payload
        | {
            "ref": {
                "bookid": ref.bookid,
                "chapter": ref.chapter or 1,
                "verse": ref.verse_start or 1,
            },
            "exists": reader.verse_line(active, ref) is not None,
        }
    )


async def find(request: web.Request) -> web.Response:
    query = request.query.get("q", "").strip()

    if not query:
        return web.json_response({"results": []})

    opened, failure = opened_translation(request)

    if failure is not None:
        return failure

    limit = min(int_param(request, "limit") or DEFAULT_FIND_LIMIT, MAX_FIND_LIMIT)
    results = await blocking(find_translation_text, opened, query, limit=limit)

    return web.json_response(
        {
            "translation": opened.slug,
            "results": [
                {
                    "reference": result.label,
                    "text": result.text,
                    "bookid": result.ref.bookid,
                    "chapter": result.ref.chapter,
                    "verse": result.ref.verse_start,
                }
                for result in results
            ],
        }
    )


async def strongs(request: web.Request) -> web.Response:
    code = request.match_info["code"].upper().strip()
    opened, failure = opened_translation(request)

    if failure is not None:
        return failure

    try:
        entries = await blocking(lambda: opened.strongs)
    except (LookupError, OSError, ValueError) as error:
        return error_response(f"Could not load the Strong's dictionary: {error}", status=502)

    entry = entries.get(code)

    if entry is None:
        return error_response(f"No Strong's entry for {code}", status=404)

    return web.json_response(asdict(entry))


# -- settings --------------------------------------------------------------


async def config_read(request: web.Request) -> web.Response:
    require_local(request)
    values = load_config()

    return web.json_response(
        {
            "values": {name: values.get(name, "") for name in CONFIG_NAMES},
            "environment": sorted(env_overrides()),
        }
    )


async def config_write(request: web.Request) -> web.Response:
    require_local(request)

    try:
        payload = await request.json()
    except (ValueError, json.JSONDecodeError):
        return error_response("Expected a JSON body")

    if not isinstance(payload, dict):
        return error_response("Expected a JSON object")

    values = {name: str(payload[name]) for name in CONFIG_NAMES if name in payload}

    if not values:
        return error_response(f"No known settings in the request. Known settings: {', '.join(CONFIG_NAMES)}")

    await blocking(save_config, values)

    return await config_read(request)


# -- commands --------------------------------------------------------------


async def command(request: web.Request) -> web.Response:
    session = session_of(request)

    try:
        payload = await request.json()
    except (ValueError, json.JSONDecodeError):
        return error_response("Expected a JSON body")

    if not isinstance(payload, dict):
        return error_response("Expected a JSON object")

    try:
        await session.command(str(payload.get("command", "")), payload.get("params") or {})
    except OperatorError as error:
        return error_response(str(error))

    return web.json_response(session.snapshot())


async def pump_events(ws: web.WebSocketResponse, queue: asyncio.Queue) -> None:
    while not ws.closed:
        event = await queue.get()

        if ws.closed:
            return

        await ws.send_json(event)


async def operator_websocket(request: web.Request) -> web.WebSocketResponse:
    session = session_of(request)
    ws = web.WebSocketResponse(heartbeat=25)
    await ws.prepare(request)

    queue = session.listen()
    request.app[SOCKETS_KEY].add(ws)
    await ws.send_json({"type": "state", "state": session.snapshot()})
    pump = asyncio.create_task(pump_events(ws, queue))

    try:
        async for message in ws:
            if message.type != WSMsgType.TEXT:
                continue

            try:
                payload = json.loads(message.data)
            except (TypeError, ValueError):
                continue

            if not isinstance(payload, dict):
                continue

            try:
                await session.command(str(payload.get("command", "")), payload.get("params") or {})
            except OperatorError as error:
                await ws.send_json({"type": "error", "message": str(error)})
    finally:
        session.forget(queue)
        request.app[SOCKETS_KEY].discard(ws)
        pump.cancel()

    return ws


# -- wiring ----------------------------------------------------------------


async def close_operator_sockets(app: web.Application) -> None:
    """See `live.close_hub_sockets`: an open socket holds up shutdown."""
    for ws in list(app[SOCKETS_KEY]):
        await ws.close(code=WSCloseCode.GOING_AWAY, message=b"bibleit is shutting down")


def add_operator_routes(
    app: web.Application,
    *,
    session: OperatorSession,
    local: bool = True,
) -> web.Application:
    app[SESSION_KEY] = session
    app[LOCAL_KEY] = local
    app[INSTALLS_KEY] = set()
    app[SOCKETS_KEY] = set()
    app.on_shutdown.append(close_operator_sockets)

    app.router.add_get(f"{API_PREFIX}/state", state)
    app.router.add_get(f"{API_PREFIX}/verses", verses)
    app.router.add_get(f"{API_PREFIX}/books", books)
    app.router.add_get(f"{API_PREFIX}/resolve", resolve)
    app.router.add_get(f"{API_PREFIX}/find", find)
    app.router.add_get(f"{API_PREFIX}/strongs/{{code}}", strongs)
    app.router.add_get(f"{API_PREFIX}/translations", translations_index)
    app.router.add_post(f"{API_PREFIX}/translations/{{slug}}", translation_install)
    app.router.add_delete(f"{API_PREFIX}/translations/{{slug}}", translation_uninstall)
    app.router.add_get(f"{API_PREFIX}/config", config_read)
    app.router.add_put(f"{API_PREFIX}/config", config_write)
    app.router.add_post(f"{API_PREFIX}/command", command)
    app.router.add_get(f"{API_PREFIX}/operator", operator_websocket)

    return app
