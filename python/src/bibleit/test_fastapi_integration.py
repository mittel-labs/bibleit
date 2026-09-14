from __future__ import annotations

import unittest

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from bibleit.integrations.fastapi import create_operator_router
from bibleit.operator import OperatorCapabilities, OperatorService, OperatorSession
from bibleit.test_operator_core import FakeCatalog


def require_staff(x_staff: str | None = Header(default=None)) -> None:
    if x_staff != "yes":
        raise HTTPException(status_code=401, detail="staff only")


def require_csrf(x_csrf: str | None = Header(default=None)) -> None:
    if x_csrf != "valid":
        raise HTTPException(status_code=403, detail="invalid csrf")


class FastApiIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.catalog = FakeCatalog()
        self.service = OperatorService(
            session=OperatorSession(),
            catalog=self.catalog,
            capabilities=OperatorCapabilities(install_translations=True, remove_translations=True),
        )
        self.router = create_operator_router(
            service=self.service,
            dependencies=[Depends(require_staff)],
            write_dependencies=[Depends(require_csrf)],
            websocket_dependencies=[Depends(require_staff)],
            close_service=True,
        )
        self.app = FastAPI()
        self.app.include_router(self.router)

    def request_headers(self, *, write=False):
        headers = {"x-staff": "yes"}
        if write:
            headers["x-csrf"] = "valid"
        return headers

    def test_host_auth_and_write_hooks_are_enforced(self):
        with TestClient(self.app) as client:
            self.assertEqual(client.get("/api/v1/bibleit/state").status_code, 401)
            self.assertEqual(
                client.post("/api/v1/bibleit/translations/KJV", headers=self.request_headers()).status_code,
                403,
            )
            response = client.post(
                "/api/v1/bibleit/translations/KJV",
                headers=self.request_headers(write=True),
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["active"], "KJV")

    def test_command_validation_and_domain_errors_have_stable_statuses(self):
        with TestClient(self.app) as client:
            invalid = client.post(
                "/api/v1/bibleit/commands",
                headers=self.request_headers(write=True),
                json={"command": "set_live", "params": {"live": "yes"}},
            )
            unknown = client.post(
                "/api/v1/bibleit/commands",
                headers=self.request_headers(write=True),
                json={"command": "launch_rocket", "params": {}},
            )
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(unknown.status_code, 422)

    def test_reading_routes_share_the_documented_shapes(self):
        with TestClient(self.app) as client:
            client.post(
                "/api/v1/bibleit/translations/KJV",
                headers=self.request_headers(write=True),
            )
            state = client.get("/api/v1/bibleit/state", headers=self.request_headers()).json()
            verses = client.get("/api/v1/bibleit/verses", headers=self.request_headers()).json()
            books = client.get("/api/v1/bibleit/books", headers=self.request_headers()).json()
            resolved = client.get(
                "/api/v1/bibleit/resolve",
                params={"q": "Genesis 1:2"},
                headers=self.request_headers(),
            ).json()
            found = client.get(
                "/api/v1/bibleit/find",
                params={"q": "earth"},
                headers=self.request_headers(),
            ).json()
            strong = client.get(
                "/api/v1/bibleit/strongs/H7225",
                headers=self.request_headers(),
            ).json()

        self.assertEqual(state["ref"]["reference"], "Genesis 1:1")
        self.assertEqual(verses["columns"][0]["translation"], "KJV")
        self.assertEqual(books["translation"], "KJV")
        self.assertTrue(resolved["exists"])
        self.assertEqual(found["results"][0]["reference"], "Genesis 1:2")
        self.assertEqual(strong["code"], "H7225")

    def test_install_progress_reaches_websocket(self):
        with TestClient(self.app) as client:
            with client.websocket_connect("/api/v1/bibleit/events", headers=self.request_headers()) as socket:
                self.assertEqual(socket.receive_json()["type"], "state")
                response = client.post(
                    "/api/v1/bibleit/translations/KJV/install",
                    headers=self.request_headers(write=True),
                )
                states = [socket.receive_json()["state"], socket.receive_json()["state"]]
        self.assertEqual(response.status_code, 202)
        self.assertEqual(states, ["installing", "installed"])

    def test_multiple_listeners_receive_commands_and_disconnect_cleanly(self):
        bridge = self.router.bibleit_bridge
        with TestClient(self.app) as client:
            client.post(
                "/api/v1/bibleit/translations/KJV",
                headers=self.request_headers(write=True),
            )
            with client.websocket_connect("/api/v1/bibleit/events", headers=self.request_headers()) as first:
                with client.websocket_connect("/api/v1/bibleit/events", headers=self.request_headers()) as second:
                    first.receive_json()
                    second.receive_json()
                    first.send_json({"command": "next_verse", "params": {}})
                    self.assertEqual(first.receive_json()["state"]["ref"]["verse"], 2)
                    self.assertEqual(second.receive_json()["state"]["ref"]["verse"], 2)
            self.assertEqual(bridge.sockets, set())

        self.assertTrue(self.catalog.available["KJV"].closed)
        self.assertEqual(bridge.sockets, set())
        self.assertEqual(bridge.tasks, set())

    def test_router_mounts_at_a_host_prefix_without_static_routes(self):
        app = FastAPI()
        app.include_router(create_operator_router(service=self.service, prefix="/internal/bible"))
        schema = app.openapi()

        self.assertIn("/internal/bible/state", schema["paths"])
        self.assertFalse(any("static" in path or "operator.html" in path for path in schema["paths"]))

    def test_exactly_one_service_provider_is_required(self):
        with self.assertRaises(ValueError):
            create_operator_router()
        with self.assertRaises(ValueError):
            create_operator_router(service=self.service, service_dependency=lambda: self.service)


if __name__ == "__main__":
    unittest.main()
