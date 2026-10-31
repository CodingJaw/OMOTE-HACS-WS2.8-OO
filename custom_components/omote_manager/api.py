"""HTTP client for the existing OMOTE firmware configuration API.

No firmware writes are implemented in this first release.
"""
from __future__ import annotations

import asyncio
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import MAX_BACKUP_FILE_BYTES, SUPPORTED_API


class OmoteApiError(Exception):
    """Raised when an OMOTE API request cannot be completed."""


class OmoteApi:
    """Transport for the firmware's omote-config-v1 endpoints."""

    def __init__(self, session: ClientSession, host: str, port: int = 80) -> None:
        self._session = session
        self._base = f"http://{host}:{port}"

    async def _json(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
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

    async def read_file(self, path: str) -> str:
        """Read one file; reject unsafe paths and oversized files.

        The raw endpoint streams, unlike the memory-hungry JSON wrapper.
        """
        if not path or path.startswith("/") or ".." in path or "\\" in path:
            raise OmoteApiError("Unsafe filesystem path")
        try:
            async with asyncio.timeout(30):
                async with self._session.get(
                    self._base + "/api/fs/read/raw",
                    params={"path": path},
                    timeout=ClientTimeout(total=27),
                ) as response:
                    response.raise_for_status()
                    data = await response.content.read(MAX_BACKUP_FILE_BYTES + 1)
        except (ClientError, asyncio.TimeoutError) as exc:
            raise OmoteApiError(f"Cannot read {path}: {exc}") from exc
        if len(data) > MAX_BACKUP_FILE_BYTES:
            raise OmoteApiError(f"File {path} exceeds backup size limit")
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise OmoteApiError(f"Non-text content in {path}") from exc
