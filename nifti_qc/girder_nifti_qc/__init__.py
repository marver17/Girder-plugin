"""
NIfTI Quality Control Plugin for Girder

Integrates MRIQC (MRI Quality Control) for automated quality assessment
of NIfTI neuroimaging files using Girder Worker.
"""

from pathlib import Path

from girder import events
from girder.constants import AccessType
from girder.models.item import Item
from girder.plugin import GirderPlugin, registerPluginStaticContent


class NiftiQCPlugin(GirderPlugin):
    """
    Plugin that adds quality control capabilities for NIfTI files
    using MRIQC container via Girder Worker
    """

    DISPLAY_NAME = "NIfTI Quality Control"
    CLIENT_SOURCE_PATH = "web_client"

    def load(self, info):
        """Load plugin and register components"""
        from .rest import NiftiQC
        from .widget_provider import QCWidgetProvider

        # Expose field for QC results on items
        Item().exposeFields(
            level=AccessType.READ, fields={"nifti_qc_results", "nifti_qc_status"}
        )

        # Register REST API endpoints
        info["apiRoot"].nifti_qc = NiftiQC()

        # Register web client static files
        registerPluginStaticContent(
            plugin="nifti_qc",
            css=[],
            js=["/nifti-qc.umd.cjs"],
            staticDir=Path(__file__).parent / "web_client" / "dist",
            tree=info["serverRoot"],
        )

        # Register widget provider with NIfTI viewer
        # Strategy: try both immediate registration and event binding
        # This handles both cases: nifti_viewer loading before or after us

        widget_registered = False

        # Try immediate registration if nifti_viewer already loaded
        if "nifti_widget_registry" in info:
            try:
                register_func = info["nifti_widget_registry"]["register_function"]
                register_func(QCWidgetProvider)
                widget_registered = True
                print("   - Widget provider: registered (immediate)")
            except Exception as e:
                print(f"   - Widget provider: immediate registration failed: {e}")

        # Also bind to event in case nifti_viewer loads after us
        def _register_widget(event):
            register_func = event.info.get("register_function")
            if register_func:
                try:
                    register_func(QCWidgetProvider)
                    print("   - Widget provider: registered (via event)")
                except Exception as e:
                    print(f"   - Widget provider: event registration failed: {e}")

        events.bind("nifti_viewer.register_widgets", "nifti_qc", _register_widget)

        print(" NIfTI QC Plugin loaded successfully!")
        print("   - REST API: /api/v1/nifti_qc")
        print("   - Web UI: enabled")
        print("   - Worker tasks: registered")
