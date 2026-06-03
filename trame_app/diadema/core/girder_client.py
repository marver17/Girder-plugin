"""
Thin wrapper around girder_client.GirderClient.

A single instance is maintained per Trame server session.
It is re-initialized whenever the auth token changes (login/logout).
"""

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

    @property
    def raw(self) -> girder_client.GirderClient:
        """Direct access to the underlying GirderClient (e.g. for FileFetcher)."""
        return self._gc
