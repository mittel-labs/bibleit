"""aiohttp transport adapter for the Bibleit operator application."""

from bibleit.integrations.aiohttp.routes import API_PREFIX, SERVICE_KEY, add_operator_routes

__all__ = ["API_PREFIX", "SERVICE_KEY", "add_operator_routes"]
