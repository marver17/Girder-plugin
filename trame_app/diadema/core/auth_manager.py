"""
Auth manager: bridges GirderProvider (JS side) token with the Python-side GirderClient.

GirderProvider (trame-gwc) manages the browser auth flow. When the user logs in,
the token is synced to Trame state as `girder_token`. This module watches that
state key and re-initializes the GirderClient accordingly.
"""

from trame.app import get_server

from diadema.core.girder_client import DiademaGirderClient


class AuthManager:
    """
    Subscribes to Trame state changes on `girder_token` and `girder_user`,
    and keeps the Python-side GirderClient in sync.
    """

    def __init__(self, server, gc: DiademaGirderClient):
        self._server = server
        self._gc = gc
        self._state = server.state

        # React to token changes coming from GirderProvider on the JS side
        self._state.change("girder_token")(self._on_token_change)

    def _on_token_change(self, girder_token, **kwargs):
        self._gc.set_token(girder_token)
        if girder_token:
            print(f"[auth] Token set — user authenticated")
        else:
            print("[auth] Token cleared — user logged out")

    @property
    def is_authenticated(self) -> bool:
        return bool(self._state.girder_token)
