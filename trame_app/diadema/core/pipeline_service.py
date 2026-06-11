"""
PipelineService: async facade over the diadema_pipeline REST endpoints.

All methods are coroutine-safe (they delegate to girder_client through
asyncio.to_thread via DiademaGirderClient async helpers) and route every
failure through a single error boundary that surfaces problems in the UI
(state.ui_error snackbar) instead of crashing the Trame server.

HTTP 409 (job already running) is special-cased: it populates
state.pipeline_conflict so the panel can offer a "Force re-run" dialog.
"""

from __future__ import annotations

import girder_client

from diadema.core.girder_client import DiademaGirderClient


class PipelineService:
    def __init__(self, server, gc: DiademaGirderClient):
        self.state = server.state
        self._gc = gc

    # ── Error boundary ─────────────────────────────────────────────────────

    async def _call(self, coro, *, conflict_ctx: dict | None = None):
        try:
            return await coro
        except girder_client.HttpError as e:
            if e.status == 409 and conflict_ctx is not None:
                with self.state:
                    self.state.pipeline_conflict = conflict_ctx
                return None
            message = e.responseText or str(e)
            with self.state:
                self.state.ui_error = {"message": message, "status": e.status}
            return None
        except Exception as e:  # network down, timeout, etc.
            with self.state:
                self.state.ui_error = {"message": str(e), "status": None}
            return None

    # ── Item-scope operations ──────────────────────────────────────────────

    async def run_tool(self, item_id: str, tool_id: str, params: dict | None = None):
        """POST /diadema_pipeline/{id}/run/{toolId}. Returns the job dict or None."""
        return await self._call(
            self._gc.apost(
                f"diadema_pipeline/{item_id}/run/{tool_id}",
                parameters=params or {},
            ),
            conflict_ctx={"scope": "item", "id": item_id, "tool_id": tool_id,
                          "params": params or {}},
        )

    async def cancel(self, item_id: str, tool_id: str):
        return await self._call(
            self._gc.apost(f"diadema_pipeline/{item_id}/cancel/{tool_id}")
        )

    async def reset(self, item_id: str, tool_id: str):
        return await self._call(
            self._gc.apost(f"diadema_pipeline/{item_id}/reset/{tool_id}")
        )

    async def delete_results(self, item_id: str, tool_id: str):
        return await self._call(
            self._gc.adelete(f"diadema_pipeline/{item_id}/results/{tool_id}")
        )

    async def get_results(self, item_id: str):
        """GET /diadema_pipeline/{id}/results → item dict (read item['diadema'])."""
        return await self._call(self._gc.aget(f"diadema_pipeline/{item_id}/results"))

    async def preview_participant_label(self, item_id: str, hint: str = ""):
        return await self._call(
            self._gc.aget(
                f"diadema_pipeline/{item_id}/participant_label",
                parameters={"hint": hint} if hint else None,
            )
        )

    # ── Session-scope operations (BIDS ses-XX folder) ──────────────────────

    async def run_session_tool(self, folder_id: str, tool_id: str, params: dict | None = None):
        return await self._call(
            self._gc.apost(
                f"diadema_pipeline/session/{folder_id}/run/{tool_id}",
                parameters=params or {},
            ),
            conflict_ctx={"scope": "session", "id": folder_id, "tool_id": tool_id,
                          "params": params or {}},
        )

    async def cancel_session(self, folder_id: str, tool_id: str):
        return await self._call(
            self._gc.apost(f"diadema_pipeline/session/{folder_id}/cancel/{tool_id}")
        )

    async def reset_session(self, folder_id: str, tool_id: str):
        return await self._call(
            self._gc.apost(f"diadema_pipeline/session/{folder_id}/reset/{tool_id}")
        )

    async def get_session_results(self, folder_id: str):
        return await self._call(
            self._gc.aget(f"diadema_pipeline/session/{folder_id}/results")
        )

    async def get_session_files(self, folder_id: str):
        return await self._call(
            self._gc.aget(f"diadema_pipeline/session/{folder_id}/files")
        )
