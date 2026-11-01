"""Read-only v1/v2-preview capability negotiation regression tests."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest

from aiohttp import ClientSession, web

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "omote_manager"
PKG = "omote_capability_test"
package = types.ModuleType(PKG)
package.__path__ = [str(ROOT)]
sys.modules[PKG] = package


def load(name):
    spec = importlib.util.spec_from_file_location(PKG + "." + name, ROOT / (name + ".py"))
    obj = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = obj
    spec.loader.exec_module(obj)
    return obj


load("const")
load("safe_files")
load("workspace_model")
capability = load("capability_model")
api_module = load("api")


def preview():
    return {
        "api_version": "omote-config-v2-preview",
        "auth_mode": "not-implemented",
        "device_id": "",
        "firmware_build": "waveshare28v2-config-v2-preview",
        "max_file_bytes": 0,
        "max_transaction_bytes": 0,
        "available_staging_bytes": 0,
        "active_revision_sha256": "",
        "previous_revision_sha256": "",
        "transaction_support": False,
        "rollback_support": False,
        "write_protection_enabled": True,
        "legacy_http_writes_disabled": True,
    }


def storage():
    return {
        "storage": "littlefs", "total_bytes": 6_000_000,
        "used_bytes": 2_000_000, "estimated_free_bytes": 4_000_000,
        "nvs_readable": True, "slot0_valid": True,
        "slot1_valid": False, "selector_initialized": True,
        "selector_sequence": 3, "generation_activation_enabled": False
    }


class TestNormalization(unittest.TestCase):
    def test_legacy_is_explicitly_non_deployable(self):
        info = capability.summarize_capabilities(None)
        self.assertEqual(info["generation"], "legacy-v1")
        self.assertFalse(info["deployment_enabled"])
        self.assertFalse(info["transaction_support"])

    def test_actual_preview_values(self):
        info = capability.summarize_capabilities(preview())
        self.assertEqual(info["generation"], "preview")
        self.assertTrue(info["preview_only"])
        self.assertTrue(info["write_protection_enabled"])
        self.assertFalse(info["deployment_enabled"])
        self.assertFalse(info["device_identity_available"])

    def test_all_remote_flags_positive_still_cannot_authorize_deploy(self):
        advertised = preview()
        advertised.update({
            "api_version": "omote-config-v2",
            "auth_mode": "tls-pinned",
            "device_id": "device-123",
            "transaction_support": True,
            "rollback_support": True,
            "max_file_bytes": 256 * 1024,
            "max_transaction_bytes": 2 * 1024 * 1024,
            "available_staging_bytes": 3 * 1024 * 1024,
            "active_revision_sha256": "a" * 64,
            "previous_revision_sha256": "b" * 64,
        })
        info = capability.summarize_capabilities(advertised)
        self.assertEqual(info["generation"], "v2-advertised")
        self.assertTrue(info["transaction_support"])
        self.assertTrue(info["device_identity_available"])
        self.assertTrue(info["active_revision_available"])
        self.assertFalse(info["deployment_enabled"])
        self.assertNotIn("device-123", str(info))
        self.assertNotIn("a" * 64, str(info))

    def test_read_only_storage_diagnostics_validation(self):
        info = capability.summarize_storage_status(storage())
        self.assertEqual(info["estimated_free_bytes"], 4_000_000)
        self.assertTrue(info["selector_initialized"])
        self.assertFalse(info["generation_activation_enabled"])
        self.assertFalse(capability.summarize_storage_status(None)["available"])

    def test_storage_fail_closed_on_unsupported_flags_and_sizes(self):
        for edits in [
            {"total_bytes": -1},
            {"used_bytes": 8_000_000},
            {"estimated_free_bytes": 5_000_000},
            {"selector_initialized": 1},
            {"generation_activation_enabled": "false"},
            {"storage": "sdcard"},
        ]:
            invalid = storage()
            invalid.update(edits)
            with self.subTest(edits=edits), self.assertRaises(
                capability.CapabilitiesError
            ):
                capability.summarize_storage_status(invalid)

    def test_missing_field_wrong_types_and_digest_rejected(self):
        invalids = []
        missing = preview()
        del missing["rollback_support"]
        invalids.append(missing)
        wrong_bool = preview()
        wrong_bool["transaction_support"] = 1
        invalids.append(wrong_bool)
        wrong_limit = preview()
        wrong_limit["max_file_bytes"] = -1
        invalids.append(wrong_limit)
        bad_hash = preview()
        bad_hash["active_revision_sha256"] = "not-a-digest"
        invalids.append(bad_hash)
        wrong_ver = preview()
        wrong_ver["api_version"] = "omote-config-v1"
        invalids.append(wrong_ver)
        for data in invalids:
            with self.subTest(data=data), self.assertRaises(capability.CapabilitiesError):
                capability.summarize_capabilities(data)


class TestReadOnlyProbe(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mode = "preview"
        self.requests = []
        app = web.Application()
        app.router.add_route("*", "/api/config/v2/capabilities", self._respond)
        app.router.add_route("*", "/api/config/v2/storage/status", self._storage)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await self.site.start()
        port = self.site._server.sockets[0].getsockname()[1]
        self.session = ClientSession()
        self.api = api_module.OmoteApi(self.session, "127.0.0.1", port)

    async def asyncTearDown(self):
        await self.session.close()
        await self.runner.cleanup()

    async def _respond(self, request):
        self.requests.append(request.method)
        if self.mode == "legacy":
            return web.Response(status=404)
        if self.mode == "redirect":
            return web.Response(status=302, headers={"Location": "https://example.com"})
        if self.mode == "oversized":
            return web.json_response(dict(preview(), garbage="z" * 9000))
        if self.mode == "malformed":
            return web.Response(text="{", content_type="application/json")
        return web.json_response(preview())

    async def _storage(self, request):
        self.requests.append(request.method)
        if self.mode == "legacy":
            return web.Response(status=404)
        if self.mode == "malformed":
            return web.Response(text="{", content_type="application/json")
        return web.json_response(storage())

    async def test_storage_request_is_read_only(self):
        result = await self.api.storage_status()
        self.assertTrue(result["available"])
        self.assertEqual(self.requests, ["GET"])
        self.mode = "legacy"
        missing = await self.api.storage_status()
        self.assertFalse(missing["available"])
        self.assertEqual(self.requests, ["GET", "GET"])

    async def test_malformed_storage_rejected(self):
        self.mode = "malformed"
        with self.assertRaises(api_module.OmoteApiError):
            await self.api.storage_status()

    async def test_preview_read_only(self):
        response = await self.api.capabilities()
        self.assertTrue(response["preview_only"])
        self.assertFalse(response["deployment_enabled"])
        self.assertEqual(self.requests, ["GET"])

    async def test_legacy_404_falls_back_to_read_only(self):
        self.mode = "legacy"
        response = await self.api.capabilities()
        self.assertEqual(response["generation"], "legacy-v1")
        self.assertEqual(self.requests, ["GET"])

    async def test_redirect_is_not_followed(self):
        self.mode = "redirect"
        with self.assertRaises(api_module.OmoteApiError):
            await self.api.capabilities()
        self.assertEqual(self.requests, ["GET"])

    async def test_oversized_response_is_rejected(self):
        self.mode = "oversized"
        with self.assertRaisesRegex(api_module.OmoteApiError, "expected size"):
            await self.api.capabilities()

    async def test_malformed_json_is_rejected(self):
        self.mode = "malformed"
        with self.assertRaises(api_module.OmoteApiError):
            await self.api.capabilities()


if __name__ == "__main__":
    unittest.main()
