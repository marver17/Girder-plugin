"""
JobMonitor: single supervised polling loop for pipeline job status.

Design notes:
  - ONE asyncio.Task for all tracked jobs (started lazily on first track(),
    cancelled when nothing is left to watch) — this avoids the
    timer-per-job leak pattern of the legacy jQuery panel.
  - Source of truth is the same one the workers write to:
    item.diadema.{tool}.status (or folder metadata for session scope),
    fetched via GET /diadema_pipeline/{id}/results.
  - Terminal statuses stop tracking; a hard cap marks the entry "stale"
    so the UI can offer the Reset action.
  - Logout (girder_token → None) cancels the loop and clears tracked jobs.
"""

from __future__ import annotations

import asyncio
import time

from diadema.core.girder_client import DiademaGirderClient

POLL_INTERVAL_S = 3
# Statuses written by the workers / REST layer into item.diadema.{tool}.status
ACTIVE_STATUSES = {"queued", "running", "processing", "uploading", "cancelling"}
TERMINAL_STATUSES = {"completed", "error", "cancelled"}
# Give up polling after this long without reaching a terminal status
MAX_TRACK_SECONDS = 6 * 3600


class JobMonitor:
    def __init__(self, server, gc: DiademaGirderClient):
        self.state = server.state
        self._gc = gc
        # key "{scope}:{id}:{tool}" -> {"scope", "id", "tool", "started": epoch}
        self._tracked: dict[str, dict] = {}
        self._task: asyncio.Task | None = None

        server.state.change("girder_token")(self._on_token_change)

    # ── Public API ─────────────────────────────────────────────────────────

    def track(self, resource_id: str, tool_id: str, scope: str = "item"):
        """Start watching a job. Safe to call repeatedly (idempotent)."""
        key = f"{scope}:{resource_id}:{tool_id}"
        if key not in self._tracked:
            self._tracked[key] = {
                "scope": scope,
                "id": resource_id,
                "tool": tool_id,
                "started": time.time(),
            }
        self._ensure_loop()

    def track_from_item(self, item: dict):
        """Resume tracking for any non-terminal tool status persisted on an item."""
        diadema = item.get("diadema") or {}
        for tool_id, info in diadema.items():
            if isinstance(info, dict) and info.get("status") in ACTIVE_STATUSES:
                self.track(str(item["_id"]), tool_id, scope="item")

    def untrack_all(self):
        self._tracked.clear()
        self._stop_loop()
        with self.state:
            self.state.pipeline_jobs = {}

    # ── Internals ──────────────────────────────────────────────────────────

    def _on_token_change(self, girder_token, **_):
        if not girder_token:
            self.untrack_all()

    def _ensure_loop(self):
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    def _stop_loop(self):
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None

    async def _loop(self):
        try:
            while self._tracked:
                await self._poll_once()
                await asyncio.sleep(POLL_INTERVAL_S)
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    async def _poll_once(self):
        for key, entry in list(self._tracked.items()):
            try:
                if entry["scope"] == "session":
                    doc = await self._gc.aget(
                        f"diadema_pipeline/session/{entry['id']}/results"
                    )
                else:
                    doc = await self._gc.aget(
                        f"diadema_pipeline/{entry['id']}/results"
                    )
            except Exception as e:
                print(f"[job_monitor] Poll failed for {key}: {e}")
                continue

            diadema = (doc or {}).get("diadema") or {}
            info = diadema.get(entry["tool"]) or {}
            status = info.get("status")

            stale = (time.time() - entry["started"]) > MAX_TRACK_SECONDS
            job_entry = {
                "status": "stale" if (stale and status in ACTIVE_STATUSES) else status,
                "scope": entry["scope"],
                "tool": entry["tool"],
                "resource_id": entry["id"],
                "job_id": info.get("job_id"),
                "progress_msg": info.get("message") or info.get("progress"),
                "error": (info.get("error") or {}).get("message")
                if isinstance(info.get("error"), dict)
                else info.get("error"),
                "updated": time.time(),
            }

            with self.state:
                jobs = dict(self.state.pipeline_jobs or {})
                jobs[key] = job_entry
                self.state.pipeline_jobs = jobs
                # Keep the open item view in sync with fresh diadema metadata
                if (
                    entry["scope"] == "item"
                    and self.state.current_item_id == entry["id"]
                    and doc
                ):
                    self.state.current_item = doc

            if status in TERMINAL_STATUSES or stale or status is None:
                self._tracked.pop(key, None)
