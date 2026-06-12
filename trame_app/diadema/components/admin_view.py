"""
AdminView: edit DIADEMA plugin settings and link out to the Girder admin UI.

Settings are read/written through the existing plugin endpoints
(GET/PUT /diadema_pipeline/settings); the PUT is admin-only server-side, so
non-admin users see a read-only form plus the "Open Girder Admin" button.

Form fields use flat top-level state keys (admin_*) rather than a nested dict:
trame's dirty-tracking and change events are reliable on top-level keys, so the
server always reads the latest values on save and the "Saved" chip resets as
soon as a field is edited. The Girder settings model is recomposed on save:
  - diadema.widget_enabled  (dict)  ⇄ three switches
  - diadema.widget_fields_* (list)  ⇄ textarea, one metric per line
"""

from __future__ import annotations

import asyncio

from trame.widgets import html
from trame.widgets import vuetify3 as v3

from diadema.config import GIRDER_ADMIN_URL
from diadema.core.girder_client import DiademaGirderClient
from diadema.core.pipeline_service import PipelineService

# Setting keys (mirror PluginSettings in girder_diadema_pipeline/settings.py)
K_STORAGE = "diadema.output_storage"
K_MRIQC_DIR = "diadema.mriqc_output_dir"
K_SUBJECTS_DIR = "diadema.subjects_dir"
K_LSTAI_DIR = "diadema.lstai_output_dir"
K_WIDGET_ENABLED = "diadema.widget_enabled"
K_FIELDS_MRIQC = "diadema.widget_fields_mriqc"
K_FIELDS_FREESURFER = "diadema.widget_fields_freesurfer"

# Flat state keys bound to the form fields
FORM_KEYS = [
    "admin_storage",
    "admin_mriqc_dir",
    "admin_subjects_dir",
    "admin_lstai_dir",
    "admin_enabled_mriqc",
    "admin_enabled_freesurfer",
    "admin_enabled_lstai",
    "admin_fields_mriqc",
    "admin_fields_freesurfer",
]

ADMIN_ONLY = "!girder_user || !girder_user.admin"


