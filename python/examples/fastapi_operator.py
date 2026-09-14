"""Minimal host-owned FastAPI application for the Bibleit operator API."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException

from bibleit.operator import NativeTranslationCatalog, OperatorService, OperatorSession
from bibleit.integrations.fastapi import create_operator_router

service = OperatorService(session=OperatorSession(), catalog=NativeTranslationCatalog())


def require_staff(authorization: str | None = Header(default=None)) -> None:
    if authorization != "Bearer example-staff-token":
        raise HTTPException(status_code=401, detail="Staff access required")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await service.close()


app = FastAPI(lifespan=lifespan)
app.include_router(
    create_operator_router(
        service=service,
        dependencies=[Depends(require_staff)],
    )
)
