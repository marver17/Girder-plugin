"""
Tests for NIfTI QC plugin
"""

import pytest


def test_plugin_loads():
    """Test that plugin loads correctly"""
    from girder_nifti_qc import NiftiQCPlugin

    plugin = NiftiQCPlugin()
    assert plugin.DISPLAY_NAME == "NIfTI Quality Control"


def test_tasks_importable():
    """Test that tasks can be imported"""
    from girder_nifti_qc import tasks

    assert hasattr(tasks, "quick_nifti_check")
    assert hasattr(tasks, "run_mriqc_task")


def test_rest_api_importable():
    """Test that REST API can be imported"""
    from girder_nifti_qc import rest

    assert hasattr(rest, "NiftiQC")
