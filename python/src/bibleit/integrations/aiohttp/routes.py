from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

from aiohttp import WSCloseCode, WSMsgType, web

from bibleit.operator import CapabilityError, CommandValidationError, OperatorError, OperatorService, PublishError

API_PREFIX = "/api/v1/bibleit"
SERVICE_KEY = web.AppKey("bibleit_operator_service", OperatorService)
SOCKETS_KEY = web.AppKey("bibleit_operator_sockets", set)
PUMPS_KEY = web.AppKey("bibleit_operator_pumps", set)


def _state(service: OperatorService) -> dict[str, Any]:
    return service.state().to_dict()


def _reference(value) -> dict[str, Any] | None:
    if value is None:
        return None
    return asdict(value) | {"reference": value.label}


def _error_status(error: OperatorError) -> int:
    if isinstance(error, CommandValidationError):
        return 422
    if isinstance(error, CapabilityError):
        return 403
    if isinstance(error, PublishError):
        return 502
    return 400


def _error(error: OperatorError) -> web.Response:
    return web.json_response({"detail": str(error)}, status=_error_status(error))


def _service(request: web.Request) -> OperatorService:
    return request.app[SERVICE_KEY]


async def _json(request: web.Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except (TypeError, ValueError):
        raise CommandValidationError("Expected a JSON object") from None
    if not isinstance(payload, dict):
        raise CommandValidationError("Expected a JSON object")
    return payload


def _integer(request: web.Request, name: str, *, minimum: int, maximum: int) -> int | None:
    raw = request.query.get(name)
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError:
        raise CommandValidationError(f"{name} must be an integer") from None
    if not minimum <= value <= maximum:
        raise CommandValidationError(f"{name} must be between {minimum} and {maximum}")
    return value


async def state_read(request: web.Request) -> web.Response:
    return web.json_response(_state(_service(request)))


async def translations_read(request: web.Request) -> web.Response:
    try:
        return web.json_response(asdict(await _service(request).translations()))
    except OperatorError as error:
        return _error(error)


async def translation_open(request: web.Request) -> web.Response:
    try:
        await _service(request).open_translation(request.match_info["slug"])
        return web.json_response(_state(_service(request)))
    except OperatorError as error:
        return _error(error)


async def translation_close(request: web.Request) -> web.Response:
    try:
        await _service(request).close_translation(request.match_info["slug"])
        return web.json_response(_state(_service(request)))
    except OperatorError as error:
        return _error(error)


async def translation_install(request: web.Request) -> web.Response:
    slug = request.match_info["slug"]
    try:
        _service(request).install_translation(slug)
        return web.json_response({"slug": slug, "state": "installing"}, status=202)
    except OperatorError as error:
        return _error(error)


async def translation_remove(request: web.Request) -> web.Response:
    slug = request.match_info["slug"]
    try:
        await _service(request).remove_translation(slug)
        return web.json_response({"slug": slug, "state": "removed"})
    except OperatorError as error:
        return _error(error)


async def command_run(request: web.Request) -> web.Response:
    try:
        payload = await _json(request)
        await _service(request).command(str(payload.get("command", "")), payload.get("params"))
        return web.json_response(_state(_service(request)))
    except OperatorError as error:
        return _error(error)


async def verses_read(request: web.Request) -> web.Response:
    try:
        service = _service(request)
        window = service.verse_window(
            before=_integer(request, "before", minimum=0, maximum=100),
            total=_integer(request, "total", minimum=1, maximum=400),
        )
        return web.json_response(asdict(window) | {"ref": _reference(window.ref)})
    except OperatorError as error:
        return _error(error)


async def books_read(request: web.Request) -> web.Response:
    try:
        service = _service(request)
        slug = request.query.get("translation")
        selected = service.translation(slug)
        return web.json_response(
            {"translation": selected.slug, "books": [asdict(book) for book in service.books(slug)]}
        )
    except OperatorError as error:
        return _error(error)


async def resolve_read(request: web.Request) -> web.Response:
    try:
        result = _service(request).resolve(request.query.get("q", ""))
        return web.json_response(asdict(result) | {"ref": _reference(result.ref)})
    except OperatorError as error:
        return _error(error)


async def find_read(request: web.Request) -> web.Response:
    try:
        service = _service(request)
        slug = request.query.get("translation")
        selected = service.translation(slug)
        results = await service.search(
            request.query.get("q", ""),
            slug=slug,
            limit=_integer(request, "limit", minimum=1, maximum=500) or 100,
        )
        return web.json_response({"translation": selected.slug, "results": [asdict(item) for item in results]})
    except OperatorError as error:
        return _error(error)


async def strongs_read(request: web.Request) -> web.Response:
    try:
        entry = await _service(request).strongs(
            request.match_info["code"],
            slug=request.query.get("translation"),
        )
        return web.json_response(asdict(entry))
    except OperatorError as error:
        return _error(error)


async def _pump(ws: web.WebSocketResponse, subscription) -> None:
    async for event in subscription:
        if ws.closed:
            return
        await ws.send_json(event.to_dict())


async def events(request: web.Request) -> web.WebSocketResponse:
    service = _service(request)
    ws = web.WebSocketResponse(heartbeat=25)
    await ws.prepare(request)
    subscription = service.subscribe(max_events=16)
    request.app[SOCKETS_KEY].add(ws)
    pump = asyncio.create_task(_pump(ws, subscription))
    request.app[PUMPS_KEY].add(pump)
    try:
        async for message in ws:
            if message.type is not WSMsgType.TEXT:
                continue
            try:
                payload = message.json()
                if not isinstance(payload, dict):
                    raise CommandValidationError("Expected a JSON object")
                await service.command(str(payload.get("command", "")), payload.get("params"))
            except (TypeError, ValueError, OperatorError) as error:
                await ws.send_json({"type": "error", "message": str(error)})
    finally:
        subscription.close()
        pump.cancel()
        request.app[PUMPS_KEY].discard(pump)
        request.app[SOCKETS_KEY].discard(ws)
    return ws


async def _close_sockets(app: web.Application) -> None:
    for ws in tuple(app[SOCKETS_KEY]):
        await ws.close(code=WSCloseCode.GOING_AWAY, message=b"bibleit is shutting down")
    for task in tuple(app[PUMPS_KEY]):
        task.cancel()
    if app[PUMPS_KEY]:
        await asyncio.gather(*app[PUMPS_KEY], return_exceptions=True)


def add_operator_routes(
    app: web.Application,
    *,
    service: OperatorService,
    prefix: str = API_PREFIX,
    close_service: bool = False,
) -> web.Application:
    prefix = prefix.rstrip("/")
    app[SERVICE_KEY] = service
    app[SOCKETS_KEY] = set()
    app[PUMPS_KEY] = set()
    app.router.add_get(f"{prefix}/state", state_read)
    app.router.add_get(f"{prefix}/translations", translations_read)
    app.router.add_post(f"{prefix}/translations/{{slug}}", translation_open)
    app.router.add_delete(f"{prefix}/translations/{{slug}}", translation_close)
    app.router.add_post(f"{prefix}/translations/{{slug}}/install", translation_install)
    app.router.add_delete(f"{prefix}/translations/{{slug}}/install", translation_remove)
    app.router.add_post(f"{prefix}/commands", command_run)
    app.router.add_get(f"{prefix}/verses", verses_read)
    app.router.add_get(f"{prefix}/books", books_read)
    app.router.add_get(f"{prefix}/resolve", resolve_read)
    app.router.add_get(f"{prefix}/find", find_read)
    app.router.add_get(f"{prefix}/strongs/{{code}}", strongs_read)
    app.router.add_get(f"{prefix}/events", events)
    app.on_shutdown.append(_close_sockets)
    if close_service:

        async def close(_app):
            await service.close()

        app.on_cleanup.append(close)
    return app