class AdminView:
    def __init__(self, server, gc: DiademaGirderClient, service: PipelineService):
        self.state = server.state
        self.ctrl = server.controller
        self._gc = gc
        self._service = service

        defaults = {
            "admin_storage": "item",
            "admin_mriqc_dir": "",
            "admin_subjects_dir": "",
            "admin_lstai_dir": "",
            "admin_enabled_mriqc": True,
            "admin_enabled_freesurfer": True,
            "admin_enabled_lstai": False,
            "admin_fields_mriqc": "",
            "admin_fields_freesurfer": "",
            "admin_loading": False,
            "admin_saving": False,
            "admin_saved": False,
            "girder_admin_url": GIRDER_ADMIN_URL,
        }
        for key, value in defaults.items():
            self.state.setdefault(key, value)

        self.ctrl.admin_load = self._on_load
        self.ctrl.admin_save = self._on_save

        server.state.change("active_view")(self._on_view_change)
        # Reset the "Saved" confirmation as soon as any field is edited
        server.state.change(*FORM_KEYS)(self._on_edit)

    # ── Load ───────────────────────────────────────────────────────────────

    def _on_view_change(self, active_view, **_):
        if active_view == "admin":
            self._on_load()

    def _on_load(self):
        asyncio.create_task(self._load_async())

    async def _load_async(self):
        with self.state:
            self.state.admin_loading = True
        settings = await self._service.get_settings()
        if settings is None:
            with self.state:
                self.state.admin_loading = False
            return
        enabled = settings.get(K_WIDGET_ENABLED) or {}
        with self.state:
            self.state.admin_storage = settings.get(K_STORAGE) or "item"
            self.state.admin_mriqc_dir = settings.get(K_MRIQC_DIR) or ""
            self.state.admin_subjects_dir = settings.get(K_SUBJECTS_DIR) or ""
            self.state.admin_lstai_dir = settings.get(K_LSTAI_DIR) or ""
            self.state.admin_enabled_mriqc = bool(enabled.get("mriqc", True))
            self.state.admin_enabled_freesurfer = bool(enabled.get("freesurfer", True))
            self.state.admin_enabled_lstai = bool(enabled.get("lstai", False))
            self.state.admin_fields_mriqc = "\n".join(settings.get(K_FIELDS_MRIQC) or [])
            self.state.admin_fields_freesurfer = "\n".join(
                settings.get(K_FIELDS_FREESURFER) or []
            )
            self.state.admin_loading = False
            self.state.admin_saved = False

    # ── Edit / Save ────────────────────────────────────────────────────────

    def _on_edit(self, **_):
        if self.state.admin_saved:
            self.state.admin_saved = False

    def _on_save(self):
        asyncio.create_task(self._save_async())

    async def _save_async(self):
        payload = {
            K_STORAGE: self.state.admin_storage or "item",
            K_MRIQC_DIR: self.state.admin_mriqc_dir or "",
            K_SUBJECTS_DIR: self.state.admin_subjects_dir or "",
            K_LSTAI_DIR: self.state.admin_lstai_dir or "",
            K_WIDGET_ENABLED: {
                "mriqc": bool(self.state.admin_enabled_mriqc),
                "freesurfer": bool(self.state.admin_enabled_freesurfer),
                "lstai": bool(self.state.admin_enabled_lstai),
            },
            K_FIELDS_MRIQC: _lines(self.state.admin_fields_mriqc),
            K_FIELDS_FREESURFER: _lines(self.state.admin_fields_freesurfer),
        }
        with self.state:
            self.state.admin_saving = True
        result = await self._service.update_settings(payload)
        with self.state:
            self.state.admin_saving = False
            self.state.admin_saved = result is not None
        if result is not None:
            await self._load_async()

    # ── UI ─────────────────────────────────────────────────────────────────

    def build(self):
        with v3.VCard(flat=True, classes="ma-4", max_width=720):
            with v3.VCardTitle(classes="d-flex align-center"):
                v3.VIcon("mdi-shield-account", classes="mr-2", color="primary")
                html.Span("Administration")
                v3.VSpacer()
                v3.VProgressCircular(
                    indeterminate=True, size=20, v_if=("admin_loading",)
                )

            with v3.VCardText():
                # Read-only notice for non-admins
                with v3.VAlert(
                    v_if=(ADMIN_ONLY,),
                    type="info",
                    variant="tonal",
                    density="compact",
                    classes="mb-4",
                ):
                    html.Span(
                        "You are viewing the configuration in read-only mode. "
                        "Administrator privileges are required to change it."
                    )

                # ── Storage & output directories ──────────────────────────
                html.P("Storage & output directories",
                        classes="text-subtitle-2 font-weight-medium mb-1")
                v3.VSelect(
                    label="Result storage",
                    items=(["item", "derivatives"],),
                    v_model=("admin_storage",),
                    disabled=(ADMIN_ONLY,),
                    density="compact",
                )
                v3.VTextField(
                    label="MRIQC output directory",
                    v_model=("admin_mriqc_dir",),
                    placeholder="$DIADEMA_MRIQC_OUTPUT_DIR or /data/diadema/mriqc",
                    disabled=(ADMIN_ONLY,),
                    density="compact",
                )
                v3.VTextField(
                    label="FreeSurfer SUBJECTS_DIR",
                    v_model=("admin_subjects_dir",),
                    placeholder="$DIADEMA_SUBJECTS_DIR or /data/diadema/subjects",
                    disabled=(ADMIN_ONLY,),
                    density="compact",
                )
                v3.VTextField(
                    label="LST-AI output directory",
                    v_model=("admin_lstai_dir",),
                    placeholder="$DIADEMA_LSTAI_OUTPUT_DIR or /data/diadema/lstai",
                    disabled=(ADMIN_ONLY,),
                    density="compact",
                )

                v3.VDivider(classes="my-3")

                # ── Tool visibility ───────────────────────────────────────
                html.P("Tool visibility",
                        classes="text-subtitle-2 font-weight-medium mb-1")
                with v3.VRow(dense=True):
                    for tool, key in (("MRIQC", "admin_enabled_mriqc"),
                                      ("FreeSurfer", "admin_enabled_freesurfer"),
                                      ("LST-AI", "admin_enabled_lstai")):
                        with v3.VCol(cols=4):
                            v3.VSwitch(
                                label=tool,
                                v_model=(key,),
                                disabled=(ADMIN_ONLY,),
                                color="primary",
                                density="compact",
                                hide_details=True,
                            )

                v3.VDivider(classes="my-3")

                # ── Widget fields ─────────────────────────────────────────
                html.P("Widget fields (one metric per line)",
                        classes="text-subtitle-2 font-weight-medium mb-1")
                v3.VTextarea(
                    label="MRIQC IQM metrics",
                    v_model=("admin_fields_mriqc",),
                    rows=4,
                    auto_grow=True,
                    disabled=(ADMIN_ONLY,),
                    density="compact",
                )
                v3.VTextarea(
                    label="FreeSurfer stats keys",
                    v_model=("admin_fields_freesurfer",),
                    rows=4,
                    auto_grow=True,
                    disabled=(ADMIN_ONLY,),
                    density="compact",
                )

            with v3.VCardActions(classes="px-4 pb-4"):
                v3.VBtn(
                    "Open Girder Admin",
                    prepend_icon="mdi-open-in-new",
                    variant="text",
                    href=("girder_admin_url + '/#plugins/diadema_pipeline/config'",),
                    target="_blank",
                )
                v3.VSpacer()
                v3.VChip(
                    "Saved",
                    v_if=("admin_saved",),
                    color="success",
                    size="small",
                    variant="tonal",
                    prepend_icon="mdi-check",
                    classes="mr-2",
                )
                v3.VBtn(
                    "Save",
                    prepend_icon="mdi-content-save",
                    color="primary",
                    variant="flat",
                    loading=("admin_saving",),
                    v_if=("girder_user && girder_user.admin",),
                    click=self.ctrl.admin_save,
                )


def _lines(text) -> list[str]:
    """Split a textarea value into a clean list of non-empty trimmed lines."""
    if not text:
        return []
    return [ln.strip() for ln in str(text).splitlines() if ln.strip()]
