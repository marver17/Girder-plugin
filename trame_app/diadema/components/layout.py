"""
AppLayout: top-level Trame UI layout for the DIADEMA application.

Structure:
- VAppBar: application title + user info + logout button
- VNavigationDrawer (left): file browser / navigation
- VMain: main content area (item detail view)
"""

from trame.widgets import vuetify3 as v3
from trame.ui.vuetify3 import VAppLayout

from diadema.config import GIRDER_PUBLIC_URL


class DiademaLayout:
    """
    Builds and owns the top-level UI skeleton.
    The actual content panels are injected by DiademaApp.
    """

    def __init__(self, server):
        self._server = server
        self.state = server.state

        self.state.update(
            {
                "drawer_open": True,
                "girder_user": None,
                "girder_token": None,
                # Currently viewed resource (item or folder)
                "current_location": None,
                "current_item_id": None,
                "current_item": None,
                # Active view: 'browse' | 'item' | 'jobs' | 'admin'
                "active_view": "browse",
            }
        )

        self.layout = VAppLayout(server, full_height=True)

    def build(self):
        """Populate the layout skeleton. Called from DiademaApp after panels are created."""
        with self.layout:
            # ── App bar ───────────────────────────────────────────────────
            with v3.VAppBar(color="primary", density="compact"):
                v3.VAppBarTitle("DIADEMA")
                v3.VSpacer()

                # Navigation buttons
                v3.VBtn(
                    "Browse",
                    variant="text",
                    click="active_view = 'browse'",
                    prepend_icon="mdi-folder-open",
                )
                v3.VBtn(
                    "Jobs",
                    variant="text",
                    click="active_view = 'jobs'",
                    prepend_icon="mdi-cog-play",
                )
                v3.VBtn(
                    "Admin",
                    variant="text",
                    click="active_view = 'admin'",
                    prepend_icon="mdi-shield-account",
                    v_if=("girder_user && girder_user.admin",),
                )

                v3.VDivider(vertical=True, inset=True, classes="mx-2")

                # User info + logout
                with v3.VChip(
                    v_if=("girder_user",),
                    variant="tonal",
                    color="white",
                    classes="mr-2",
                ):
                    v3.VIcon("mdi-account", start=True)
                    v3.VChipText(
                        "{{ girder_user.firstName }} {{ girder_user.lastName }}"
                    )

            # ── Main content (full width — file browser panel is rendered inside VMain) ──
            with v3.VMain(classes="d-flex flex-column"):
                pass  # Content is appended by DiademaApp

        return self.layout
