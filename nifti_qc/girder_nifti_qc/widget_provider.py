"""
Widget provider for NIfTI Quality Control metrics
"""

from girder_nifti_viewer.widget_registry import WidgetProviderBase


class QCWidgetProvider(WidgetProviderBase):
    """
    Provides quality control metrics widget for NIfTI viewer
    """

    @classmethod
    def get_widget_id(cls):
        return "nifti_qc_metrics"

    @classmethod
    def get_title(cls):
        return "Quality Control Metrics"

    @classmethod
    def get_priority(cls):
        return 10  # High priority - show before other widgets

    @classmethod
    def get_rest_endpoint(cls):
        # Data is stored in item metadata, no custom endpoint needed
        return None

    def should_display(self, item):
        """Display widget if item has QC results"""
        return "nifti_qc_results" in item

    def get_data(self, item):
        """Return QC results from item metadata"""
        qc_results = item.get("nifti_qc_results", {})
        qc_status = item.get("nifti_qc_status", "unknown")

        return {"results": qc_results, "status": qc_status}
