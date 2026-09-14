"""Optional FastAPI integration for the Bibleit operator application."""

from bibleit.integrations.fastapi.router import DEFAULT_PREFIX, WebSocketBridge, create_operator_router

__all__ = ["DEFAULT_PREFIX", "WebSocketBridge", "create_operator_router"]
