"""
Celery tasks for NIfTI Quality Control using MRIQC

MRIQC Documentation: https://mriqc.readthedocs.io/
Installation: pip install mriqc (local installation)
"""

import datetime
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from girder_worker.app import app
from girder_worker.utils import girder_job


@girder_job(title="MRIQC - NIfTI Quality Control")
@app.task(bind=True)
def run_mriqc_task(task, **kwargs):
    """
    Execute MRIQC quality control on a NIfTI file using local installation

    Args:
        task: Celery task instance (injected by bind=True)
        **kwargs: All parameters including:
            - item_id (str): Girder item ID
            - file_id (str): Girder file ID for the NIfTI file
            - participant_label (str): BIDS participant label
            - modality (str): MRI modality (T1w, T2w, etc.)
            - file_name (str): Name of the file
            - timeout (int): Maximum execution time in seconds
            - girder_client_token (str): Authentication token for Girder API
            - girder_api_url (str): Girder API URL

    Returns:
        dict: QC results including metrics and paths to outputs

    MRIQC will:
    - Extract IQMs (Image Quality Metrics)
    - Generate visual reports (HTML)
    - Produce JSON with quantitative metrics
    """
    from girder_client import GirderClient

    # Extract parameters from kwargs (non-reserved)
    item_id = kwargs.get("item_id")
    file_id = kwargs.get("file_id")
    file_name = kwargs.get("file_name", "unknown file")
    participant_label = kwargs.get("participant_label", "001")
    modality = kwargs.get("modality", "T1w")

    # Extract reserved parameters from task.request (girder_worker moves them there)
    girder_client_token = getattr(task.request, "girder_client_token", None)
    girder_api_url = getattr(
        task.request, "girder_api_url", "http://localhost:8080/api/v1"
    )
    # When running inside Docker, the Girder server may send its own localhost URL
    # which is unreachable from other containers. Override with the env var if set.
    girder_api_url_env = os.environ.get("GIRDER_API_URL")
    if girder_api_url_env and (
        "localhost" in girder_api_url or "127.0.0.1" in girder_api_url
    ):
        girder_api_url = girder_api_url_env

    # Initialize progress with descriptive message
    # The @girder_job decorator handles job status updates automatically
    task.job_manager.updateProgress(
        message=f"MRIQC: {file_name} ({modality}, sub-{participant_label})",
        total=100,
        current=5,
    )

    # Create Girder client manually with token
    gc = GirderClient(apiUrl=girder_api_url)
    gc.token = girder_client_token

    # Create temporary workspace
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Setup directories following BIDS structure
        input_dir = tmpdir_path / "input"
        output_dir = tmpdir_path / "output"
        work_dir = tmpdir_path / "work"

        input_dir.mkdir()
        output_dir.mkdir()
        work_dir.mkdir()

        # Download NIfTI file
        task.job_manager.updateProgress(
            message="Downloading NIfTI file from Girder...", current=10
        )

        file_info = gc.get(f"file/{file_id}")
        filename = file_info["name"]

        # BIDS requires dataset_description.json in the root
        dataset_description = {
            "Name": "Girder NIfTI QC",
            "BIDSVersion": "1.6.0",
            "DatasetType": "raw",
        }
        with open(input_dir / "dataset_description.json", "w") as f:
            json.dump(dataset_description, f)

        # BIDS structure varies by modality
        if modality == "bold":
            subdir = "func"
            bids_filename = f"sub-{participant_label}_task-rest_{modality}.nii.gz"
        elif modality == "dwi":
            subdir = "dwi"
            bids_filename = f"sub-{participant_label}_{modality}.nii.gz"
        else:
            # T1w, T2w and other anatomical modalities
            subdir = "anat"
            bids_filename = f"sub-{participant_label}_{modality}.nii.gz"

        subject_dir = input_dir / f"sub-{participant_label}" / subdir
        subject_dir.mkdir(parents=True)
        nifti_path = subject_dir / bids_filename

        gc.downloadFile(file_id, str(nifti_path))

        task.job_manager.updateProgress(
            message=f"Running MRIQC on {filename}...", current=30
        )

        # Prepare MRIQC command (local installation)
        mriqc_cmd = [
            "mriqc",
            str(input_dir),
            str(output_dir),
            "participant",
            "--participant-label",
            participant_label,
            "--no-sub",  # Don't generate group-level reports
            "-w",
            str(work_dir),
            "--verbose-reports",
        ]

        # Add optional flags
        if kwargs.get("skip_web_report", False):
            mriqc_cmd.append("--no-web-reports")

        try:
            # Execute MRIQC
            task.job_manager.updateProgress(
                message="MRIQC processing in progress (this may take several minutes)...",
                current=40,
            )

            result = subprocess.run(
                mriqc_cmd,
                capture_output=True,
                text=True,
                timeout=kwargs.get("timeout", 1800),  # 30 min default
            )

            if result.returncode != 0:
                raise Exception(
                    f"MRIQC failed with code {result.returncode}: {result.stderr}"
                )

            task.job_manager.updateProgress(
                message="MRIQC completed, collecting results...", current=80
            )

            # Parse MRIQC outputs
            qc_results = _parse_mriqc_outputs(output_dir, participant_label, modality)

            # Upload results to Girder
            task.job_manager.updateProgress(
                message="Uploading results to Girder...", current=90
            )

            _upload_results_to_girder(
                gc,
                item_id,
                file_id,
                qc_results,
                output_dir,
                participant_label,
                modality,
            )

            # Update item metadata
            gc.put(
                f"item/{item_id}/metadata",
                json={
                    "nifti_qc_results": {
                        "metrics": qc_results["metrics"],
                        "timestamp": datetime.datetime.now(
                            datetime.timezone.utc
                        ).isoformat(),
                        "mriqc_version": _get_mriqc_version(),
                        "participant_label": participant_label,
                        "modality": modality,
                        "file_id": file_id,
                        "file_name": filename,
                    },
                    "nifti_qc_status": "completed",
                },
            )

            task.job_manager.updateProgress(
                message="Quality control completed successfully!", current=100
            )

            # The @girder_job decorator handles job completion automatically

            return {
                "status": "success",
                "item_id": item_id,
                "file_id": file_id,
                "metrics": qc_results["metrics"],
                "reports_uploaded": qc_results.get("reports_uploaded", []),
            }

        except subprocess.TimeoutExpired:
            error_msg = f'MRIQC timeout after {kwargs.get("timeout", 1800)} seconds'
            _update_item_error(gc, item_id, "MRIQC timeout exceeded")

            # The @girder_job decorator handles job failure automatically
            raise Exception(error_msg)

        except Exception as e:
            error_msg = str(e)
            _update_item_error(gc, item_id, error_msg)

            # The @girder_job decorator handles job failure automatically
            raise


