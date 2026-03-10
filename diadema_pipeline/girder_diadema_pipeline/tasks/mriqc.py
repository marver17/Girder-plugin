"""
Task DIADEMA – MRI Quality Control (MRIQC).

Directory configurabili (ordine di priorità):
  1. Parametro esplicito nella chiamata   → output_base_dir=...
  2. Variabile d'ambiente nel container   → DIADEMA_MRIQC_OUTPUT_DIR
  3. Default hardcoded                    → /data/diadema/mriqc

La directory di output viene strutturata come:
  <output_base_dir>/<item_id>/output/   ← report HTML + JSON metriche
  <output_base_dir>/<item_id>/work/     ← file intermedi MRIQC (cancellati dopo)
Il BIDS input viene sempre creato in un tmpdir effimero.
"""

import datetime
import json
import os
import subprocess
import tempfile
from pathlib import Path

from girder_worker.app import app
from girder_worker.utils import girder_job

from ._helpers import (
    idempotency_guard,
    kill_proc,
    make_safe_progress,
    now_iso,
    resolve_dir,
    resolve_girder_url,
    set_job_cancelled,
    set_running,
    tool_version,
    update_item_fields,
)

# Default dir se non viene passato nulla
_DEFAULT_MRIQC_OUTPUT_DIR = "/data/diadema/mriqc"
_ENV_MRIQC_OUTPUT_DIR = "DIADEMA_MRIQC_OUTPUT_DIR"


@girder_job(title="DIADEMA – MRI QC")
@app.task(bind=True, acks_late=True, reject_on_worker_lost=True,
          name="girder_diadema_pipeline.tasks.run_mriqc_task")
