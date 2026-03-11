"""Widget provider DIADEMA per nifti_viewer.

Usa le Settings del plugin (diadema.widget_enabled, diadema.widget_fields_*)
per controllare la visibilità dei tool e i campi da esporre.
"""

import logging

from girder_nifti_viewer.widget_registry import WidgetProviderBase

logger = logging.getLogger(__name__)


def _get_settings():
    """Legge le settings DIADEMA da Girder. Ritorna (widget_enabled, fields_mriqc, fields_fs)."""
    try:
        from girder.models.setting import Setting

        from .settings import PluginSettings

        enabled = Setting().get(PluginSettings.WIDGET_ENABLED)
        fields_mriqc = Setting().get(PluginSettings.WIDGET_FIELDS_MRIQC)
        fields_fs = Setting().get(PluginSettings.WIDGET_FIELDS_FREESURFER)
        return enabled, fields_mriqc, fields_fs
    except Exception as exc:
        logger.warning("[diadema_pipeline] Impossibile leggere settings: %s", exc)
        # Ritorna valori di default safe
        from .settings import (
            _DEFAULT_WIDGET_ENABLED,
            _DEFAULT_WIDGET_FIELDS_FREESURFER,
            _DEFAULT_WIDGET_FIELDS_MRIQC,
        )

        return (
            dict(_DEFAULT_WIDGET_ENABLED),
            list(_DEFAULT_WIDGET_FIELDS_MRIQC),
            list(_DEFAULT_WIDGET_FIELDS_FREESURFER),
        )


class DiademaWidgetProvider(WidgetProviderBase):
    @classmethod
    def get_widget_id(cls):
        return "diadema_results"

    @classmethod
    def get_title(cls):
        return "DIADEMA Pipeline Results"

    @classmethod
    def get_priority(cls):
        return 15

    @classmethod
    def get_rest_endpoint(cls):
        return None

    def should_display(self, item):
        enabled, _, _ = _get_settings()
        diadema = item.get("diadema") or {}
        return any(
            enabled.get(t, False) and (diadema.get(t) or {}).get("results") is not None
            for t in ("mriqc", "freesurfer", "lstai")
        )

    def get_data(self, item):
        enabled, fields_mriqc, fields_fs = _get_settings()
        diadema = item.get("diadema") or {}

        data = {}

        if enabled.get("mriqc", True):
            tool_data = diadema.get("mriqc") or {}
            results = tool_data.get("results")
            if results and "metrics" in results:
                filtered_metrics = {
                    k: v
                    for k, v in results["metrics"].items()
                    if not fields_mriqc or k in fields_mriqc
                }
                results = {**results, "metrics": filtered_metrics}
            data["mriqc"] = {
                "results": results,
                "status": tool_data.get("status"),
            }

        if enabled.get("freesurfer", True):
            tool_data = diadema.get("freesurfer") or {}
            results = tool_data.get("results")
            if results and "stats" in results:
                stats = results["stats"]
                if fields_fs:
                    filtered_sub = {
                        k: v
                        for k, v in stats.get("subcortical", {}).items()
                        if k in fields_fs
                    }
                    filtered_glob = {
                        k: v
                        for k, v in stats.get("global", {}).items()
                        if k in fields_fs
                    }
                    results = {
                        **results,
                        "stats": {
                            **stats,
                            "subcortical": filtered_sub,
                            "global": filtered_glob,
                        },
                    }
            data["freesurfer"] = {
                "results": results,
                "status": tool_data.get("status"),
            }

        if enabled.get("lstai", False):
            tool_data = diadema.get("lstai") or {}
            data["lstai"] = {
                "results": tool_data.get("results"),
                "status": tool_data.get("status"),
            }

        return data
