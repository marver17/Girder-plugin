"""Widget provider DIADEMA per nifti_viewer."""

from girder_nifti_viewer.widget_registry import WidgetProviderBase


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
        return any(
            f"diadema_{t}_results" in item
            for t in ("mriqc", "freesurfer", "lstai")
        )

    def get_data(self, item):
        return {
            "mriqc":      {"results": item.get("diadema_mriqc_results"),      "status": item.get("diadema_mriqc_status")},
            "freesurfer": {"results": item.get("diadema_freesurfer_results"), "status": item.get("diadema_freesurfer_status")},
            "lstai":      {"results": item.get("diadema_lstai_results"),      "status": item.get("diadema_lstai_status")},
        }
