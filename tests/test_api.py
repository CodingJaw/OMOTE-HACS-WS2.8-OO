"""Integration transport regressions for fragmented HTTP file responses.

Reproduces the original bug: one aiohttp StreamReader.read(n) may yield
only the first available network fragment, not the complete HTTP entity.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest

from aiohttp import ClientSession, web

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "omote_manager"
PKG = "omote_api_transport_test"
package = types.ModuleType(PKG)
package.__path__ = [str(ROOT)]
sys.modules[PKG] = package


def load(name):
    spec = importlib.util.spec_from_file_location(
        PKG + "." + name, ROOT / (name + ".py")
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


load("const")
load("safe_files")
load("workspace_model")
client = load("api")

DOC = (
    '{"Manufacturer":"Test","DeviceClass":"TV","Commands":['
    + ",".join(
        '{"Command":"KEY_%03d","Mode":"IR","Protocol":"NEC",'
        '"Data":["0x40BE30CF"]}' % i
        for i in range(90)
    )
    + "]}"
).encode("utf-8")


class TestCompleteHttpReads(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.raw_mode = "fragmented"
        self.chunk_mode = "good"
        self.chunk_calls = 0
        self.raw_calls = 0
        self.source = DOC
        self.status_mode = "good"
        self.pair_mode = "legacy"
        self.raw_mode = "fragmented"
        app = web.Application()
        app.router.add_get("/api/status", self._status)
        app.router.add_get("/api/config/v2/pairing/status", self._pair_status)
        app.router.add_get("/api/fs/stat", self._stat)
        app.router.add_get("/api/fs/read/raw", self._raw)
        app.router.add_get("/api/fs/read/chunk", self._chunk)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await self.site.start()
        sock = self.site._server.sockets[0]
        port = sock.getsockname()[1]
        self.session = ClientSession()
        self.api = client.OmoteApi(self.session, "127.0.0.1", port)

    async def asyncTearDown(self):
        await self.session.close()
        await self.runner.cleanup()

    async def _status(self, request):
        if self.status_mode == "redirect":
            raise web.HTTPFound(location="http://127.0.0.1:1/secret")
        if self.status_mode == "oversize":
            return web.Response(
                body=b'{"api":"omote-config-v1","padding":"' +
                b"x" * (128 * 1024) + b'"}',
                content_type="application/json",
            )
        return web.json_response({"api": "omote-config-v1"})


    async def _pair_status(self, request):
        if self.pair_mode == "legacy":
            raise web.HTTPNotFound()
        if self.pair_mode == "redirect":
            raise web.HTTPFound(location="http://127.0.0.1:1/exfil")
        if self.pair_mode == "oversize":
            return web.Response(body=b'{"padding":"' + b"x" * 5000 + b'"}')
        fixture = json.loads(
            (Path(__file__).resolve().parent /
             "fixtures/pairing_v1_preview_contract.json").read_text()
        )["response"]
        if self.pair_mode == "fake-secure":
            fixture["session_ready"] = True
        return web.json_response(fixture)

    async def _stat(self, request):
        path = request.query.get("path")
        return web.json_response({"path": path, "size": len(self.source)})

    async def _raw(self, request):
        self.raw_calls += 1
        body = self.source
        if self.raw_mode == "redirect":
            raise web.HTTPFound(location="http://127.0.0.1:1/secret")
        if self.raw_mode == "partial":
            body = body[:1234]
        elif self.raw_mode == "corrupt":
            # Same byte length but invalid JSON: must not be imported.
            body = body[:112] + b"[" + body[113:]
        response = web.StreamResponse(
            status=200, headers={"Content-Type": "application/json"}
        )
        await response.prepare(request)
        for i in range(0, len(body), 197):
            await response.write(body[i:i+197])
            await asyncio.sleep(0.0001)
        await response.write_eof()
        return response

    async def _chunk(self, request):
        self.chunk_calls += 1
        path = request.query.get("path")
        offset = int(request.query.get("offset", 0))
        count = int(request.query.get("max", 2048))
        if self.chunk_mode == "redirect":
            raise web.HTTPFound(location="http://127.0.0.1:1/secret")
        data = self.source[offset:offset + count]
        if self.chunk_mode == "partial":
            data = data[:-4]
        headers = {
            "X-OMOTE-Path": path,
            "X-OMOTE-Offset": str(offset),
            "X-OMOTE-Total": str(len(self.source)),
            "X-OMOTE-Length": str(len(self.source[offset:offset + count])),
            "X-OMOTE-More": (
                "1" if offset + count < len(self.source) else "0"
            ),
        }
        return web.Response(
            body=data, headers=headers, content_type="application/octet-stream"
        )


    async def test_pairing_status_legacy_returns_disabled(self):
        status = await self.api.pairing_status()
        self.assertFalse(status["available"])
        self.assertFalse(status["pairing_enabled"])
        self.assertFalse(status["deployment_enabled"])

    async def test_pairing_status_preview_never_authorizes_pairing(self):
        self.pair_mode = "valid"
        status = await self.api.pairing_status()
        self.assertTrue(status["available"])
        self.assertFalse(status["encrypted_session_ready"])
        self.assertFalse(status["pairing_enabled"])

    async def test_forged_pairing_enabled_metadata_is_rejected(self):
        self.pair_mode = "fake-secure"
        with self.assertRaises(client.OmoteApiError):
            await self.api.pairing_status()

    async def test_pairing_redirect_and_oversized_payload_fail_closed(self):
        for mode in ("redirect", "oversize"):
            self.pair_mode = mode
            with self.subTest(mode=mode), self.assertRaises(client.OmoteApiError):
                await self.api.pairing_status()

    async def test_legacy_json_redirect_rejected(self):
        self.status_mode = "redirect"
        with self.assertRaises(client.OmoteApiError):
            await self.api.status()

    async def test_legacy_json_oversize_rejected(self):
        self.status_mode = "oversize"
        with self.assertRaisesRegex(client.OmoteApiError, "expected size"):
            await self.api.status()

    async def test_raw_redirect_falls_back_to_valid_chunk(self):
        self.raw_mode = "redirect"
        result = await self.api.read_file("Commands/Test.json", verify_json=True)
        self.assertEqual(result.encode("utf-8"), DOC)
        self.assertGreater(self.chunk_calls, 0)

    async def test_redirects_never_supply_raw_or_chunk_bytes(self):
        self.raw_mode = "redirect"
        self.chunk_mode = "redirect"
        with self.assertRaises(client.OmoteApiError):
            await self.api.read_file("Commands/Test.json", verify_json=True)

    async def test_binary_png_larger_than_json_limit(self):
        image = b"\\x89PNG\\r\\n\\x1a\\n" + b"X" * (72 * 1024)
        self.source = image
        result = await self.api.read_image_asset("Images/living-room.png")
        self.assertEqual(result, image)
        self.assertEqual(self.chunk_calls, 0)

    async def test_binary_jpeg_retrieval_via_chunks(self):
        image = b"\\xff\\xd8\\xff" + b"X" * 7000
        self.source = image
        self.raw_mode = "partial"
        result = await self.api.read_image_asset("Images/living-room.jpeg")
        self.assertEqual(result, image)
        self.assertGreater(self.chunk_calls, 0)

    async def test_invalid_image_signature_rejected(self):
        self.source = b"not a valid png"
        with self.assertRaisesRegex(client.OmoteApiError, "signature"):
            await self.api.read_image_asset("Images/fake.png")

    async def test_image_path_and_quota_rejected(self):
        for path in ("../Images/secret.png", "Images/../secret.png",
                     "DeviceSettings.json", "Images/evil.svg"):
            with self.subTest(path=path), self.assertRaises(client.OmoteApiError):
                await self.api.read_image_asset(path)
        self.source = b"\\x89PNG\\r\\n\\x1a\\n" + b"X" * (512 * 1024)
        with self.assertRaisesRegex(client.OmoteApiError, "exceeds"):
            await self.api.read_image_asset("Images/huge.png")

    async def test_short_image_transfer_rejected(self):
        self.source = b"\\x89PNG\\r\\n\\x1a\\n" + b"X" * 3000
        self.raw_mode = "partial"
        self.chunk_mode = "partial"
        with self.assertRaises(client.OmoteApiError):
            await self.api.read_image_asset("Images/room.png")

    async def test_fragments_consumed_to_eof(self):
        result = await self.api.read_file("Commands/Test.json", verify_json=True)
        self.assertEqual(result.encode("utf-8"), DOC)
        self.assertEqual(self.raw_calls, 1)
        self.assertEqual(self.chunk_calls, 0)

    async def test_short_raw_response_falls_back_to_chunked_reads(self):
        self.raw_mode = "partial"
        result = await self.api.read_file("Commands/Test.json", verify_json=True)
        self.assertEqual(result.encode("utf-8"), DOC)
        self.assertGreater(self.chunk_calls, 1)

    async def test_corrupt_same_size_raw_response_falls_back(self):
        self.raw_mode = "corrupt"
        result = await self.api.read_file("Commands/Test.json", verify_json=True)
        self.assertEqual(result.encode("utf-8"), DOC)
        self.assertGreater(self.chunk_calls, 0)

    async def test_short_chunks_rejected(self):
        self.raw_mode = "partial"
        self.chunk_mode = "partial"
        with self.assertRaisesRegex(client.OmoteApiError, "Unable to safely read"):
            await self.api.read_file("Commands/Test.json", verify_json=True)

    async def test_oversized_file_rejected_before_transfer(self):
        self.source = b"a" * (64 * 1024 + 1)
        with self.assertRaisesRegex(client.OmoteApiError, "exceeds 64 KiB"):
            await self.api.read_file("Commands/Test.json")
        self.assertEqual(self.raw_calls, 0)
        self.assertEqual(self.chunk_calls, 0)

    async def test_unsafe_path_rejected(self):
        with self.assertRaisesRegex(client.OmoteApiError, "Unsafe"):
            await self.api.read_file("../HaSettings.json")


if __name__ == "__main__":
    unittest.main()
