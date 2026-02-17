"""
NIfTI Quality Control Plugin for Girder

Integrates MRIQC (MRI Quality Control) for automated quality assessment
of NIfTI neuroimaging files using Girder Worker.
"""

from pathlib import Path

from girder.constants import AccessType
from girder.models.item import Item
from girder.plugin import GirderPlugin, registerPluginStaticContent

from .rest import NiftiQC


class NiftiQCPlugin(GirderPlugin):
    """
    Plugin that adds quality control capabilities for NIfTI files
    using MRIQC container via Girder Worker
    """

    DISPLAY_NAME = "NIfTI Quality Control"
    CLIENT_SOURCE_PATH = "web_client"

    def load(self, info):
        """Load plugin and register components"""

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

        print(" NIfTI QC Plugin loaded successfully!")
        print("   - REST API: /api/v1/nifti_qc")
        print("   - Web UI: enabled")
        print("   - Worker tasks: registered")