@girder_job(title="Quick NIfTI Check")
@app.task(bind=True)
def quick_nifti_check(task, **kwargs):
    """
    Simple task to verify NIfTI structure without running full MRIQC
    Useful for testing and quick validation
    """
    import datetime

    import nibabel as nib
    import numpy as np
    from girder_client import GirderClient

    def safe_progress(message, current=None, total=None):
        """Aggiorna il progresso del job senza bloccare il task se fallisce."""
        print(f"[quick_nifti_check] {message}")
        try:
            kwargs_ = {"message": message}
            if current is not None:
                kwargs_["current"] = current
            if total is not None:
                kwargs_["total"] = total
            task.job_manager.updateProgress(**kwargs_)
        except Exception as e:
            print(f"[quick_nifti_check] updateProgress failed (non-fatal): {e}")

    # Estrai parametri dal task
    item_id = kwargs.get("item_id")
    file_id = kwargs.get("file_id")
    file_name = kwargs.get("file_name", "unknown file")
    girder_client_token = getattr(task.request, "girder_client_token", None)
    girder_api_url = getattr(
        task.request, "girder_api_url", "http://localhost:8080/api/v1"
    )
    girder_api_url_env = os.environ.get("GIRDER_API_URL")
    if girder_api_url_env and (
        "localhost" in girder_api_url or "127.0.0.1" in girder_api_url
    ):
        girder_api_url = girder_api_url_env

    print(f"[quick_nifti_check] Starting: item={item_id}, file={file_name}")

    gc = GirderClient(apiUrl=girder_api_url)
    gc.token = girder_client_token

    try:
        safe_progress(f"Quick check: {file_name}", total=100, current=5)
        safe_progress("Downloading file...", current=20)

        with tempfile.TemporaryDirectory() as tmpdir:
            nifti_file = Path(tmpdir) / "temp.nii.gz"
            gc.downloadFile(file_id, str(nifti_file))
            print(f"[quick_nifti_check] File downloaded: {nifti_file}")

            safe_progress("Analyzing NIfTI...", current=50)

            img = nib.load(str(nifti_file))
            header = img.header
            data = img.get_fdata()

            info = {
                "shape": list(img.shape),
                "dtype": str(img.get_data_dtype()),
                "voxel_size_mm": [float(x) for x in header.get_zooms()],
                "orientation": list(nib.aff2axcodes(img.affine)),
                "data_range": {
                    "min": float(np.min(data)),
                    "max": float(np.max(data)),
                    "mean": float(np.mean(data)),
                    "std": float(np.std(data)),
                },
            }
            print(f"[quick_nifti_check] Analysis done: shape={info['shape']}")

            safe_progress("Saving results...", current=80)

            qc_results = {
                "quick_check": info,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "type": "quick_check",
            }
            gc.put(
                f"item/{item_id}/metadata",
                json={
                    "nifti_qc_results": qc_results,
                    "nifti_qc_status": "quick_check_completed",
                },
            )
            print(f"[quick_nifti_check] Results saved to item {item_id}")

            safe_progress("Done!", current=100)
            return {"status": "success", "info": info}

    except Exception as e:
        import traceback

        print(f"[quick_nifti_check] ERROR: {e}")
        print(traceback.format_exc())
        safe_progress(f"Quick check failed: {e}", current=100)
        try:
            gc.put(
                f"item/{item_id}/metadata",
                json={
                    "nifti_qc_status": "error",
                    "nifti_qc_error": {
                        "message": str(e),
                        "timestamp": datetime.datetime.utcnow().isoformat(),
                    },
                },
            )
        except Exception:
            pass
        raise


