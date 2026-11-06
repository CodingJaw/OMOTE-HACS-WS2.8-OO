"""Offline tests of the async port-18082 Security2 LAB transport.

No network socket is opened; aiohttp.ClientSession is replaced with a
deterministic fake that captures method, cookie, redirect and payload rules.
"""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components/omote_manager"
package = types.ModuleType("sec2_http_tests")
package.__path__ = [str(COMPONENT)]
sys.modules[package.__name__] = package
spec = importlib.util.spec_from_file_location(
    package.__name__ + ".sec2_lab_http", COMPONENT / "sec2_lab_http.py"
)
transport_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = transport_module
spec.loader.exec_module(transport_module)


class FakeContent:
    def __init__(self, body):
        self.body = body

    async def iter_chunked(self, maximum):
        # Simulate a response split across multiple TCP reads.
        for offset in range(0, len(self.body), maximum):
            yield self.body[offset:offset + maximum]


class FakeResponse:
    def __init__(self, status=200, headers=None, body=b"OK"):
        self.status = status
        self.headers = headers or {}
        self.content = FakeContent(body)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class FakeSession:
    def __init__(self, *, timeout, cookie_jar, trust_env):
        self.timeout = timeout
        self.cookie_jar = cookie_jar
        self.trust_env = trust_env
        self.calls = []
        self.responses = []
        self.closed = False

    def post(self, url, *, data, headers, allow_redirects):
        self.calls.append((url, data, headers.copy(), allow_redirects))
        return self.responses.pop(0)

    async def close(self):
        self.closed = True


class LabTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mocks = []
        def factory(**kwargs):
            value = FakeSession(**kwargs)
            self.mocks.append(value)
            return value
        self.patcher = patch.object(transport_module.aiohttp, "ClientSession", factory)
        self.patcher.start()
        self.client = transport_module.LabHttpTransport("10.0.10.121:18082")
        self.http = self.mocks[-1]

    async def asyncTearDown(self):
        await self.client.aclose()
        self.patcher.stop()

    async def test_fixed_uri_bounded_io_no_proxy_cookie_jar_or_redirect(self):
        self.assertFalse(self.http.trust_env)
        self.assertIsInstance(
            self.http.cookie_jar, transport_module.aiohttp.DummyCookieJar
        )
        self.assertEqual(self.http.timeout.total, 8)
        self.http.responses.append(FakeResponse(
            200, {"Set-Cookie": "session=17"}, b"\x00\x80\xff"
        ))
        data = await self.client.send_data("prov-session", b"\x00\xfa\xff")
        self.assertEqual(data.encode("latin-1"), b"\x00\x80\xff")
        url, body, headers, redirects = self.http.calls[-1]
        self.assertEqual(url, "http://10.0.10.121:18082/prov-session")
        self.assertEqual(body, b"\x00\xfa\xff")
        self.assertFalse(redirects)
        self.assertNotIn("Cookie", headers)
        self.assertEqual(self.client.headers["Cookie"], "session=17")

        self.http.responses.append(FakeResponse(200, {}, b"ACK"))
        self.assertEqual(await self.client.send_data("omote-ha-proof", "X"), "ACK")
        self.assertEqual(self.http.calls[-1][2]["Cookie"], "session=17")

    async def test_rejects_non_allowlisted_endpoint_without_network(self):
        for bad in ("/config", "../omote-probe", "prov-config", 5, []):
            with self.subTest(endpoint=bad):
                with self.assertRaises(transport_module.LabHttpTransportError):
                    await self.client.send_data(bad, "secret")
        self.assertFalse(self.http.calls)

    async def test_rejects_bad_cookie_cookie_rotation_and_redirect(self):
        self.http.responses.append(FakeResponse(
            200, {"Set-Cookie": "session=17; Path=/"}, b"OK"
        ))
        with self.assertRaises(transport_module.LabHttpTransportError):
            await self.client.send_data("prov-session", "a")
        self.assertEqual(self.client.headers, {})

        self.http.responses.append(FakeResponse(
            200, {"Set-Cookie": "session=17"}, b"OK"
        ))
        await self.client.send_data("prov-session", "a")
        self.http.responses.append(FakeResponse(
            200, {"Set-Cookie": "session=18"}, b"OK"
        ))
        with self.assertRaises(transport_module.LabHttpTransportError):
            await self.client.send_data("prov-session", "a")
        self.http.responses.append(FakeResponse(302, {"Location": "http://bad"}, b""))
        with self.assertRaises(transport_module.LabHttpTransportError):
            await self.client.send_data("omote-probe", "a")

    async def test_response_request_limits(self):
        with self.assertRaises(transport_module.LabHttpTransportError):
            await self.client.send_data("omote-probe", b"x" * 4097)
        self.assertFalse(self.http.calls)
        self.http.responses.append(FakeResponse(200, {}, b"x" * 4097))
        with self.assertRaises(transport_module.LabHttpTransportError):
            await self.client.send_data("omote-probe", "a")
        self.assertEqual(len(self.http.calls), 1)

    async def test_closed_client_and_invalid_destinations(self):
        await self.client.aclose()
        self.assertTrue(self.http.closed)
        with self.assertRaises(transport_module.LabHttpTransportError):
            await self.client.send_data("proto-ver", "-")
        for address in ("example.com:18082", "10.0.10.121:80",
                        "10.0.10.121:18082/path", "[::1]:18082"):
            with self.assertRaises(transport_module.LabHttpTransportError):
                transport_module.LabHttpTransport(address)


if __name__ == "__main__":
    unittest.main()
