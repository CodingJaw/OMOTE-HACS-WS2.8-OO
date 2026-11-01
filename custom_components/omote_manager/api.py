"""Bounded, complete HTTP transport for the existing OMOTE configuration API.

The firmware exposes raw stream and chunk endpoints. aiohttp's
StreamReader.read(n) MAY return less than n before EOF; always consume a
response to completion. Verify every file against /api/fs/stat. A failed
raw transfer falls back to the firmware's fixed-size chunk interface.
No HTTP write operations are implemented.
"""
from __future__ import annotations

import asyncio
import logging
import json
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import MAX_BACKUP_FILE_BYTES, SUPPORTED_API
from .capability_model import CapabilitiesError, summarize_capabilities
from .workspace_model import WorkspaceError, parse_jsonc

_LOGGER = logging.getLogger(__name__)

_CHUNK_SIZE = 2048
_READ_TIMEOUT = 35


class OmoteApiError(Exception):
    """Raised when an OMOTE API request cannot be completed safely."""


class OmoteApi:
    """Transport for the firmware's omote-config-v1 endpoints."""

    def __init__(self, session: ClientSession, host: str, port: int = 80) -> None:
        self._session = session
        self._base = f"http://{host}:{port}"

    async def _json(
        self, path: str, *, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            async with asyncio.timeout(20):
                async with self._session.get(
                    self._base + path,
                    params=params,
                    timeout=ClientTimeout(total=18),
                ) as response:
                    response.raise_for_status()
                    payload = await response.json(content_type=None)
        except (ClientError, asyncio.TimeoutError, ValueError) as exc:
            raise OmoteApiError(f"OMOTE API request {path} failed: {exc}") from exc
        if not isinstance(payload, dict):
            raise OmoteApiError(f"OMOTE API returned invalid object for {path}")
        return payload

    async def status(self) -> dict[str, Any]:
        """Verify the firmware reports the expected configuration API."""
        status = await self._json("/api/status")
        if status.get("api") != SUPPORTED_API:
            raise OmoteApiError(
                f"Unsupported OMOTE API: {status.get('api')!r}"
            )
        return status

    async def capabilities(self) -> dict[str, Any]:
        """Inspect optional read-only config-v2 capability metadata.

        A 404 means the older firmware has no v2 endpoint. All capability
        results are fail-closed and NEVER grant access to write methods.
        """
        endpoint = "/api/config/v2/capabilities"
        try:
            async with asyncio.timeout(12):
                async with self._session.get(
                    self._base + endpoint,
                    timeout=ClientTimeout(total=10),
                    allow_redirects=False,
                ) as response:
                    if response.status == 404:
                        return summarize_capabilities(None)
                    if response.status != 200:
                        raise OmoteApiError(
                            f"Capability request returned HTTP {response.status}"
                        )
                    payload = await self._read_complete(response, 8192)
        except (ClientError, asyncio.TimeoutError) as exc:
            raise OmoteApiError(f"Read-only capability request failed: {exc}") from exc
        try:
            obj = json.loads(payload.decode("utf-8"))
            return summarize_capabilities(obj)
        except (UnicodeDecodeError, ValueError, CapabilitiesError) as exc:
            raise OmoteApiError(f"Invalid firmware capability metadata: {exc}") from exc

    async def files(self) -> list[str]:
        """Enumerate JSON files without downloading their contents."""
        tree = await self._json("/api/fs/tree")
        paths = tree.get("files")
        if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
            raise OmoteApiError("Invalid filesystem tree response")
        return sorted(set(paths))

    async def settings(self) -> dict[str, Any]:
        """Read effective device settings (contains runtime status fields)."""
        return await self._json("/api/device/settings")

    async def settings_schema(self) -> dict[str, Any]:
        """Read the firmware-provided device settings editor schema."""
        return await self._json("/api/device/settings/schema")

    @staticmethod
    def _check_path(path: str) -> None:
        if (
            not isinstance(path, str)
            or not path
            or path.startswith("/")
            or ".." in path
            or "\\" in path
            or "\x00" in path
        ):
            raise OmoteApiError("Unsafe filesystem path")

    async def file_size(self, path: str) -> int:
        """Read authoritative size from the firmware's file-stat API."""
        self._check_path(path)
        data = await self._json("/api/fs/stat", params={"path": path})
        size = data.get("size")
        if data.get("path") != path or type(size) is not int or size < 0:
            raise OmoteApiError(f"Invalid size metadata for {path}")
        if size > MAX_BACKUP_FILE_BYTES:
            raise OmoteApiError(f"File {path} exceeds 64 KiB limit ({size} bytes)")
        return size

    @staticmethod
    async def _read_complete(response, limit: int) -> bytes:
        """Drain to EOF, never assume one StreamReader.read returns all data."""
        payload = bytearray()
        async for block in response.content.iter_chunked(_CHUNK_SIZE):
            payload.extend(block)
            if len(payload) > limit:
                raise OmoteApiError("HTTP response exceeds expected size")
        return bytes(payload)

    async def _read_raw(self, path: str, expected_size: int) -> bytes:
        try:
            async with asyncio.timeout(_READ_TIMEOUT):
                async with self._session.get(
                    self._base + "/api/fs/read/raw",
                    params={"path": path},
                    timeout=ClientTimeout(total=_READ_TIMEOUT - 2),
                ) as response:
                    response.raise_for_status()
                    value = await self._read_complete(response, expected_size)
        except (ClientError, asyncio.TimeoutError) as exc:
            raise OmoteApiError(f"Raw file read failed for {path}: {exc}") from exc
        return value

    @staticmethod
    def _header_int(headers: Any, key: str, path: str) -> int:
        text = headers.get(key)
        try:
            if text is None:
                raise ValueError("missing header")
            value = int(text)
        except (TypeError, ValueError) as exc:
            raise OmoteApiError(
                f"Missing or invalid {key} in chunk for {path}"
            ) from exc
        if value < 0:
            raise OmoteApiError(f"Negative {key} in chunk for {path}")
        return value

    async def _read_chunked(self, path: str, expected_size: int) -> bytes:
        """Read with offsets, checking each response against firmware metadata."""
        parts = bytearray()
        while len(parts) < expected_size:
            offset = len(parts)
            count = min(_CHUNK_SIZE, expected_size - offset)
            try:
                async with asyncio.timeout(_READ_TIMEOUT):
                    async with self._session.get(
                        self._base + "/api/fs/read/chunk",
                        params={
                            "path": path,
                            "offset": offset,
                            "max": count,
                        },
                        timeout=ClientTimeout(total=_READ_TIMEOUT - 2),
                    ) as response:
                        response.raise_for_status()
                        # Never accept a different file, offset or total.
                        if response.headers.get("X-OMOTE-Path") != path:
                            raise OmoteApiError(
                                f"Wrong chunk path for {path} at offset {offset}"
                            )
                        if self._header_int(
                            response.headers, "X-OMOTE-Offset", path
                        ) != offset:
                            raise OmoteApiError(
                                f"Unexpected chunk offset for {path}: {offset}"
                            )
                        if self._header_int(
                            response.headers, "X-OMOTE-Total", path
                        ) != expected_size:
                            raise OmoteApiError(
                                f"File size changed during chunk read: {path}"
                            )
                        declared = self._header_int(
                            response.headers, "X-OMOTE-Length", path
                        )
                        if declared != count:
                            raise OmoteApiError(
                                f"Unexpected chunk length for {path} at {offset}"
                            )
                        data = await self._read_complete(response, count)
                        if len(data) != count:
                            raise OmoteApiError(
                                f"Incomplete chunk for {path}: offset {offset}, "
                                f"expected {count}, received {len(data)}"
                            )
                        more = response.headers.get("X-OMOTE-More")
                        expected_more = "1" if offset + count < expected_size else "0"
                        if more != expected_more:
                            raise OmoteApiError(
                                f"Inconsistent continuation header for {path}"
                            )
                        parts.extend(data)
            except (ClientError, asyncio.TimeoutError) as exc:
                raise OmoteApiError(
                    f"Chunk read failed for {path} at offset {offset}: {exc}"
                ) from exc
        if len(parts) != expected_size:
            raise OmoteApiError(f"Wrong assembled length for {path}")
        return bytes(parts)

    @staticmethod
    def _decode_verified(
        data: bytes, path: str, expected_size: int, verify_json: bool
    ) -> str:
        if len(data) != expected_size:
            raise OmoteApiError(
                f"Incomplete read of {path}: received {len(data)} "
                f"of {expected_size} bytes"
            )
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise OmoteApiError(f"File {path} contains invalid UTF-8") from exc
        if verify_json:
            try:
                document = parse_jsonc(content)
            except WorkspaceError as exc:
                raise OmoteApiError(f"Invalid JSON from {path}: {exc}") from exc
            if not isinstance(document, dict):
                raise OmoteApiError(f"Expected JSON object in {path}")
        return content

    async def read_file(self, path: str, *, verify_json: bool = False) -> str:
        """Read and verify the complete file; retry using chunked reads.

        The read is not a snapshot transaction: a same-size file modification
        during transfer cannot be detected without future firmware hashes.
        """
        expected_size = await self.file_size(path)
        raw_error = None
        try:
            data = await self._read_raw(path, expected_size)
            return self._decode_verified(data, path, expected_size, verify_json)
        except OmoteApiError as exc:
            raw_error = str(exc)
            _LOGGER.warning(
                "OMOTE raw read verification failed for %s: %s; "
                "trying chunked read", path, exc
            )

        chunk_error = ""
        for attempt in range(2):
            try:
                data = await self._read_chunked(path, expected_size)
                return self._decode_verified(data, path, expected_size, verify_json)
            except OmoteApiError as exc:
                chunk_error = str(exc)
                _LOGGER.warning(
                    "OMOTE chunked read %s attempt %s failed: %s",
                    path, attempt + 1, exc,
                )
        raise OmoteApiError(
            f"Unable to safely read {path}: raw read: {raw_error}; "
            f"chunked read: {chunk_error}"
        )
