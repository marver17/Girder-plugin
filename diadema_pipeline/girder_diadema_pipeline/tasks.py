"""
ATTENZIONE: questo file è stato sostituito dal package tasks/

  girder_diadema_pipeline/tasks/
      __init__.py      ← re-export di tutti i task
      _helpers.py      ← helper condivisi
      mriqc.py         ← run_mriqc_task
      freesurfer.py    ← run_freesurfer_task
      lstai.py         ← run_lstai_task

Python preferisce il package (tasks/) al modulo (tasks.py) con lo stesso nome,
quindi questo file non viene mai importato. È mantenuto solo per la cronologia git.
"""


import datetime
import json
import os
import subprocess
import tempfile
from pathlib import Path

from girder_worker.app import app
from girder_worker.utils import girder_job


# ── Helpers condivisi ─────────────────────────────────────────────────────────

def _resolve_girder_url(task):
    url = getattr(task.request, "girder_api_url", "http://localhost:8080/api/v1")
    env = os.environ.get("GIRDER_API_URL")
    if env and ("localhost" in url or "127.0.0.1" in url):
        url = env
    return url


def _idempotency_guard(girder_api_url, job_id, job_token_id, task_name):
    from girder_client import GirderClient
    if not (job_id and job_token_id):
        return False
    try:
        gc = GirderClient(apiUrl=girder_api_url)
        gc.token = job_token_id
        status = gc.get(f"job/{job_id}").get("status", 0)
        if status in (3, 4, 5):
            print(f"[{task_name}] Job {job_id} già terminale ({status}), skip")
            return True
    except Exception as e:
        print(f"[{task_name}] idempotency check non-fatal: {e}")
    return False


def _set_running(girder_api_url, job_id, job_token_id, task_name):
    from girder_client import GirderClient
    if not (job_id and job_token_id):
        return
    try:
        gc = GirderClient(apiUrl=girder_api_url)
        gc.token = job_token_id
        gc.put(f"job/{job_id}", parameters={"status": 2})
        print(f"[{task_name}] Job {job_id} → RUNNING")
    except Exception as e:
        print(f"[{task_name}] WARNING set RUNNING: {e}")


def _make_safe_progress(task, task_name):
    def safe_progress(message, current=None, total=None):
        print(f"[{task_name}] {message}")
        try:
            # write() fa streaming in tempo reale nel log del job Girder
            task.job_manager.write(f"{message}\n")
        except Exception:
            pass
        try:
            kw = {"message": message}
            if current is not None:
                kw["current"] = current
            if total is not None:
                kw["total"] = total
            task.job_manager.updateProgress(**kw)
        except Exception:
            pass
    return safe_progress


def _update_item_fields(gc, item_id, **fields):
    try:
        gc.put(f"item/{item_id}/metadata", json=fields)
    except Exception as e:
        print(f"[diadema] WARNING update item {item_id}: {e}")


def _get_mriqc_version():
    try:
        r = subprocess.run(["mriqc", "--version"], capture_output=True, text=True, timeout=10)
        return r.stdout.strip()
    except Exception:
        return "unknown"


# ── MRI QC (MRIQC) ────────────────────────────────────────────────────────────

