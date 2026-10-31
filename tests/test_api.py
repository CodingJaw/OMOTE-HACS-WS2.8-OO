"""Integration transport regressions for fragmented HTTP file responses.

Reproduces the original bug: one aiohttp StreamReader.read(n) may yield
only the first available network fragment, not the complete HTTP entity.
"""
from __future__ import annotations

import asyncio
import importlib.util
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
        app = web.Application()
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

    async def _stat(self, request):
        path = request.query.get("path")
        return web.json_response({"path": path, "size": len(self.source)})

    async def _raw(self, request):
        self.raw_calls += 1
        body = self.source
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