def run_mriqc_task(task, **kwargs):
    """
    Esegue MRIQC su un file NIfTI e salva i risultati sull'item Girder.

    Parametri (kwargs):
        item_id          (str)  – ID item Girder
        file_id          (str)  – ID file NIfTI
        file_name        (str)  – nome visualizzato nel log
        participant_label(str)  – etichetta BIDS sub-XXX, default "001"
        modality         (str)  – T1w | T2w | bold | dwi, default "T1w"
        timeout          (int)  – secondi max, default 1800
        output_base_dir  (str)  – directory radice output persistente
                                  (default: $DIADEMA_MRIQC_OUTPUT_DIR o /data/diadema/mriqc)
        keep_work_dir    (bool) – conserva i file di lavoro MRIQC, default False
        job_id           (str)  – ID job Girder (idempotency + cancel)
        job_token_id     (str)  – token job (scrittura stato)
    """
    import gzip as _gzip
    import signal as _signal
    import time as _time

    import nibabel as nib
    from girder_client import GirderClient

    TASK_NAME = "run_mriqc_task"

    item_id           = kwargs.get("item_id")
    file_id           = kwargs.get("file_id")
    file_name         = kwargs.get("file_name", "unknown file")
    participant_label = kwargs.get("participant_label", "001")
    modality          = kwargs.get("modality", "T1w")
    timeout           = int(kwargs.get("timeout", 1800))
    output_base_dir   = kwargs.get("output_base_dir")
    keep_work_dir     = bool(kwargs.get("keep_work_dir", False))
    job_id            = kwargs.get("job_id")
    job_token_id      = kwargs.get("job_token_id")

    girder_api_url      = resolve_girder_url(task)
    girder_client_token = getattr(task.request, "girder_client_token", None)

    gc = GirderClient(apiUrl=girder_api_url)
    gc.token = girder_client_token

    if idempotency_guard(girder_api_url, job_id, job_token_id, TASK_NAME):
        return {"status": "skipped", "reason": "job already terminal"}

    set_running(girder_api_url, job_id, job_token_id, TASK_NAME)
    progress = make_safe_progress(task, TASK_NAME)
    progress(f"MRIQC: {file_name} ({modality}, sub-{participant_label})", total=100, current=5)

    # ── Directory di output persistente ──────────────────────────────────────
    item_output_dir = resolve_dir(
        output_base_dir, _ENV_MRIQC_OUTPUT_DIR, _DEFAULT_MRIQC_OUTPUT_DIR,
        "output_base_dir", TASK_NAME
    ) / str(item_id)
    output_dir = item_output_dir / "output"
    work_dir   = item_output_dir / "work"
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    # ─────────────────────────────────────────────────────────────────────────

    # BIDS input in tmpdir effimero (scaricato ogni volta)
    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = Path(tmpdir) / "input"
        input_dir.mkdir()

        # Download
        progress("Scaricamento file NIfTI...", current=10)
        file_info = gc.get(f"file/{file_id}")
        filename  = file_info["name"]

        (input_dir / "dataset_description.json").write_text(json.dumps({
            "Name": "DIADEMA MRI QC", "BIDSVersion": "1.6.0", "DatasetType": "raw"
        }))

        if modality == "bold":
            subdir, bids_filename = "func", f"sub-{participant_label}_task-rest_{modality}.nii.gz"
        elif modality == "dwi":
            subdir, bids_filename = "dwi", f"sub-{participant_label}_{modality}.nii.gz"
        else:
            subdir, bids_filename = "anat", f"sub-{participant_label}_{modality}.nii.gz"

        subject_dir = input_dir / f"sub-{participant_label}" / subdir
        subject_dir.mkdir(parents=True)
        nifti_path = subject_dir / bids_filename
        gc.downloadFile(file_id, str(nifti_path))

        # Comprimi se non gzip
        with open(nifti_path, "rb") as f:
            magic = f.read(2)
        if magic != b"\x1f\x8b":
            progress(f"File non compresso ({magic!r}), comprimo in-place...", current=15)
            raw = nifti_path.read_bytes()
            with _gzip.open(nifti_path, "wb") as gz:
                gz.write(raw)
            del raw

        # Check 3D (MRIQC fallisce su acquisizioni 2D thin-slab)
        img = nib.load(str(nifti_path))
        if img.shape[2] < 10:
            msg = (f"Acquisizione 2D non supportata da MRIQC: shape={img.shape[:3]}, "
                   f"solo {img.shape[2]} slice (minimo 10).")
            update_item_fields(gc, item_id,
                diadema_mriqc_status="error",
                diadema_mriqc_error={"message": msg, "timestamp": now_iso()})
            raise Exception(msg)

        progress("Avvio MRIQC (potrebbero volerci diversi minuti)...", current=30)

        mriqc_cmd = [
            "mriqc", str(input_dir), str(output_dir), "participant",
            "--participant-label", participant_label,
            "--no-sub",
            "-w", str(work_dir),
            "--verbose-reports",
        ]

        try:
            proc = subprocess.Popen(
                mriqc_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            _elapsed = 0

            while proc.poll() is None:
                _time.sleep(10)
                _elapsed += 10

                if _elapsed >= timeout:
                    kill_proc(proc, TASK_NAME)
                    raise subprocess.TimeoutExpired(mriqc_cmd, timeout)

                _cancel_requested = False
                _cancel_status    = None
                if job_id:
                    try:
                        _cancel_status = gc.get(f"job/{job_id}").get("status")
                        progress(f"[poll] job status={_cancel_status}", current=_elapsed * 50 // timeout + 30)
                        if _cancel_status in (5, 824):  # CANCELLED / CANCELING
                            _cancel_requested = True
                    except Exception as _poll_e:
                        print(f"[{TASK_NAME}] poll status non-fatal: {_poll_e}")

                if _cancel_requested:
                    progress(f"Cancellazione richiesta (status={_cancel_status}), termino MRIQC...", current=50)
                    kill_proc(proc, TASK_NAME)
                    update_item_fields(gc, item_id,
                        diadema_mriqc_status="cancelled",
                        diadema_mriqc_error={"message": "Job cancellato dall'utente", "timestamp": now_iso()})
                    set_job_cancelled(gc, job_id, TASK_NAME)
                    from celery.exceptions import Ignore
                    raise Ignore()

            stdout, stderr = proc.communicate()
            if proc.returncode != 0:
                raise Exception(f"MRIQC fallito (exit {proc.returncode}):\n{stderr[-2000:]}")

            progress("MRIQC completato, raccolta risultati...", current=80)

            # Parse output JSON
            metrics = {}
            json_files = list(output_dir.glob(f"**/sub-{participant_label}_{modality}.json"))
            if json_files:
                with open(json_files[0]) as f:
                    metrics = json.load(f)

            # Upload HTML + JSON su Girder
            progress("Upload risultati su Girder...", current=90)
            uploaded = []
            for html_file in output_dir.glob("**/*.html"):
                gc.uploadFileToItem(item_id, str(html_file))
                uploaded.append(html_file.name)
            for jf in json_files:
                gc.uploadFileToItem(item_id, str(jf))
                uploaded.append(jf.name)

            # Pulizia work dir (opzionale)
            if not keep_work_dir:
                import shutil
                try:
                    shutil.rmtree(work_dir, ignore_errors=True)
                    work_dir.mkdir(exist_ok=True)
                    progress("Work dir ripulita.", current=95)
                except Exception as _rm_e:
                    print(f"[{TASK_NAME}] pulizia work dir non-fatal: {_rm_e}")

            update_item_fields(gc, item_id,
                diadema_mriqc_results={
                    "metrics":           metrics,
                    "timestamp":         now_iso(),
                    "mriqc_version":     tool_version("mriqc"),
                    "participant_label": participant_label,
                    "modality":          modality,
                    "file_id":           file_id,
                    "file_name":         filename,
                    "output_dir":        str(output_dir),
                    "reports_uploaded":  uploaded,
                },
                diadema_mriqc_status="completed",
            )
            progress("Quality control completato!", current=100)
            return {"status": "success", "item_id": item_id, "metrics": metrics}

        except subprocess.TimeoutExpired:
            msg = f"MRIQC timeout dopo {timeout}s"
            update_item_fields(gc, item_id,
                diadema_mriqc_status="error",
                diadema_mriqc_error={"message": msg, "timestamp": now_iso()})
            raise Exception(msg)

        except Exception as exc:
            update_item_fields(gc, item_id,
                diadema_mriqc_status="error",
                diadema_mriqc_error={"message": str(exc), "timestamp": now_iso()})
            raise