@girder_job(title="DIADEMA – MRI QC")
@app.task(bind=True, acks_late=True, reject_on_worker_lost=True)
def run_mriqc_task(task, **kwargs):
    """Esegue MRIQC su un file NIfTI e salva i risultati sull'item Girder."""
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
    job_id            = kwargs.get("job_id")
    job_token_id      = kwargs.get("job_token_id")
    timeout           = kwargs.get("timeout", 1800)

    girder_api_url      = _resolve_girder_url(task)
    girder_client_token = getattr(task.request, "girder_client_token", None)

    gc = GirderClient(apiUrl=girder_api_url)
    gc.token = girder_client_token

    if _idempotency_guard(girder_api_url, job_id, job_token_id, TASK_NAME):
        return {"status": "skipped", "reason": "job already terminal"}

    _set_running(girder_api_url, job_id, job_token_id, TASK_NAME)
    safe_progress = _make_safe_progress(task, TASK_NAME)
    safe_progress(f"MRIQC: {file_name} ({modality}, sub-{participant_label})", total=100, current=5)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        input_dir  = tmpdir_path / "input"
        output_dir = tmpdir_path / "output"
        work_dir   = tmpdir_path / "work"
        input_dir.mkdir(); output_dir.mkdir(); work_dir.mkdir()

        # Download
        safe_progress("Scaricamento file NIfTI...", current=10)
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
            raw = nifti_path.read_bytes()
            with _gzip.open(nifti_path, "wb") as gz:
                gz.write(raw)

        # Check 3D
        img = nib.load(str(nifti_path))
        if img.shape[2] < 10:
            msg = f"Acquisizione 2D non supportata da MRIQC: shape={img.shape[:3]}"
            _update_item_fields(gc, item_id,
                diadema_mriqc_status="error",
                diadema_mriqc_error={"message": msg,
                                     "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()})
            raise Exception(msg)

        # Esegui MRIQC
        safe_progress("Avvio MRIQC (potrebbe richiedere diversi minuti)...", current=30)
        mriqc_cmd = [
            "mriqc", str(input_dir), str(output_dir), "participant",
            "--participant-label", participant_label,
            "--no-sub", "-w", str(work_dir), "--verbose-reports",
        ]
        try:
            mriqc_proc = subprocess.Popen(
                mriqc_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, start_new_session=True,
            )

            _elapsed = 0
            while mriqc_proc.poll() is None:
                _time.sleep(10)
                _elapsed += 10

                # Timeout esplicito
                if _elapsed >= timeout:
                    os.killpg(os.getpgid(mriqc_proc.pid), _signal.SIGTERM)
                    mriqc_proc.wait()
                    raise subprocess.TimeoutExpired(mriqc_cmd, timeout)

                # Check cancellazione: il flag è FUORI dal try/except HTTP
                # così raise Ignore() non viene inghiottito dall'except.
                _cancel_requested = False
                _cancel_status = None
                if job_id:
                    try:
                        _job_state = gc.get(f"job/{job_id}")
                        _cancel_status = _job_state.get("status")
                        print(f"[{TASK_NAME}] poll job {job_id}: status={_cancel_status}")
                        if _cancel_status in (5, 824):  # CANCELLED / CANCELING
                            _cancel_requested = True
                    except Exception as _poll_e:
                        print(f"[{TASK_NAME}] poll status non-fatal: {_poll_e}")

                # Kill ed Ignore() sono FUORI dal try/except HTTP
                if _cancel_requested:
                    print(f"[{TASK_NAME}] Job {job_id} in stato cancel ({_cancel_status}), termino MRIQC...")
                    try:
                        os.killpg(os.getpgid(mriqc_proc.pid), _signal.SIGTERM)
                        mriqc_proc.wait(timeout=30)
                    except Exception as _kill_e:
                        print(f"[{TASK_NAME}] killpg non-fatal: {_kill_e}")
                        try:
                            mriqc_proc.kill()
                            mriqc_proc.wait(timeout=10)
                        except Exception:
                            pass
                    _update_item_fields(gc, item_id,
                        diadema_mriqc_status="error",
                        diadema_mriqc_error={"message": "Job cancellato dall'utente",
                                             "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()})
                    try:
                        gc.put(f"job/{job_id}", parameters={"status": 5})
                        print(f"[{TASK_NAME}] Job {job_id} → CANCELLED")
                    except Exception as _ce:
                        print(f"[{TASK_NAME}] WARNING set CANCELLED: {_ce}")
                    from celery.exceptions import Ignore
                    raise Ignore()

            stdout, stderr = mriqc_proc.communicate()
            if mriqc_proc.returncode != 0:
                raise Exception(f"MRIQC fallito (code {mriqc_proc.returncode}): {stderr[-2000:]}")

            safe_progress("MRIQC completato, raccolta risultati...", current=80)

            # Parse output
            metrics = {}
            json_files = list(output_dir.glob(f"**/sub-{participant_label}_{modality}.json"))
            if json_files:
                with open(json_files[0]) as f:
                    metrics = json.load(f)

            # Upload report
            safe_progress("Upload risultati su Girder...", current=90)
            uploaded = []
            for html_file in output_dir.glob("**/*.html"):
                gc.uploadFileToItem(item_id, str(html_file))
                uploaded.append(html_file.name)
            for jf in json_files:
                gc.uploadFileToItem(item_id, str(jf))
                uploaded.append(jf.name)

            _update_item_fields(gc, item_id,
                diadema_mriqc_results={
                    "metrics": metrics,
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "mriqc_version": _get_mriqc_version(),
                    "participant_label": participant_label,
                    "modality": modality,
                    "file_id": file_id,
                    "file_name": filename,
                    "reports_uploaded": uploaded,
                },
                diadema_mriqc_status="completed",
            )
            safe_progress("Quality control completato!", current=100)
            return {"status": "success", "item_id": item_id, "metrics": metrics}

        except subprocess.TimeoutExpired:
            _update_item_fields(gc, item_id,
                diadema_mriqc_status="error",
                diadema_mriqc_error={"message": f"MRIQC timeout dopo {timeout}s",
                                     "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()})
            raise Exception(f"MRIQC timeout dopo {timeout} secondi")

        except Exception as _exc:
            # salva l'errore sull'item e rilancia perché @girder_job gestisce il job failure
            _update_item_fields(gc, item_id,
                diadema_mriqc_status="error",
                diadema_mriqc_error={"message": str(_exc),
                                     "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()})
            raise


# ── FreeSurfer recon-all ───────────────────────────────────────────────────────

@girder_job(title="DIADEMA – FreeSurfer")
@app.task(bind=True, acks_late=True, reject_on_worker_lost=True)
def run_freesurfer_task(task, **kwargs):
    """Esegue FreeSurfer recon-all. TODO: implementazione completa."""
    TASK_NAME = "run_freesurfer_task"
    job_id, job_token_id = kwargs.get("job_id"), kwargs.get("job_token_id")
    girder_api_url = _resolve_girder_url(task)
    if _idempotency_guard(girder_api_url, job_id, job_token_id, TASK_NAME):
        return {"status": "skipped", "reason": "job already terminal"}
    _set_running(girder_api_url, job_id, job_token_id, TASK_NAME)
    raise NotImplementedError("run_freesurfer_task: implementazione backend pendente")


# ── LST-AI ────────────────────────────────────────────────────────────────────

@girder_job(title="DIADEMA – LST-AI")
@app.task(bind=True, acks_late=True, reject_on_worker_lost=True)
def run_lstai_task(task, **kwargs):
    """Esegue LST-AI lesion segmentation. TODO: implementazione completa."""
    TASK_NAME = "run_lstai_task"
    job_id, job_token_id = kwargs.get("job_id"), kwargs.get("job_token_id")
    girder_api_url = _resolve_girder_url(task)
    if _idempotency_guard(girder_api_url, job_id, job_token_id, TASK_NAME):
        return {"status": "skipped", "reason": "job already terminal"}
    _set_running(girder_api_url, job_id, job_token_id, TASK_NAME)
    raise NotImplementedError("run_lstai_task: implementazione backend pendente")
