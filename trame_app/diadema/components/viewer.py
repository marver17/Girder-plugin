"""
ViewerPanel: GirderMedViewer quad-view NIfTI viewer component.

Integra:
- FileFetcher per scaricare e cachare i file NIfTI da Girder
- SceneLogic per gestire il volume nella scena VTK
- ViewUI per il rendering quad-view (Sagittal, 3D, Coronal, Axial)

Flusso di caricamento:
  1. _load_item(item) riceve l'item Girder selezionato
  2. Recupera la lista file dell'item via REST
  3. Scarica il primo file NIfTI via FileFetcher (con cache in CACHE_DIR)
  4. Crea un SceneObject e lo aggiunge alla SceneLogic
  5. SceneLogic carica il vtkImageData e aggiorna il ViewUI
"""

import asyncio
import os
import uuid

from girdermedviewer.app.widgets.utils import FileFetcher, CacheMode
from girdermedviewer.app.widgets.logic.scene.scene_logic import SceneLogic
from girdermedviewer.app.widgets.logic.scene.objects.scene_object_logic import SceneObject
from girdermedviewer.app.widgets.ui.vtk.view_ui import ViewUI

from diadema.config import CACHE_DIR
from diadema.core.girder_client import DiademaGirderClient


class ViewerPanel:
    """Right-side NIfTI quad-view panel using GirderMedViewer."""

    def __init__(self, server, gc: DiademaGirderClient):
        self._server = server
        self._gc = gc
        self.state = server.state
        self.ctrl = server.controller

        # Assicura che la directory di cache esista
        os.makedirs(CACHE_DIR, exist_ok=True)

        # FileFetcher: scarica i file NIfTI con cache di sessione
        self._fetcher = FileFetcher(
            girder_client=gc.raw,
            temp_dir=CACHE_DIR,
            cache_mode=CacheMode.Session,
        )

        # SceneLogic gestisce volumi nella scena VTK
        self._scene_logic = SceneLogic(server)

        # ViewUI quad-view: istanziato in build()
        self._view_ui = None

        self.state.update(
            {
                "viewer_loading": False,
                "viewer_error": None,
            }
        )

        # Handler chiamato da FileBrowserPanel quando viene selezionato un item
        self.ctrl.on_load_volume = self._load_item

    def _load_item(self, item: dict):
        """Avvia il caricamento asincrono del volume NIfTI."""
        asyncio.ensure_future(self._async_load_item(item))

    async def _async_load_item(self, item: dict):
        """Scarica e carica il volume NIfTI dell'item Girder selezionato."""
        if not item:
            return
        item_id = item.get("_id")
        if not item_id:
            return

        self.state.viewer_loading = True
        self.state.viewer_error = None

        try:
            # Pulisce la scena precedente
            self._scene_logic.clear_scene()

            # Recupera i file dell'item
            files = self._gc.get(f"item/{item_id}/files", parameters={"limit": 50})
            nifti_files = [
                f for f in files
                if f.get("name", "").endswith((".nii", ".nii.gz"))
            ]
            if not nifti_files:
                self.state.viewer_error = "Nessun file NIfTI trovato in questo item."
                return

            file_info = nifti_files[0]

            # Scarica il file (con cache) e caricalo nella scena
            async with self._fetcher.fetch_file(file_info) as local_path:
                object_id = str(uuid.uuid4())
                scene_object = SceneObject(trame_server=self._server)
                scene_object._id = object_id

                self._scene_logic.add_object(scene_object)
                self._scene_logic.add_file_object_to_views(str(local_path), object_id)

        except Exception as e:
            self.state.viewer_error = str(e)
        finally:
            self.state.viewer_loading = False

    def build(self):
        """
        Render il quad-view e gli overlay di stato.
        Deve essere chiamato dentro un contesto widget attivo (with ...:).
        """
        from trame.widgets import vuetify3 as v3
        from trame.widgets import html

        # Spinner di caricamento
        with v3.VOverlay(
            v_if=("viewer_loading",),
            contained=True,
            classes="d-flex align-center justify-center",
        ):
            v3.VProgressCircular(indeterminate=True, color="primary", size=48)

        # Messaggio di errore
        with v3.VAlert(
            v_if=("viewer_error",),
            type="error",
            variant="tonal",
            classes="ma-4",
            closable=True,
            close=("viewer_error = null",),
        ):
            html.Span(v_text="viewer_error")

        # Quad-view VTK
        self._view_ui = ViewUI(
            style="width: 100%; height: 100%;",
        )

        # Collega la ViewUI alla SceneLogic per ricevere i volumi caricati
        self._scene_logic.set_view_ui(self._view_ui)
