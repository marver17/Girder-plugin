"""
DIADEMA Pipeline Plugin per Girder v5

Orchestratore per analisi neuroimaging multi-tool:
  - MRI QC (MRIQC)
  - FreeSurfer recon-all
  - LST-AI lesion segmentation

Ogni tool gira in un container Docker dedicato e comunica
tramite Celery worker + RabbitMQ.
"""

import logging
from pathlib import Path

from girder import events
from girder.constants import AccessType
from girder.models.item import Item
from girder.plugin import GirderPlugin, registerPluginStaticContent

logger = logging.getLogger(__name__)


class DiademaPlugin(GirderPlugin):
    DISPLAY_NAME = "DIADEMA Pipeline"
    CLIENT_SOURCE_PATH = "web_client"

    def load(self, info):
        from .rest import DiademaResource
        from .settings import (
            PluginSettings,
        )  # registra validatori e default  # noqa: F401
        from .widget_provider import DiademaWidgetProvider

        # Esponi il campo diadema (tutti i dati di elaborazione) via REST
        Item().exposeFields(level=AccessType.READ, fields={"diadema"})

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
                    logger.info(
                        "[diadema_pipeline] Widget provider: registrato via evento"
                    )
                except Exception as e:
                    logger.error("[diadema_pipeline] Widget provider: errore: %s", e)

        if "nifti_widget_registry" in info:
            try:
                info["nifti_widget_registry"]["register_function"](
                    DiademaWidgetProvider
                )
                logger.info(
                    "[diadema_pipeline] Widget provider: registrato (immediato)"
                )
            except Exception as e:
                logger.error(
                    "[diadema_pipeline] Widget provider: errore immediato: %s", e
                )

        events.bind(
            "nifti_viewer.register_widgets", "diadema_pipeline", _register_widget
        )

        logger.info("[diadema_pipeline] Plugin caricato!")
        logger.info("  - REST API: /api/v1/diadema_pipeline")
        logger.info("  - Tool: MRI QC, FreeSurfer, LST-AI")
        logger.info("  - Settings: diadema.output_storage, diadema.widget_enabled, ...")
        logger.info("  - Settings: diadema.output_storage, diadema.widget_enabled, ...")
