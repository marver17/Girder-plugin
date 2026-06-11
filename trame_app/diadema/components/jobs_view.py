"""
JobsView: list of the current user's Girder jobs with cancel / open-item actions.

Data comes from GET /job (user-scoped). The list refreshes when the view is
activated, on demand (refresh button) and automatically while jobs are active.
"""

from __future__ import annotations

import asyncio

from trame.widgets import html
from trame.widgets import vuetify3 as v3

from diadema.core.girder_client import DiademaGirderClient
from diadema.core.pipeline_service import PipelineService

# Girder job status codes (girder_jobs.constants.JobStatus + worker extensions)
JOB_STATUS_LABELS = {
    0: "Inactive",
    1: "Queued",
    2: "Running",
    3: "Success",
    4: "Error",
    5: "Cancelled",
    820: "Fetching input",
    821: "Converting input",
    822: "Converting output",
    823: "Pushing output",
    824: "Cancelling",
}
CANCELLABLE_CODES = [0, 1, 2, 820, 821, 822, 823]

AUTO_REFRESH_S = 5


class JobsView:
    def __init__(self, server, gc: DiademaGirderClient, service: PipelineService):
        self.state = server.state
        self.ctrl = server.controller
        self._gc = gc
        self._service = service
        self._refresh_task: asyncio.Task | None = None

        self.state.setdefault("jobs_list", [])
        self.state.setdefault("jobs_loading", False)

        self.ctrl.jobs_refresh = self._on_refresh
        self.ctrl.jobs_cancel = self._on_cancel
        self.ctrl.jobs_open_item = self._on_open_item

        server.state.change("active_view")(self._on_view_change)

    # ── Handlers ───────────────────────────────────────────────────────────

    def _on_view_change(self, active_view, **_):
        if active_view == "jobs":
            self._on_refresh()
            self._ensure_auto_refresh()
        else:
            self._stop_auto_refresh()

    def _ensure_auto_refresh(self):
        if self._refresh_task is None or self._refresh_task.done():
            self._refresh_task = asyncio.create_task(self._auto_refresh_loop())

    def _stop_auto_refresh(self):
        if self._refresh_task is not None and not self._refresh_task.done():
            self._refresh_task.cancel()
        self._refresh_task = None

    async def _auto_refresh_loop(self):
        try:
            while self.state.active_view == "jobs":
                await asyncio.sleep(AUTO_REFRESH_S)
                if any(j["statusCode"] in CANCELLABLE_CODES or j["statusCode"] == 824
                       for j in (self.state.jobs_list or [])):
                    await self._refresh_async()
        except asyncio.CancelledError:
            pass

    def _on_refresh(self):
        asyncio.create_task(self._refresh_async())

    async def _refresh_async(self):
        with self.state:
            self.state.jobs_loading = True
        try:
            jobs = await self._gc.aget(
                "job", parameters={"limit": 50, "sort": "created", "sortdir": -1}
            )
            rows = []
            for job in jobs or []:
                code = job.get("status")
                rows.append({
                    "id": str(job["_id"]),
                    "title": job.get("title", ""),
                    "type": job.get("type", ""),
                    "statusCode": code,
                    "status": JOB_STATUS_LABELS.get(code, str(code)),
                    "created": (job.get("created") or "").replace("T", " ")[:19],
                    "itemId": (job.get("otherFields") or {}).get("itemId"),
                    "tool": (job.get("otherFields") or {}).get("tool"),
                })
            with self.state:
                self.state.jobs_list = rows
        except Exception as e:
            with self.state:
                self.state.ui_error = {"message": f"Failed to load jobs: {e}"}
        finally:
            with self.state:
                self.state.jobs_loading = False

    def _on_cancel(self, row: dict):
        asyncio.create_task(self._cancel_async(row))

    async def _cancel_async(self, row: dict):
        try:
            if row.get("itemId") and row.get("tool"):
                await self._service.cancel(row["itemId"], row["tool"])
            else:
                await self._gc.aput(f"job/{row['id']}/cancel")
        except Exception as e:
            with self.state:
                self.state.ui_error = {"message": f"Failed to cancel job: {e}"}
        await self._refresh_async()

    def _on_open_item(self, item_id: str):
        if item_id and self.ctrl.on_item_selected.exists():
            self.ctrl.on_item_selected([{"_modelType": "item", "_id": item_id}])

    # ── UI ─────────────────────────────────────────────────────────────────

    def build(self):
        with v3.VCard(flat=True, classes="ma-4 flex-grow-1"):
            with v3.VCardTitle(classes="d-flex align-center"):
                v3.VIcon("mdi-cog-play", classes="mr-2", color="primary")
                html.Span("Jobs")
                v3.VSpacer()
                v3.VBtn(
                    icon="mdi-refresh",
                    variant="text",
                    size="small",
                    loading=("jobs_loading",),
                    click=self.ctrl.jobs_refresh,
                    title="Refresh",
                )

            with v3.VTable(density="comfortable", hover=True):
                with html.Thead():
                    with html.Tr():
                        for col in ("Title", "Status", "Created", "Actions"):
                            html.Th(col, classes="text-left")
                with html.Tbody():
                    with html.Tr(v_for="job in jobs_list", key="job.id"):
                        html.Td("{{ job.title }}")
                        with html.Td():
                            v3.VChip(
                                "{{ job.status }}",
                                size="x-small",
                                color=(
                                    "job.status === 'Success' ? 'success' : "
                                    "job.status === 'Error' ? 'error' : "
                                    "['Cancelled', 'Cancelling'].includes(job.status)"
                                    " ? 'grey' : 'info'",
                                ),
                            )
                        html.Td("{{ job.created }}")
                        with html.Td():
                            v3.VBtn(
                                icon="mdi-cancel",
                                variant="text",
                                size="x-small",
                                color="warning",
                                v_if=(f"{CANCELLABLE_CODES}.includes(job.statusCode)",),
                                click=(self.ctrl.jobs_cancel, "[job]"),
                                title="Cancel job",
                            )
                            v3.VBtn(
                                icon="mdi-open-in-app",
                                variant="text",
                                size="x-small",
                                v_if=("job.itemId",),
                                click=(self.ctrl.jobs_open_item, "[job.itemId]"),
                                title="Open item",
                            )

            with v3.VCardText(
                v_if=("!jobs_list.length && !jobs_loading",),
                classes="text-center text-medium-emphasis",
            ):
                html.Span("No jobs found")
