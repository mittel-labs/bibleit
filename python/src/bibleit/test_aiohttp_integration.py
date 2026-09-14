from __future__ import annotations

import unittest

from aiohttp import WSMsgType, web
from aiohttp.test_utils import AioHTTPTestCase
from fastapi import FastAPI
from fastapi.testclient import TestClient as FastApiClient

from bibleit.integrations.aiohttp import API_PREFIX, add_operator_routes
from bibleit.integrations.fastapi import create_operator_router
from bibleit.operator import OperatorCapabilities, OperatorService, OperatorSession
from bibleit.test_operator_core import FakeCatalog


def make_service():
    return OperatorService(
        session=OperatorSession(),
        catalog=FakeCatalog(),
        capabilities=OperatorCapabilities(install_translations=True, remove_translations=True),
    )


class AioHttpIntegrationTests(AioHTTPTestCase):
    async def get_application(self):
        self.service = make_service()
        return add_operator_routes(web.Application(), service=self.service, close_service=True)

    async def test_reading_and_command_contract(self):
        opened = await self.client.post(f"{API_PREFIX}/translations/KJV")
        state = await opened.json()
        command = await self.client.post(
            f"{API_PREFIX}/commands",
            json={"command": "next_verse", "params": {}},
        )
        books = await (await self.client.get(f"{API_PREFIX}/books")).json()
        verses = await (await self.client.get(f"{API_PREFIX}/verses")).json()

        self.assertEqual(opened.status, 200)
        self.assertEqual(state["active"], "KJV")
        self.assertEqual((await command.json())["ref"]["verse"], 2)
        self.assertEqual(books["translation"], "KJV")
        self.assertEqual(verses["columns"][0]["translation"], "KJV")

    async def test_validation_and_capability_errors_match_fastapi_statuses(self):
        invalid = await self.client.post(
            f"{API_PREFIX}/commands",
            json={"command": "set_live", "params": {"live": "yes"}},
        )
        self.service.capabilities = OperatorCapabilities()
        forbidden = await self.client.post(f"{API_PREFIX}/translations/KJV/install")

        self.assertEqual(invalid.status, 422)
        self.assertIn("boolean", (await invalid.json())["detail"])
        self.assertEqual(forbidden.status, 403)

    async def test_install_events_and_commands_use_the_socket(self):
        async with self.client.ws_connect(f"{API_PREFIX}/events") as socket:
            self.assertEqual((await socket.receive_json())["type"], "state")
            response = await self.client.post(f"{API_PREFIX}/translations/KJV/install")
            states = [(await socket.receive_json())["state"], (await socket.receive_json())["state"]]
            await socket.send_json({"command": "open_translation", "params": {"slug": "KJV"}})
            state = await socket.receive_json()

        self.assertEqual(response.status, 202)
        self.assertEqual(states, ["installing", "installed"])
        self.assertEqual(state["state"]["active"], "KJV")

    async def test_shutdown_closes_open_socket_and_service(self):
        await self.service.open_translation("KJV")
        socket = await self.client.ws_connect(f"{API_PREFIX}/events")
        await socket.receive_json()
        await self.app.shutdown()

        message = await socket.receive()
        self.assertIn(message.type, {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.CLOSING})
        await socket.close()

    async def test_fastapi_and_aiohttp_return_equivalent_common_contracts(self):
        aio_open = await self.client.post(f"{API_PREFIX}/translations/KJV")
        aio_state = await aio_open.json()
        aio_resolve = await (await self.client.get(f"{API_PREFIX}/resolve", params={"q": "Genesis 1:2"})).json()
        aio_error = await self.client.post(
            f"{API_PREFIX}/commands",
            json={"command": "set_live", "params": {"live": "yes"}},
        )

        fast_service = make_service()
        fast_app = FastAPI()
        fast_app.include_router(create_operator_router(service=fast_service, close_service=True))
        with FastApiClient(fast_app) as client:
            fast_state = client.post(f"{API_PREFIX}/translations/KJV").json()
            fast_resolve = client.get(f"{API_PREFIX}/resolve", params={"q": "Genesis 1:2"}).json()
            fast_error = client.post(
                f"{API_PREFIX}/commands",
                json={"command": "set_live", "params": {"live": "yes"}},
            )

        self.assertEqual(aio_state, fast_state)
        self.assertEqual(aio_resolve, fast_resolve)
        self.assertEqual(aio_error.status, fast_error.status_code)
        self.assertEqual((await aio_error.json())["detail"], fast_error.json()["detail"])


if __name__ == "__main__":
    unittest.main()
