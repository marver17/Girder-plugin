"""
DIADEMA Trame Application - Main entrypoint.

Wires together:
  - GirderProvider (auth, token management)
  - DiademaLayout (app bar, main structure)
  - FileBrowserPanel (left split: file browser)
  - AuthManager (syncs JS token → Python GirderClient)
  - PipelineService / JobMonitor / PipelinePanel (launch & monitor pipelines)
  - JobsView (user job list), ResultsPanel (pipeline results)
"""

import argparse

from trame.app import TrameApp
from trame.ui.vuetify3 import VAppLayout
from trame.widgets import gwc
from trame.widgets import html
from trame.widgets import vuetify3 as v3

from diadema.config import GIRDER_PUBLIC_URL, TRAME_HOST, TRAME_PORT
from diadema.core.girder_client import DiademaGirderClient
from diadema.core.auth_manager import AuthManager
from diadema.core.pipeline_service import PipelineService
from diadema.core.job_monitor import JobMonitor
from diadema.components.file_browser import FileBrowserPanel
from diadema.components.viewer import ViewerPanel
from diadema.components.pipeline_panel import PipelinePanel
from diadema.components.jobs_view import JobsView
from diadema.components.results_panel import ResultsPanel
from diadema.components.admin_view import AdminView


class DiademaApp(TrameApp):
    def __init__(self, server=None):
        super().__init__(server, client_type="vue3")

        # ── Shared Girder client (server-side REST calls) ─────────────────
        self.gc = DiademaGirderClient()

        # ── Auth manager: keeps gc in sync with GirderProvider token ──────
        self.auth_manager = AuthManager(self.server, self.gc)

        # ── Pipeline services ─────────────────────────────────────────────
        self.pipeline_service = PipelineService(self.server, self.gc)
        self.job_monitor = JobMonitor(self.server, self.gc)

        # ── Sub-panels ────────────────────────────────────────────────────
        self.file_browser = FileBrowserPanel(self.server, self.gc)
        self.viewer = ViewerPanel(self.server, self.gc)
        self.pipeline_panel = PipelinePanel(
            self.server, self.gc, self.pipeline_service, self.job_monitor
        )
        self.jobs_view = JobsView(self.server, self.gc, self.pipeline_service)
        self.results_panel = ResultsPanel(self.server, self.gc)
        self.admin_view = AdminView(self.server, self.gc, self.pipeline_service)

        # ── Initialize default state ──────────────────────────────────────
        self.state.update(
            {
                "girder_api_root": f"{GIRDER_PUBLIC_URL}/api/v1",
                "girder_user": None,
                "girder_token": None,
                "current_location": None,
                "current_item_id": None,
                "current_item": None,
                "active_view": "browse",
                "file_manager_selected": [],
                # Pipeline scope (set by file browser on selection)
                "pipeline_scope": "item",
                "pipeline_target_ids": [],
                "pipeline_scope_label": "",
                # Pipeline jobs & UI feedback
                "pipeline_jobs": {},
                "ui_error": None,
            }
        )

        self._build_ui()

    def _build_ui(self):
        with VAppLayout(self.server, full_height=True) as self.layout:

            # ── GirderProvider wraps everything ───────────────────────────
            # It manages the browser-side auth token and Girder API connection.
            # Events bridge JS auth state → Trame state keys.
            with gwc.GirderProvider(
                api_root=("girder_api_root",),
                user_logged_in=(
                    "girder_user = $event.user; girder_token = $event.token; "
                    "current_location = { _modelType: 'collections' };"
                ),
                user_fetched=(
                    "girder_user = $event.user; girder_token = $event.token; "
                    "current_location = { _modelType: 'collections' };"
                ),
                user_logged_out="girder_user = null; girder_token = null; current_location = null;",
            ) as self._provider:

                # ── App bar ───────────────────────────────────────────────
                with v3.VAppBar(color="primary", density="compact", elevation=2):
                    v3.VAppBarTitle(
                        "DIADEMA",
                        style="font-weight: bold; letter-spacing: 0.05em;",
                    )
                    v3.VSpacer()

                    # Navigation buttons (only when logged in)
                    with v3.VBtnGroup(
                        v_if=("girder_user",), variant="text", density="compact"
                    ):
                        v3.VBtn(
                            "Browse",
                            prepend_icon="mdi-folder-open",
                            click="active_view = 'browse'",
                            color=("active_view === 'browse' ? 'white' : ''",),
                        )
                        v3.VBtn(
                            "Jobs",
                            prepend_icon="mdi-cog-play",
                            click="active_view = 'jobs'",
                            color=("active_view === 'jobs' ? 'white' : ''",),
                        )
                        v3.VBtn(
                            "Admin",
                            prepend_icon="mdi-shield-account",
                            click="active_view = 'admin'",
                            v_if=("girder_user && girder_user.admin",),
                            color=("active_view === 'admin' ? 'white' : ''",),
                        )

                    v3.VDivider(
                        vertical=True, inset=True, classes="mx-2", v_if=("girder_user",)
                    )

                    # User chip + logout
                    with v3.VChip(
                        v_if=("girder_user",),
                        variant="tonal",
                        color="white",
                        classes="mr-2",
                        size="small",
                    ):
                        v3.VIcon("mdi-account", start=True)
                        html.Span(v_text="girder_user.firstName + ' ' + girder_user.lastName")
                    v3.VBtn(
                        v_if=("girder_user",),
                        icon="mdi-logout",
                        variant="text",
                        color="white",
                        size="small",
                        click=self._provider.logout,
                        title="Logout",
                    )

                # ── Main content area ─────────────────────────────────────
                with v3.VMain():

                    # Not logged in → show login form centered
                    with v3.VContainer(
                        v_if=("!girder_user",),
                        fluid=True,
                        classes="fill-height d-flex align-center justify-center",
                    ):
                        with v3.VCard(max_width=480, elevation=4):
                            with v3.VCardTitle(classes="text-h6 pa-4"):
                                v3.VIcon("mdi-brain", classes="mr-2", color="primary")
                                html.Span("Sign in to DIADEMA")
                            with v3.VCardText():
                                gwc.GirderAuthentication(
                                    register=False,
                                    oauth=True,
                                )

                    # Logged in → split layout: left file browser / right content
                    with v3.VContainer(
                        v_if=("girder_user",),
                        fluid=True,
                        classes="fill-height pa-0 d-flex flex-row",
                    ):
                        # Left panel: file browser
                        with v3.VSheet(
                            width=380,
                            min_width=280,
                            max_width=480,
                            classes="d-flex flex-column border-e",
                            style="overflow-y: auto;",
                        ) as left_panel:
                            self.file_browser.build(left_panel)

                        # Right panel: content depending on active_view
                        with v3.VSheet(
                            classes="flex-grow-1 d-flex flex-column",
                            style="overflow-y: auto;",
                        ):
                            # Browse view: folder scope → pipeline panel,
                            # otherwise prompt to pick a file
                            with v3.VSheet(
                                v_if=(
                                    "active_view === 'browse' && !current_item_id"
                                    " && pipeline_scope !== 'item'"
                                    " && pipeline_target_ids.length",
                                ),
                                classes="d-flex flex-column",
                                max_width=560,
                            ):
                                self.pipeline_panel.build()

                            with v3.VContainer(
                                v_if=(
                                    "active_view === 'browse' && !current_item_id"
                                    " && (pipeline_scope === 'item'"
                                    " || !pipeline_target_ids.length)",
                                ),
                                classes="fill-height d-flex align-center justify-center",
                            ):
                                with v3.VSheet(
                                    classes="text-center text-medium-emphasis pa-8"
                                ):
                                    v3.VIcon(
                                        "mdi-cursor-default-click",
                                        size=64,
                                        color="grey-lighten-1",
                                    )
                                    html.P(
                                        "Select a NIfTI file or a BIDS folder "
                                        "from the panel on the left",
                                        classes="mt-4 text-body-1",
                                    )

                            # Item detail view: viewer + pipeline side column
                            with v3.VSheet(
                                v_if=("active_view === 'item' && current_item",),
                                classes="flex-grow-1 d-flex flex-row fill-height",
                                style="position: relative;",
                            ):
                                with v3.VSheet(
                                    classes="flex-grow-1 d-flex flex-column fill-height",
                                    style="position: relative; min-width: 0;",
                                ):
                                    self.viewer.build()
                                with v3.VSheet(
                                    width=380,
                                    classes="d-flex flex-column border-s",
                                    style="overflow-y: auto;",
                                ):
                                    self.pipeline_panel.build()
                                    self.results_panel.build()

                            # Jobs view
                            with v3.VSheet(
                                v_if=("active_view === 'jobs'",),
                                classes="flex-grow-1 d-flex flex-column",
                            ):
                                self.jobs_view.build()

                            # Admin view: plugin settings + Girder admin link
                            with v3.VSheet(
                                v_if=("active_view === 'admin'",),
                                classes="flex-grow-1 d-flex flex-column",
                                style="overflow-y: auto;",
                            ):
                                self.admin_view.build()

                # ── Global force re-run dialog (HTTP 409 conflicts) ───────
                self.pipeline_panel.build_force_dialog()

                # ── Global error snackbar ─────────────────────────────────
                with v3.VSnackbar(
                    model_value=("ui_error !== null",),
                    timeout=6000,
                    color="error",
                    location="bottom right",
                    update_modelValue="ui_error = null",
                ):
                    html.Span("{{ ui_error && ui_error.message }}")
                    with html.Template(v_slot_actions=True):
                        v3.VBtn(
                            "Close",
                            variant="text",
                            click="ui_error = null",
                        )


def main():
    parser = argparse.ArgumentParser(description="DIADEMA Trame App")
    parser.add_argument("--host", default=TRAME_HOST)
    parser.add_argument("--port", type=int, default=TRAME_PORT)
    parser.add_argument("--dev", action="store_true", help="Enable hot reload")
    args = parser.parse_args()

    app = DiademaApp()
    app.server.start(
        host=args.host,
        port=args.port,
        open_browser=False,
        ws_endpoint="paraview",
    )


if __name__ == "__main__":
    main()
