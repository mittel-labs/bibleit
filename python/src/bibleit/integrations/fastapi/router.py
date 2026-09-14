from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.params import Depends as DependsParam

from bibleit.operator import (
    CapabilityError,
    CommandValidationError,
    OperatorError,
    OperatorService,
    PublishError,
)
from bibleit.integrations.fastapi.schemas import (
    BooksRead,
    CommandRequest,
    ErrorRead,
    FindRead,
    InstallRead,
    OperatorStateRead,
    ResolveRead,
    StrongRead,
    TranslationCatalogRead,
    VersesRead,
)

DEFAULT_PREFIX = "/api/v1/bibleit"


def _state(service: OperatorService) -> dict[str, Any]:
    return service.state().to_dict()


def _reference(value) -> dict[str, Any] | None:
    if value is None:
        return None
    return asdict(value) | {"reference": value.label}


def domain_error(error: OperatorError) -> HTTPException:
    if isinstance(error, CommandValidationError):
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    elif isinstance(error, CapabilityError):
        code = status.HTTP_403_FORBIDDEN
    elif isinstance(error, PublishError):
        code = status.HTTP_502_BAD_GATEWAY
    else:
        code = status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=str(error))


class WebSocketBridge:
    def __init__(self):
        self.sockets: set[WebSocket] = set()
        self.tasks: set[asyncio.Task] = set()
        self.closing = False

    async def serve(self, websocket: WebSocket, service: OperatorService) -> None:
        await websocket.accept()
        self.sockets.add(websocket)
        subscription = service.subscribe(max_events=16)
        current: set[asyncio.Task] = set()
        try:
            while not self.closing:
                event_task = asyncio.create_task(subscription.get())
                receive_task = asyncio.create_task(websocket.receive_json())
                current = {event_task, receive_task}
                self.tasks.update(current)
                done, pending = await asyncio.wait(current, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                self.tasks.difference_update(current)

                if event_task in done:
                    await websocket.send_json(event_task.result().to_dict())
                if receive_task in done:
                    payload = receive_task.result()
                    if not isinstance(payload, dict):
                        continue
                    try:
                        await service.command(str(payload.get("command", "")), payload.get("params"))
                    except OperatorError as error:
                        await websocket.send_json({"type": "error", "message": str(error)})
        except (WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
            pass
        finally:
            for task in current:
                task.cancel()
            self.tasks.difference_update(current)
            subscription.close()
            self.sockets.discard(websocket)

    async def close(self) -> None:
        self.closing = True
        for websocket in tuple(self.sockets):
            with suppress(RuntimeError):
                await websocket.close(code=1001, reason="bibleit is shutting down")
        for task in tuple(self.tasks):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)


def create_operator_router(  # noqa: C901 - route declarations intentionally share one configured closure
    *,
    service: OperatorService | None = None,
    service_dependency: Callable[..., OperatorService] | None = None,
    prefix: str = DEFAULT_PREFIX,
    dependencies: Sequence[DependsParam] = (),
    write_dependencies: Sequence[DependsParam] = (),
    websocket_dependencies: Sequence[DependsParam] = (),
    close_service: bool = False,
) -> APIRouter:
    """Create a versioned operator router without imposing host auth policy."""
    if (service is None) == (service_dependency is None):
        raise ValueError("Provide exactly one of service or service_dependency")

    if service_dependency is None:

        def service_dependency() -> OperatorService:
            assert service is not None
            return service

    bridge = WebSocketBridge()

    @asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        finally:
            await bridge.close()
            if close_service and service is not None:
                await service.close()

    router = APIRouter(prefix=prefix.rstrip("/"), dependencies=list(dependencies), lifespan=lifespan)
    operator = Depends(service_dependency)
    errors = {400: {"model": ErrorRead}, 403: {"model": ErrorRead}, 502: {"model": ErrorRead}}

    @router.get("/state", response_model=OperatorStateRead, responses=errors)
    async def state_read(current: OperatorService = operator):
        return _state(current)

    @router.get("/translations", response_model=TranslationCatalogRead, responses=errors)
    async def translations_read(current: OperatorService = operator):
        try:
            return asdict(await current.translations())
        except OperatorError as error:
            raise domain_error(error) from error

    @router.post(
        "/translations/{slug}",
        response_model=OperatorStateRead,
        dependencies=list(write_dependencies),
        responses=errors,
    )
    async def translation_open(slug: str, current: OperatorService = operator):
        try:
            await current.open_translation(slug)
            return _state(current)
        except OperatorError as error:
            raise domain_error(error) from error

    @router.delete(
        "/translations/{slug}",
        response_model=OperatorStateRead,
        dependencies=list(write_dependencies),
        responses=errors,
    )
    async def translation_close(slug: str, current: OperatorService = operator):
        try:
            await current.close_translation(slug)
            return _state(current)
        except OperatorError as error:
            raise domain_error(error) from error

    @router.post(
        "/translations/{slug}/install",
        response_model=InstallRead,
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=list(write_dependencies),
        responses=errors,
    )
    async def translation_install(slug: str, current: OperatorService = operator):
        try:
            current.install_translation(slug)
            return {"slug": slug, "state": "installing"}
        except OperatorError as error:
            raise domain_error(error) from error

    @router.delete(
        "/translations/{slug}/install",
        response_model=InstallRead,
        dependencies=list(write_dependencies),
        responses=errors,
    )
    async def translation_remove(slug: str, current: OperatorService = operator):
        try:
            await current.remove_translation(slug)
            return {"slug": slug, "state": "removed"}
        except OperatorError as error:
            raise domain_error(error) from error

    @router.post(
        "/commands",
        response_model=OperatorStateRead,
        dependencies=list(write_dependencies),
        responses=errors,
    )
    async def command_run(payload: CommandRequest, current: OperatorService = operator):
        try:
            await current.command(payload.command, payload.params)
            return _state(current)
        except OperatorError as error:
            raise domain_error(error) from error

    @router.get("/verses", response_model=VersesRead, responses=errors)
    async def verses_read(
        current: OperatorService = operator,
        before: int | None = Query(default=None, ge=0, le=100),
        total: int | None = Query(default=None, ge=1, le=400),
    ):
        try:
            window = current.verse_window(before=before, total=total)
            return asdict(window) | {"ref": _reference(window.ref)}
        except OperatorError as error:
            raise domain_error(error) from error

    @router.get("/books", response_model=BooksRead, responses=errors)
    async def books_read(current: OperatorService = operator, translation: str | None = None):
        try:
            selected = current.translation(translation)
            return {"translation": selected.slug, "books": [asdict(book) for book in current.books(translation)]}
        except OperatorError as error:
            raise domain_error(error) from error

    @router.get("/resolve", response_model=ResolveRead, responses=errors)
    async def resolve_read(q: str = "", current: OperatorService = operator):
        try:
            result = current.resolve(q)
            return asdict(result) | {"ref": _reference(result.ref)}
        except OperatorError as error:
            raise domain_error(error) from error

    @router.get("/find", response_model=FindRead, responses=errors)
    async def find_read(
        q: str = "",
        translation: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
        current: OperatorService = operator,
    ):
        try:
            selected = current.translation(translation)
            return {
                "translation": selected.slug,
                "results": [asdict(item) for item in await current.search(q, slug=translation, limit=limit)],
            }
        except OperatorError as error:
            raise domain_error(error) from error

    @router.get("/strongs/{code}", response_model=StrongRead, responses=errors)
    async def strongs_read(code: str, translation: str | None = None, current: OperatorService = operator):
        try:
            return asdict(await current.strongs(code, slug=translation))
        except OperatorError as error:
            raise domain_error(error) from error

    @router.websocket("/events", dependencies=list(websocket_dependencies))
    async def events(websocket: WebSocket, current: OperatorService = operator):
        await bridge.serve(websocket, current)

    router.bibleit_bridge = bridge
    return router