# Helper functions


def _parse_mriqc_outputs(output_dir, participant_label, modality):
    """Parse MRIQC JSON outputs"""
    results = {"metrics": {}, "reports": []}

    # Find JSON metrics file
    json_pattern = f"sub-{participant_label}_{modality}.json"
    json_files = list(output_dir.glob(f"**/{json_pattern}"))

    if json_files:
        with open(json_files[0]) as f:
            results["metrics"] = json.load(f)

    # Find HTML reports
    html_files = list(output_dir.glob("**/*.html"))
    results["reports"] = [str(f.name) for f in html_files]

    return results


def _upload_results_to_girder(
    gc, item_id, file_id, qc_results, output_dir, participant_label, modality
):
    """Upload MRIQC reports to Girder"""
    uploaded = []

    # Upload HTML reports
    html_files = list(output_dir.glob("**/*.html"))
    for html_file in html_files:
        gc.uploadFileToItem(item_id, str(html_file))
        uploaded.append(html_file.name)

    # Upload JSON metrics
    json_pattern = f"sub-{participant_label}_{modality}.json"
    json_files = list(output_dir.glob(f"**/{json_pattern}"))
    for json_file in json_files:
        gc.uploadFileToItem(item_id, str(json_file))
        uploaded.append(json_file.name)

    qc_results["reports_uploaded"] = uploaded


def _get_mriqc_version():
    """Get MRIQC version from local installation"""
    try:
        result = subprocess.run(
            ["mriqc", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()
    except:
        return "unknown"


def _update_item_error(gc, item_id, error_msg):
    """Update item with error status"""
    try:
        gc.put(
            f"item/{item_id}/metadata",
            json={
                "nifti_qc_status": "error",
                "nifti_qc_error": {
                    "message": error_msg,
                    "timestamp": datetime.datetime.now(
                        datetime.timezone.utc
                    ).isoformat(),
                },
            },
        )
    except Exception:
        pass
