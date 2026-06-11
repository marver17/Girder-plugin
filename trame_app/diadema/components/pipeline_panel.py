"""
PipelinePanel: launch / monitor / cancel DIADEMA pipelines from the Trame UI.

One expansion card per tool (MRIQC, FreeSurfer, LST-AI) with a status chip,
tool-specific parameters and Run / Cancel / Reset / Delete actions.

Scope handling (state.pipeline_scope, set by FileBrowserPanel):
  - "item"             → POST /diadema_pipeline/{itemId}/run/{tool}
  - "session" (ses-XX) → POST /diadema_pipeline/session/{folderId}/run/{tool}
  - "subject"/"dataset"→ sequential submission over pipeline_target_ids
                         (Celery queues do the real throttling)

A global "force re-run" dialog handles HTTP 409 conflicts surfaced by
PipelineService through state.pipeline_conflict.
"""

from __future__ import annotations

import asyncio

from trame.widgets import html
from trame.widgets import vuetify3 as v3

from diadema.core.girder_client import DiademaGirderClient
from diadema.core.job_monitor import ACTIVE_STATUSES, JobMonitor
from diadema.core.pipeline_service import PipelineService

TOOLS = [
    {"id": "mriqc", "label": "MRIQC", "icon": "mdi-magnify-scan",
     "description": "MRI quality control metrics and reports"},
    {"id": "freesurfer", "label": "FreeSurfer", "icon": "mdi-brain",
     "description": "Cortical reconstruction (recon-all)"},
    {"id": "lstai", "label": "LST-AI", "icon": "mdi-chart-bubble",
     "description": "White-matter lesion segmentation"},
]

# Defaults mirror the REST endpoint defaults in diadema_pipeline/rest.py
DEFAULT_PARAMS = {
    "mriqc": {"modality": "T1w", "timeout": 1800},
    "freesurfer": {
        "directive": "-all",
        "hemi": "both",
        "openmpThreads": 4,
        "mprage": False,
        "wsatlas": False,
        "deface": False,
        "fsTimeout": 14400,
    },
    "lstai": {"inputType": "T1+FLAIR", "threshold": 0.5, "useGpu": True},
}

CANCELLABLE = ("queued", "running", "processing", "uploading")


