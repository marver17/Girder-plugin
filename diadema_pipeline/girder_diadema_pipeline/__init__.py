"""
DIADEMA Pipeline Plugin per Girder v5

Orchestratore per analisi neuroimaging multi-tool:
  - MRI QC (MRIQC)
  - FreeSurfer recon-all
  - LST-AI lesion segmentation

Ogni tool gira in un container Docker dedicato e comunica
tramite Celery worker + RabbitMQ.
"""

from pathlib import Path

from girder import events
from girder.constants import AccessType
from girder.models.item import Item
from girder.plugin import GirderPlugin, registerPluginStaticContent


class DiademaPlugin(GirderPlugin):
    DISPLAY_NAME = "DIADEMA Pipeline"
    CLIENT_SOURCE_PATH = "web_client"

    def load(self, info):
        from .rest import DiademaResource
        from .widget_provider import DiademaWidgetProvider

        # Esponi i campi di ogni tool via REST (AccessType.READ)
        Item().exposeFields(
            level=AccessType.READ,
            fields={
                # MRIQC
                "diadema_mriqc_results",
                "diadema_mriqc_status",
                "diadema_mriqc_error",
                # FreeSurfer
                "diadema_freesurfer_results",
                "diadema_freesurfer_status",
                "diadema_freesurfer_error",
                # LST-AI
                "diadema_lstai_results",
                "diadema_lstai_status",
                "diadema_lstai_error",
            },
        )

        info["apiRoot"].diadema_pipeline = DiademaResource()

        registerPluginStaticContent(
            plugin="diadema_pipeline",
            css=[],
            js=["/diadema-pipeline.umd.cjs"],
            staticDir=Path(__file__).parent / "web_client" / "dist",
            tree=info["serverRoot"],
        )

        # Integrazione widget con nifti_viewer
        def _register_widget(event):
            register_func = event.info.get("register_function")
            if register_func:
                try:
                    register_func(DiademaWidgetProvider)
                    print("[diadema_pipeline] Widget provider: registrato via evento")
                except Exception as e:
                    print(f"[diadema_pipeline] Widget provider: errore: {e}")

        if "nifti_widget_registry" in info:
            try:
                info["nifti_widget_registry"]["register_function"](DiademaWidgetProvider)
                print("[diadema_pipeline] Widget provider: registrato (immediato)")
            except Exception as e:
                print(f"[diadema_pipeline] Widget provider: errore immediato: {e}")

        events.bind("nifti_viewer.register_widgets", "diadema_pipeline", _register_widget)

        print("[diadema_pipeline] Plugin caricato!")
        print("  - REST API: /api/v1/diadema_pipeline")
        print("  - Tool: MRI QC, FreeSurfer, LST-AI")
