"""Bounded, strictly scoped aiohttp transport for OMOTE Security2 LAB.

Replaces the official esp_prov Transport_HTTP *transport only* because
the reference HTTPConnection client blocks HA's asyncio event loop and has a
60-second socket timeout. Cryptographic Security2 remains Espressif's code.

Never exposes general HTTP access, never follows redirects, never sends
credentials to a proxy, and never touches the port-80 Config API.
"""
from __future__ import annotations

import ipaddress
import re

import aiohttp

_ALLOWED_ENDPOINTS = frozenset({
    "proto-ver", "prov-session", "omote-probe",
    "omote-ha-proof", "omote-device-proof",
    "omote-tx2-open", "omote-tx2-commit", "omote-tx2-review",
    "omote-tx2-touch-receipt",
})
_COOKIE = re.compile(r"session=(?:0|[1-9][0-9]{0,9})\Z", re.ASCII)
_MAX_RESPONSE_BYTES = 4096
_MAX_REQUEST_BYTES = 4096
_TIMEOUT_SECONDS = 8


class LabHttpTransportError(ValueError):
    """Sanitized transport rejection without server response or secret data."""


class LabHttpTransport:
    """Private one-session HTTP transport for fixed device LAB endpoints.

    The address matches the official Espressif factory's HOST:PORT interface.
    The aiohttp session is disposable and has a disabled cookie jar: only the
    explicitly validated Security2 session cookie is re-sent.
    """

    def __init__(self, address: str):
        if type(address) is not str or address.count(":") != 1:
            raise LabHttpTransportError("Invalid LAB address")
        host, port = address.split(":")
        try:
            addr = ipaddress.IPv4Address(host)
        except ipaddress.AddressValueError:
            raise LabHttpTransportError("LAB requires a literal IPv4 address") from None
        if port != "18082":
            raise LabHttpTransportError("Unexpected LAB port")
        self._host = str(addr)
        self._url = f"http://{self._host}:18082"
        self.headers = {}
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=_TIMEOUT_SECONDS),
            cookie_jar=aiohttp.DummyCookieJar(),
            trust_env=False,
        )
        self._closed = False

    async def send_data(self, endpoint: str, payload: bytes | str) -> str:
        if self._closed:
            raise LabHttpTransportError("Closed LAB transport")
        if type(endpoint) is not str or endpoint not in _ALLOWED_ENDPOINTS:
            raise LabHttpTransportError("Unexpected LAB endpoint")
        if type(payload) is str:
            try:
                body = payload.encode("latin-1")
            except UnicodeEncodeError:
                raise LabHttpTransportError("Invalid LAB request encoding") from None
        elif type(payload) is bytes:
            body = payload
        else:
            raise LabHttpTransportError("Invalid LAB request body")
        if len(body) > _MAX_REQUEST_BYTES:
            raise LabHttpTransportError("Oversized LAB request")
        headers = {
            "Content-type": "application/x-www-form-urlencoded",
            "Accept": "text/plain",
        }
        if "Cookie" in self.headers:
            headers["Cookie"] = self.headers["Cookie"]

        async with self._session.post(
            f"{self._url}/{endpoint}",
            data=body,
            headers=headers,
            allow_redirects=False,
        ) as response:
            if response.status != 200:
                raise LabHttpTransportError("LAB returned a non-200 response")
            cookie = response.headers.get("Set-Cookie")
            if cookie is not None:
                if not _COOKIE.fullmatch(cookie):
                    raise LabHttpTransportError("Invalid LAB session cookie")
                if int(cookie[8:]) > 0xFFFFFFFF:
                    raise LabHttpTransportError("Out-of-range LAB session ID")
                if "Cookie" in self.headers and cookie != self.headers["Cookie"]:
                    raise LabHttpTransportError("LAB session changed unexpectedly")
            # Stream to EOF with an absolute cap. aiohttp read(n) may
            # return fewer than n bytes before the response is complete.
            parts = []
            total = 0
            async for part in response.content.iter_chunked(512):
                total += len(part)
                if total > _MAX_RESPONSE_BYTES:
                    raise LabHttpTransportError("Oversized LAB response")
                parts.append(part)
            raw = b"".join(parts)
            if cookie is not None:
                self.headers["Cookie"] = cookie
            # Official Espressif HTTP transport uses latin-1 end-to-end
            # for arbitrary protobuf and AES-GCM ciphertext octets.
            return raw.decode("latin-1")

    async def aclose(self) -> None:
        if not self._closed:
            self._closed = True
            await self._session.close()