class PipelinePanel:
    def __init__(self, server, gc: DiademaGirderClient,
                 service: PipelineService, monitor: JobMonitor):
        self.state = server.state
        self.ctrl = server.controller
        self._gc = gc
        self._service = service
        self._monitor = monitor

        self.state.setdefault("pipeline_params", DEFAULT_PARAMS)
        self.state.setdefault("pipeline_status", {})
        self.state.setdefault("pipeline_busy", {})
        self.state.setdefault("pipeline_conflict", None)

        self.ctrl.pipeline_run = self._on_run
        self.ctrl.pipeline_cancel = self._on_cancel
        self.ctrl.pipeline_reset = self._on_reset
        self.ctrl.pipeline_delete_results = self._on_delete_results
        self.ctrl.pipeline_force_run = self._on_force_run
        self.ctrl.on_item_loaded = self._on_item_loaded

        server.state.change("current_item", "pipeline_jobs")(self._refresh_status)

    # ── Status derivation ──────────────────────────────────────────────────

    def _refresh_status(self, **_):
        """Derive {tool: status} for the open resource from live polling data
        (pipeline_jobs) falling back to the persisted item metadata."""
        item = self.state.current_item or {}
        item_id = self.state.current_item_id
        diadema = item.get("diadema") or {}
        jobs = self.state.pipeline_jobs or {}

        status = {}
        for tool in DEFAULT_PARAMS:
            live = None
            if item_id:
                for scope in ("item", "session"):
                    entry = jobs.get(f"{scope}:{item_id}:{tool}")
                    if entry:
                        live = entry.get("status")
            persisted = (diadema.get(tool) or {}).get("status")
            status[tool] = live or persisted
        self.state.pipeline_status = status

    def _on_item_loaded(self, item: dict):
        """Resume tracking of in-flight jobs when an item is (re)opened."""
        self._monitor.track_from_item(item)
        self._refresh_status()

    # ── Target resolution ──────────────────────────────────────────────────

    def _current_target(self) -> tuple[str, str | None]:
        """Return (scope, resource_id) for the active selection."""
        scope = self.state.pipeline_scope or "item"
        if scope == "item":
            return "item", self.state.current_item_id
        targets = self.state.pipeline_target_ids or []
        return scope, (targets[0] if targets else None)

    def _set_busy(self, tool_id: str, busy: bool):
        with self.state:
            flags = dict(self.state.pipeline_busy or {})
            flags[tool_id] = busy
            self.state.pipeline_busy = flags

    # ── Actions ────────────────────────────────────────────────────────────

    def _on_run(self, tool_id: str, force: bool = False):
        asyncio.create_task(self._run_async(tool_id, force=force))

    async def _run_async(self, tool_id: str, force: bool = False):
        scope, resource_id = self._current_target()
        params = dict((self.state.pipeline_params or {}).get(tool_id) or {})
        if force:
            params["force"] = True
        self._set_busy(tool_id, True)
        try:
            if scope == "session" and resource_id:
                result = await self._service.run_session_tool(resource_id, tool_id, params)
                if result is not None:
                    self._monitor.track(resource_id, tool_id, scope="session")
            elif scope in ("subject", "dataset"):
                for item_id in self.state.pipeline_target_ids or []:
                    result = await self._service.run_tool(item_id, tool_id, params)
                    if result is not None:
                        self._monitor.track(item_id, tool_id, scope="item")
            elif resource_id:
                result = await self._service.run_tool(resource_id, tool_id, params)
                if result is not None:
                    self._monitor.track(resource_id, tool_id, scope="item")
        finally:
            self._set_busy(tool_id, False)

    def _on_force_run(self):
        conflict = self.state.pipeline_conflict
        if not conflict:
            return
        with self.state:
            self.state.pipeline_conflict = None
        params = dict(conflict.get("params") or {})
        params["force"] = True

        async def _force():
            if conflict["scope"] == "session":
                result = await self._service.run_session_tool(
                    conflict["id"], conflict["tool_id"], params)
                if result is not None:
                    self._monitor.track(conflict["id"], conflict["tool_id"], scope="session")
            else:
                result = await self._service.run_tool(
                    conflict["id"], conflict["tool_id"], params)
                if result is not None:
                    self._monitor.track(conflict["id"], conflict["tool_id"], scope="item")

        asyncio.create_task(_force())

    def _on_cancel(self, tool_id: str):
        asyncio.create_task(self._cancel_async(tool_id))

    async def _cancel_async(self, tool_id: str):
        scope, resource_id = self._current_target()
        if not resource_id:
            return
        if scope == "session":
            await self._service.cancel_session(resource_id, tool_id)
        else:
            await self._service.cancel(resource_id, tool_id)
        self._monitor.track(resource_id, tool_id,
                            scope="session" if scope == "session" else "item")

    def _on_reset(self, tool_id: str):
        asyncio.create_task(self._reset_async(tool_id))

    async def _reset_async(self, tool_id: str):
        scope, resource_id = self._current_target()
        if not resource_id:
            return
        if scope == "session":
            await self._service.reset_session(resource_id, tool_id)
        else:
            await self._service.reset(resource_id, tool_id)
        await self._refresh_results(resource_id, scope)

    def _on_delete_results(self, tool_id: str):
        asyncio.create_task(self._delete_results_async(tool_id))

    async def _delete_results_async(self, tool_id: str):
        scope, resource_id = self._current_target()
        if not resource_id or scope == "session":
            return
        await self._service.delete_results(resource_id, tool_id)
        await self._refresh_results(resource_id, scope)

    async def _refresh_results(self, resource_id: str, scope: str):
        doc = (await self._service.get_session_results(resource_id)
               if scope == "session"
               else await self._service.get_results(resource_id))
        if doc and scope != "session":
            with self.state:
                self.state.current_item = doc

    # ── UI ─────────────────────────────────────────────────────────────────

    def build(self):
        with v3.VCard(flat=True, classes="ma-2"):
            with v3.VCardTitle(classes="d-flex align-center text-subtitle-1"):
                v3.VIcon("mdi-pipe", classes="mr-2", color="primary")
                html.Span("DIADEMA Pipelines")
                v3.VSpacer()
                v3.VChip(
                    "{{ pipeline_scope_label }}",
                    v_if=("pipeline_scope_label",),
                    size="small",
                    variant="tonal",
                    color="primary",
                )

            with v3.VExpansionPanels(variant="accordion", multiple=True):
                for tool in TOOLS:
                    self._build_tool_panel(tool)

    def _build_tool_panel(self, tool: dict):
        tid = tool["id"]
        status_expr = f"pipeline_status['{tid}']"
        busy_expr = f"pipeline_busy['{tid}']"
        active = list(ACTIVE_STATUSES)

        with v3.VExpansionPanel():
            with v3.VExpansionPanelTitle():
                v3.VIcon(tool["icon"], classes="mr-2")
                html.Span(tool["label"], classes="font-weight-medium mr-2")
                v3.VChip(
                    f"{{{{ {status_expr} }}}}",
                    v_if=(status_expr,),
                    size="x-small",
                    classes="ml-1",
                    color=(
                        f"{status_expr} === 'completed' ? 'success' : "
                        f"{status_expr} === 'error' ? 'error' : "
                        f"{status_expr} === 'stale' ? 'warning' : "
                        f"['cancelled'].includes({status_expr}) ? 'grey' : 'info'",
                    ),
                )
            with v3.VExpansionPanelText():
                html.P(tool["description"], classes="text-caption text-medium-emphasis mb-2")
                self._build_params(tid)

                with v3.VCardActions(classes="px-0"):
                    v3.VBtn(
                        "Run",
                        prepend_icon="mdi-play",
                        color="primary",
                        variant="flat",
                        size="small",
                        loading=(busy_expr,),
                        disabled=(f"{str(active)}.includes({status_expr})",),
                        click=(self.ctrl.pipeline_run, f"['{tid}']"),
                    )
                    v3.VBtn(
                        "Cancel",
                        prepend_icon="mdi-cancel",
                        color="warning",
                        variant="text",
                        size="small",
                        v_if=(f"{list(CANCELLABLE)}.includes({status_expr})",),
                        click=(self.ctrl.pipeline_cancel, f"['{tid}']"),
                    )
                    v3.VBtn(
                        "Reset",
                        prepend_icon="mdi-restore",
                        variant="text",
                        size="small",
                        v_if=(f"['cancelling', 'stale'].includes({status_expr})",),
                        click=(self.ctrl.pipeline_reset, f"['{tid}']"),
                    )
                    v3.VBtn(
                        "Delete results",
                        prepend_icon="mdi-delete-outline",
                        color="error",
                        variant="text",
                        size="small",
                        v_if=(
                            f"['completed', 'error', 'cancelled'].includes({status_expr})"
                            " && pipeline_scope === 'item'",
                        ),
                        click=(self.ctrl.pipeline_delete_results, f"['{tid}']"),
                    )

    def _build_params(self, tool_id: str):
        if tool_id == "mriqc":
            with v3.VRow(dense=True):
                with v3.VCol(cols=6):
                    v3.VSelect(
                        label="Modality",
                        items=(["T1w", "T2w", "bold", "dwi"],),
                        v_model=("pipeline_params.mriqc.modality",),
                        density="compact",
                        hide_details=True,
                    )
                with v3.VCol(cols=6):
                    v3.VTextField(
                        label="Timeout (s)",
                        type="number",
                        v_model_number=("pipeline_params.mriqc.timeout",),
                        density="compact",
                        hide_details=True,
                    )
        elif tool_id == "freesurfer":
            with v3.VRow(dense=True):
                with v3.VCol(cols=6):
                    v3.VSelect(
                        label="Directive",
                        items=(["-all", "-autorecon1", "-autorecon2",
                                "-autorecon3", "-autorecon2-cp", "-autorecon2-wm"],),
                        v_model=("pipeline_params.freesurfer.directive",),
                        density="compact",
                        hide_details=True,
                    )
                with v3.VCol(cols=6):
                    v3.VSelect(
                        label="Hemisphere",
                        items=(["both", "lh", "rh"],),
                        v_model=("pipeline_params.freesurfer.hemi",),
                        density="compact",
                        hide_details=True,
                    )
                with v3.VCol(cols=6):
                    v3.VTextField(
                        label="OpenMP threads",
                        type="number",
                        v_model_number=("pipeline_params.freesurfer.openmpThreads",),
                        density="compact",
                        hide_details=True,
                    )
                with v3.VCol(cols=6):
                    v3.VTextField(
                        label="Timeout (s)",
                        type="number",
                        v_model_number=("pipeline_params.freesurfer.fsTimeout",),
                        density="compact",
                        hide_details=True,
                    )
            with v3.VRow(dense=True, classes="mt-1"):
                with v3.VCol(cols=4):
                    v3.VSwitch(
                        label="MP-RAGE",
                        v_model=("pipeline_params.freesurfer.mprage",),
                        density="compact",
                        hide_details=True,
                        color="primary",
                    )
                with v3.VCol(cols=4):
                    v3.VSwitch(
                        label="WS atlas",
                        v_model=("pipeline_params.freesurfer.wsatlas",),
                        density="compact",
                        hide_details=True,
                        color="primary",
                    )
                with v3.VCol(cols=4):
                    v3.VSwitch(
                        label="Deface",
                        v_model=("pipeline_params.freesurfer.deface",),
                        density="compact",
                        hide_details=True,
                        color="primary",
                    )
        elif tool_id == "lstai":
            with v3.VRow(dense=True):
                with v3.VCol(cols=6):
                    v3.VSelect(
                        label="Input type",
                        items=(["T1+FLAIR", "T1 only"],),
                        v_model=("pipeline_params.lstai.inputType",),
                        density="compact",
                        hide_details=True,
                    )
                with v3.VCol(cols=6):
                    v3.VSwitch(
                        label="Use GPU",
                        v_model=("pipeline_params.lstai.useGpu",),
                        density="compact",
                        hide_details=True,
                        color="primary",
                    )
                with v3.VCol(cols=12):
                    v3.VSlider(
                        label="Lesion threshold",
                        min=0.0,
                        max=1.0,
                        step=0.05,
                        thumb_label=True,
                        v_model=("pipeline_params.lstai.threshold",),
                        density="compact",
                        hide_details=True,
                    )

    def build_force_dialog(self):
        """Global 409-conflict dialog; mount ONCE at app level (the panel
        itself may be rendered in multiple views)."""
        with v3.VDialog(
            model_value=("pipeline_conflict !== null",),
            persistent=True,
            max_width=440,
        ):
            with v3.VCard():
                with v3.VCardTitle(classes="text-subtitle-1"):
                    v3.VIcon("mdi-alert", classes="mr-2", color="warning")
                    html.Span("Job already running")
                v3.VCardText(
                    "A job for this tool is already running or queued on this "
                    "resource. Force a re-run anyway?"
                )
                with v3.VCardActions():
                    v3.VSpacer()
                    v3.VBtn(
                        "Close",
                        variant="text",
                        click="pipeline_conflict = null",
                    )
                    v3.VBtn(
                        "Force re-run",
                        color="warning",
                        variant="flat",
                        click=self.ctrl.pipeline_force_run,
                    )
