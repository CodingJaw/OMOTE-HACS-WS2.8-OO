"""Mocked HA 2024.9.1 config-flow tests for zeroconf plus manual fallback.

No Home Assistant server or LAN access is required. Patch modules only during
this module's test import, restoring original sys.modules immediately.
"""
from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import ipaddress
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "omote_manager"
PKG = "omote_discovery_flow_test"
package = types.ModuleType(PKG)
package.__path__ = [str(ROOT)]
sys.modules[PKG] = package


def load(name):
    spec = importlib.util.spec_from_file_location(PKG + "." + name, ROOT / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


load("const")
load("form")


@dataclass
class Entry:
    data: dict


class Flow:
    def __init_subclass__(cls, **kwargs):
        pass

    def __init__(self):
        self.hass = object()
        self.entries = []
        self.context = {}
        self.unique_id = None

    def _async_current_entries(self):
        return self.entries

    async def async_set_unique_id(self, unique_id):
        self.unique_id = unique_id

    def _abort_if_unique_id_configured(self):
        pass

    def async_abort(self, *, reason):
        return {"type": "abort", "reason": reason}

    def async_show_form(self, *, step_id, data_schema, errors=None):
        return {"type": "form", "step_id": step_id, "schema": data_schema,
                "errors": errors}

    def async_create_entry(self, *, title, data):
        return {"type": "create_entry", "title": title, "data": data}


class FakeApiError(Exception):
    pass


class FakeApi:
    status_result = {"hostname": "omote", "api": "omote-config-v1"}
    failure = False

    def __init__(self, session, host, port):
        self.host = host
        self.port = port

    async def status(self):
        if self.failure:
            raise FakeApiError("unavailable")
        return dict(self.status_result)


@dataclass
class Info:
    host: str = "192.168.1.22"
    port: int = 80
    properties: dict | None = None


ha = types.ModuleType("homeassistant")
ha.config_entries = types.ModuleType("homeassistant.config_entries")
ha.config_entries.ConfigFlow = Flow
components = types.ModuleType("homeassistant.components")
zc = types.ModuleType("homeassistant.components.zeroconf")
zc.ZeroconfServiceInfo = Info
helpers = types.ModuleType("homeassistant.helpers")
aio = types.ModuleType("homeassistant.helpers.aiohttp_client")
aio.async_get_clientsession = lambda hass: object()
api = types.ModuleType(PKG + ".api")
api.OmoteApi = FakeApi
api.OmoteApiError = FakeApiError
mocks = {
    "homeassistant": ha,
    "homeassistant.config_entries": ha.config_entries,
    "homeassistant.components": components,
    "homeassistant.components.zeroconf": zc,
    "homeassistant.helpers": helpers,
    "homeassistant.helpers.aiohttp_client": aio,
    PKG + ".api": api,
}
with patch.dict(sys.modules, mocks):
    flow_module = load("config_flow")


def info(**values):
    data = {
        "host": "192.168.1.22", "port": 80,
        "properties": {
            "id": "aabbccddeeff",
            "api": "omote-config-v1",
            "model": "waveshare28v2",
        },
    }
    data.update(values)
    return Info(**data)


class TestDiscoveryFlow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        FakeApi.failure = False
        FakeApi.status_result = {"hostname": "omote", "api": "omote-config-v1"}
        self.flow = flow_module.OmoteManagerConfigFlow()

    async def test_requires_explicit_confirmation_after_matching_omote(self):
        first = await self.flow.async_step_zeroconf(info())
        self.assertEqual(first["type"], "form")
        self.assertEqual(first["step_id"], "zeroconf_confirm")
        self.assertEqual(self.flow.unique_id, "omote:aabbccddeeff")
        self.assertEqual(self.flow.context["title_placeholders"]["host"], "192.168.1.22")
        second = await self.flow.async_step_zeroconf_confirm({})
        self.assertEqual(second["type"], "create_entry")
        self.assertEqual(second["data"]["host"], "192.168.1.22")
        self.assertEqual(second["data"]["discovery_id"], "aabbccddeeff")

    async def test_existing_manual_host_does_not_duplicate(self):
        self.flow.entries = [Entry(data={"host": "192.168.1.22", "port": 80})]
        r = await self.flow.async_step_zeroconf(info())
        self.assertEqual(r["reason"], "already_configured")

    async def test_existing_manual_local_hostname_does_not_duplicate(self):
        self.flow.entries = [Entry(data={"host": "omote.local", "port": 80})]
        r = await self.flow.async_step_zeroconf(info())
        self.assertEqual(r["reason"], "already_configured")

    async def test_known_discovery_id_does_not_override_ip(self):
        self.flow.entries = [Entry(data={
            "host": "192.168.1.10", "port": 80,
            "discovery_id": "aabbccddeeff"
        })]
        r = await self.flow.async_step_zeroconf(info(host="192.168.1.22"))
        self.assertEqual(r["reason"], "already_configured")
        self.assertEqual(self.flow.entries[0].data["host"], "192.168.1.10")

    async def test_wrong_service_properties_refused_without_probe(self):
        for props in [
            None, {}, {"id":"abcd","api":"omote-config-v1","model":"waveshare28v2"},
            {"id":"aabbccddeeff","api":"omote-config-v2-preview","model":"waveshare28v2"},
            {"id":"aabbccddeeff","api":"omote-config-v1","model":"other"}
        ]:
            with self.subTest(props=props):
                result = await self.flow.async_step_zeroconf(info(properties=props))
                self.assertEqual(result["reason"], "invalid_discovery")

    async def test_public_and_ipv6_addresses_refused(self):
        for host in ["8.8.8.8", "::1", "fe80::1", "not-an-ip", "127.0.0.1"]:
            with self.subTest(host=host):
                r = await self.flow.async_step_zeroconf(info(host=host))
                self.assertEqual(r["reason"], "invalid_discovery")

    async def test_invalid_ports_and_unresponsive_remote_refused(self):
        for port in [0, -1, 65536, None]:
            r = await self.flow.async_step_zeroconf(info(port=port))
            self.assertEqual(r["reason"], "invalid_discovery")
        FakeApi.failure = True
        r = await self.flow.async_step_zeroconf(info())
        self.assertEqual(r["reason"], "cannot_connect")

    async def test_confirmation_cannot_reuse_disappearing_device(self):
        await self.flow.async_step_zeroconf(info())
        self.flow.entries = [Entry(data={"host":"192.168.1.22","port":80})]
        r = await self.flow.async_step_zeroconf_confirm({})
        self.assertEqual(r["reason"], "already_configured")

    async def test_manual_setup_remains_available(self):
        result = await self.flow.async_step_user({"host":"OMOTE.local","port":80})
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"]["host"], "omote.local")
        self.assertEqual(self.flow.unique_id, "omote.local:80")
        self.assertNotIn("discovery_id", result["data"])


if __name__ == "__main__":
    unittest.main()
