"""No-network tests for the opt-in administrator-only Security2 LAB WebSocket.

Load the handler against lightweight HA API stubs so tests do not need a
running Home Assistant, firmware, six-digit PIN or ESP-IDF installation.
"""
from __future__ import annotations

import asyncio
import importlib.util
import ipaddress
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components/omote_manager"
PACKAGE = "omote_lab_gate_test"


def load_handler():
    modules = {}
    ha = types.ModuleType("homeassistant")
    ha.__path__ = []
    components = types.ModuleType("homeassistant.components")
    components.__path__ = []
    ws = types.ModuleType("homeassistant.components.websocket_api")
    ha.components = components
    components.websocket_api = ws
    ws.ERR_UNAUTHORIZED = "unauthorized"
    ws.ERR_NOT_FOUND = "not_found"
    ws.ERR_NOT_ALLOWED = "not_allowed"
    ws.ERR_INVALID_FORMAT = "invalid_format"
    ws.ERR_UNKNOWN_ERROR = "unknown"
    ws.websocket_command = lambda _schema: (lambda f: f)
    ws.async_response = lambda f: f
    ws.async_register_command = lambda _h, _f: None
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    vol = types.ModuleType("voluptuous")
    vol.Required = lambda s: s
    pkg = types.ModuleType(PACKAGE)
    pkg.__path__ = [str(COMPONENT)]
    for name, module in (
        ("homeassistant", ha), ("homeassistant.components", components),
        ("homeassistant.components.websocket_api", ws),
        ("homeassistant.core", core), ("voluptuous", vol), (PACKAGE, pkg),
    ):
        modules[name] = module
    for name, attrs in (
        (".candidate_identity_ws", {"IDENTITY_STORE_KEY": "candidate_store"}),
        (".const", {"DOMAIN": "omote_manager"}),
        (".sec2_lab_espidf", {
            "LabPrerequisiteError": type("LabPrerequisiteError", (RuntimeError,), {}),
            "load_official_security2": lambda: object,
        }),
        (".sec2_lab_http", {"LabHttpTransport": object}),
        (".sec2_lab_session", {
            "LabSessionError": type("LabSessionError", (RuntimeError,), {}),
            "run_tx2_lab_session": None,
        }),
    ):
        sub = types.ModuleType(PACKAGE + name)
        sub.__dict__.update(attrs)
        modules[sub.__name__] = sub
    originals = {key: sys.modules.get(key) for key in modules}
    try:
        sys.modules.update(modules)
        spec = importlib.util.spec_from_file_location(
            PACKAGE + ".sec2_lab_ws", COMPONENT / "sec2_lab_ws.py"
        )
        lab = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = lab
        spec.loader.exec_module(lab)
        return lab
    finally:
        for name, original in originals.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
        sys.modules.pop(PACKAGE + ".sec2_lab_ws", None)


lab = load_handler()


class Remote:
    def __init__(self, host="10.0.10.121"):
        self.entry_id = "remote1"
        self.data = {"host": host}


class Entries:
    def __init__(self, remote):
        self.remote = remote

    def async_entries(self, domain):
        assert domain == "omote_manager"
        return [self.remote]


class HA:
    def __init__(self, remote=None):
        self.config_entries = Entries(remote or Remote())
        self.data = {"candidate_store": Candidate()}


class Candidate:
    def status(self, entry_id):
        assert entry_id == "remote1"
        return {"prepared": True}


class Connection:
    def __init__(self, is_admin=True):
        self.user = types.SimpleNamespace(is_admin=is_admin)
        self.results = []
        self.errors = []

    def send_result(self, request_id, value):
        self.results.append((request_id, value))

    def send_error(self, request_id, code, message):
        self.errors.append((request_id, code, message))


class LabWebSocketTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.request = {
            "id": 7, "entry_id": "remote1", "pin": "123456",
            "ack_lab_only": True,
        }

    async def test_disabled_is_safe_and_readiness_reports_no_authorization(self):
        with patch.dict(os.environ, {"OMOTE_SEC2_LAB_ENABLE": "0"}, clear=True):
            hass, connection = HA(), Connection()
            await lab.ws_lab_readiness(hass, connection, self.request)
            status = connection.results[0][1]
            self.assertFalse(status["enabled"])
            self.assertFalse(status["can_attempt"])
            self.assertFalse(status["paired"])
            self.assertFalse(status["deployment_enabled"])
            await lab.ws_lab_test(hass, connection, self.request)
            self.assertEqual(len(connection.errors), 1)

    async def test_bundled_client_readiness_without_idf_path(self):
        with patch.dict(os.environ, {"OMOTE_SEC2_LAB_ENABLE": "1"}, clear=True):
            hass, conn = HA(), Connection()
            with patch.object(lab, "load_official_security2", return_value=object):
                await lab.ws_lab_readiness(hass, conn, self.request)
        self.assertFalse(conn.errors)
        status = conn.results[0][1]
        self.assertTrue(status["bundled_client_ready"])
        self.assertTrue(status["can_attempt"])
        self.assertEqual(status["security2_client"], "bundled-esp-idf-v5.4.2")
        self.assertNotIn("idf_path_configured", status)
        self.assertFalse(status["paired"])
        self.assertFalse(status["deployment_enabled"])

    async def test_bundled_client_preflight_failure_never_contacts_device(self):
        with patch.dict(os.environ, {"OMOTE_SEC2_LAB_ENABLE": "1"}, clear=True):
            hass, conn = HA(), Connection()
            with patch.object(lab, "load_official_security2",
                              side_effect=lab.LabPrerequisiteError("bad_bundle")):
                await lab.ws_lab_readiness(hass, conn, self.request)
        status = conn.results[0][1]
        self.assertFalse(status["bundled_client_ready"])
        self.assertFalse(status["can_attempt"])
        self.assertEqual(status["client_diagnostic"], "bad_bundle")

    async def test_nonadmin_rejected_before_all_diagnostics(self):
        hass, conn = HA(), Connection(is_admin=False)
        with patch.dict(os.environ, {"OMOTE_SEC2_LAB_ENABLE": "1"}):
            await lab.ws_lab_readiness(hass, conn, self.request)
            await lab.ws_lab_test(hass, conn, self.request)
        self.assertEqual(len(conn.errors), 2)
        self.assertFalse(conn.results)

    async def test_unregistered_and_public_hosts_rejected(self):
        with patch.dict(os.environ, {"OMOTE_SEC2_LAB_ENABLE": "1", "IDF_PATH": "/fake"}):
            bad_entry = dict(self.request, entry_id="unknown")
            conn = Connection()
            await lab.ws_lab_test(HA(), conn, bad_entry)
            self.assertEqual(len(conn.errors), 1)
            for bad_ip in ("8.8.8.8", "127.0.0.1", "169.254.1.1", "example.org"):
                with self.subTest(host=bad_ip):
                    conn = Connection()
                    await lab.ws_lab_test(HA(Remote(bad_ip)), conn, self.request)
                    self.assertEqual(len(conn.errors), 1)
                    self.assertFalse(conn.results)

    async def test_bad_pin_and_no_ack_rejected(self):
        with patch.dict(os.environ, {"OMOTE_SEC2_LAB_ENABLE": "1", "IDF_PATH": "/fake"}):
            for change in ({"pin": "12345"}, {"pin": "1234567"},
                           {"ack_lab_only": False}):
                conn = Connection()
                await lab.ws_lab_test(HA(), conn, {**self.request, **change})
                self.assertEqual(len(conn.errors), 1)
                self.assertFalse(conn.results)

    async def test_explicit_run_uses_registered_host_and_never_pins(self):
        async def fake_runner(**kwargs):
            self.assertEqual(kwargs["host"], "10.0.10.121")
            self.assertEqual(kwargs["entry_id"], "remote1")
            self.assertTrue(kwargs["ack_lab_only"])
            return {
                "lab_only": True, "paired": False, "trusted": False,
                "deployment_enabled": False, "ota_enabled": False,
            }
        with patch.dict(os.environ, {"OMOTE_SEC2_LAB_ENABLE": "1", "IDF_PATH": "/fake"}):
            hass, conn = HA(), Connection()
            with patch.object(lab, "load_official_security2", return_value=object), \
                    patch.object(lab, "run_tx2_lab_session", side_effect=fake_runner):
                await lab.ws_lab_test(hass, conn, self.request)
            self.assertFalse(conn.errors)
            self.assertEqual(len(conn.results), 1)
            self.assertFalse(conn.results[0][1]["paired"])
            self.assertFalse(conn.results[0][1]["deployment_enabled"])

    def test_fixed_ports_not_user_controlled_and_feature_not_production(self):
        source = (COMPONENT / "sec2_lab_ws.py").read_text()
        self.assertNotIn("vol.Required(\"host\")", source)
        self.assertNotIn("vol.Required(\"port\")", source)
        self.assertIn("OMOTE_SEC2_LAB_ENABLE", source)
        self.assertNotIn("deploy_configuration", source)
        self.assertNotIn("add_trusted", source)


if __name__ == "__main__":
    unittest.main()
