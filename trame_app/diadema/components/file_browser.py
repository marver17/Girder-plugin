"""
FileBrowserPanel: Girder file browser panel using trame-gwc components.

Features:
- GirderAuthentication: login form when not authenticated
- GirderFileManager: full-featured file browser with upload support
- GirderBreadcrumb: path navigation
- Detects selected item/folder and updates state accordingly

When an item is selected, sets:
  state.current_item_id  → Girder item _id (string)
  state.current_item     → full item dict (fetched from REST API)
  state.active_view      → 'item' (switches main panel to item detail)

When a folder is selected, updates:
  state.current_location → new folder location
"""

import asyncio

from trame.widgets import gwc
from trame.widgets import html
from trame.widgets import vuetify3 as v3

from diadema.core.girder_client import DiademaGirderClient
from diadema.utils.bids_explorer import detect_scope


class FileBrowserPanel:
    """Left-side file browser panel."""

    def __init__(self, server, gc: DiademaGirderClient):
        self._server = server
        self._gc = gc
        self.state = server.state
        self.ctrl = server.controller

        # Register controller methods
        self.ctrl.on_location_updated = self._on_location_updated
        self.ctrl.on_item_selected = self._on_item_selected

    def _on_location_updated(self, new_location):
        """Called when the user navigates to a new folder."""
        self.state.current_location = new_location

    def _on_item_selected(self, selected_items):
        """
        Called when the user clicks on an item in the file manager.
        Detects whether it's a NIfTI item, a subject folder, or a dataset folder,
        and updates pipeline scope state accordingly.
        """
        if not selected_items:
            return

        resource = selected_items[0] if isinstance(selected_items, list) else selected_items

        if resource.get("_modelType") == "item":
            asyncio.ensure_future(self._load_item(resource["_id"]))
        elif resource.get("_modelType") == "folder":
            asyncio.ensure_future(self._inspect_folder(resource["_id"], resource))

    async def _load_item(self, item_id: str):
        """Fetch full item and switch to item detail view."""
        try:
            item = await self._gc.aget(f"item/{item_id}")

            # Detect pipeline scope for this item
            scope, target_ids, scope_label = await detect_scope(
                self._gc, item_id=item_id, resource_type="item"
            )

            # State mutations from a background task must be flushed explicitly
            with self.state:
                self.state.current_item_id = item_id
                self.state.current_item = item
                self.state.pipeline_scope = scope
                self.state.pipeline_target_ids = target_ids
                self.state.pipeline_scope_label = scope_label
                self.state.active_view = "item"

            # Resume tracking of any in-flight pipeline jobs on this item
            if self.ctrl.on_item_loaded.exists():
                self.ctrl.on_item_loaded(item)

            self.ctrl.on_load_volume(item)
        except Exception as e:
            print(f"[file_browser] Error loading item {item_id}: {e}")
            with self.state:
                self.state.ui_error = {"message": f"Failed to load item: {e}"}

    async def _inspect_folder(self, folder_id: str, folder: dict):
        """Inspect a folder to detect if it's a subject or dataset, update pipeline scope."""
        try:
            scope, target_ids, scope_label = await detect_scope(
                self._gc, folder_id=folder_id, resource_type="folder", folder=folder
            )
            with self.state:
                self.state.pipeline_scope = scope
                self.state.pipeline_target_ids = target_ids
                self.state.pipeline_scope_label = scope_label
                # Keep current_item_id as-is; folder selection doesn't open item view
        except Exception as e:
            print(f"[file_browser] Error inspecting folder {folder_id}: {e}")

    def build(self, container):
        """Render the file browser into the given container widget."""
        with container:
            # Login form — shown when not authenticated
            with v3.VCard(
                v_if=("!girder_user",),
                flat=True,
                classes="ma-4",
            ):
                with v3.VCardTitle():
                    v3.VIcon("mdi-account-circle", classes="mr-2")
                    html.Span("Sign in to DIADEMA")
                with v3.VCardText():
                    gwc.GirderAuthentication(
                        register=False,
                        oauth=True,
                    )

            # File browser — shown when authenticated
            with v3.VContainer(
                v_if=("girder_user",),
                fluid=True,
                classes="pa-0 fill-height d-flex flex-column",
            ):
                # Breadcrumb navigation
                with v3.VSheet(v_if=("current_location",), classes="px-2 pt-1 pb-0"):
                    gwc.GirderBreadcrumb(
                        location=("current_location",),
                        crumb_click=(
                            self.ctrl.on_location_updated,
                            "[$event]",
                        ),
                        root_location_disabled=False,
                    )

                v3.VDivider()

                # File manager
                gwc.GirderFileManager(
                    v_if=("current_location",),
                    location=("current_location",),
                    update_location=(
                        self.ctrl.on_location_updated,
                        "[$event]",
                    ),
                    selected=("file_manager_selected",),
                    update_selected=(
                        self.ctrl.on_item_selected,
                        "[$event]",
                    ),
                    upload_enabled=True,
                    new_folder_enabled=True,
                    selectable=True,
                    root_location_disabled=False,
                    classes="flex-grow-1",
                )
