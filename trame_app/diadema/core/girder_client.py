"""
Thin wrapper around girder_client.GirderClient.

A single instance is maintained per Trame server session.
It is re-initialized whenever the auth token changes (login/logout).
"""

import asyncio

import girder_client

from diadema.config import GIRDER_API_URL


class DiademaGirderClient:
    """Wrapper that holds a girder_client.GirderClient instance."""

    def __init__(self):
        self._gc = girder_client.GirderClient(apiUrl=GIRDER_API_URL)

    def set_token(self, token: str | None) -> None:
        """Update the auth token used for all subsequent requests."""
        self._gc.token = token or ""

    def get(self, path: str, parameters: dict | None = None):
        return self._gc.get(path, parameters=parameters)

    def post(self, path: str, parameters: dict | None = None, data=None, json=None):
        return self._gc.post(path, parameters=parameters, data=data, json=json)

    def put(self, path: str, parameters: dict | None = None, data=None, json=None):
        return self._gc.put(path, parameters=parameters, data=data, json=json)

    def delete(self, path: str, parameters: dict | None = None):
        return self._gc.delete(path, parameters=parameters)

    def download_file(self, file_id: str, dest_path: str) -> None:
        self._gc.downloadFile(file_id, dest_path)

    # ── Async variants ─────────────────────────────────────────────────────
    # girder_client is synchronous; these delegate to a worker thread so the
    # Trame asyncio event loop never blocks on network I/O.

    async def aget(self, path: str, parameters: dict | None = None):
        return await asyncio.to_thread(self._gc.get, path, parameters=parameters)

    async def apost(self, path: str, parameters: dict | None = None, data=None, json=None):
        return await asyncio.to_thread(
            self._gc.post, path, parameters=parameters, data=data, json=json
        )

    async def aput(self, path: str, parameters: dict | None = None, data=None, json=None):
        return await asyncio.to_thread(
            self._gc.put, path, parameters=parameters, data=data, json=json
        )

    async def adelete(self, path: str, parameters: dict | None = None):
        return await asyncio.to_thread(self._gc.delete, path, parameters=parameters)

    async def adownload_file(self, file_id: str, dest_path: str) -> None:
        await asyncio.to_thread(self._gc.downloadFile, file_id, dest_path)

    @property
    def raw(self) -> girder_client.GirderClient:
        """Direct access to the underlying GirderClient (e.g. for FileFetcher)."""
        return self._gc
