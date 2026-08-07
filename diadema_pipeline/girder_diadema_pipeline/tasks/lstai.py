"""
Task DIADEMA – LST-AI (lesion segmentation).

Supporta sia item singolo (file T1 ± FLAIR espliciti) che sessione BIDS
(ricerca automatica di T1w e FLAIR nella cartella ses-XX / sub-XX).

Parametri:
  session_folder_id (str)   – ID cartella sessione BIDS [modalità sessione]
  item_id           (str)   – ID item Girder [modalità item, backward-compat]
  file_id           (str)   – ID file T1 NIfTI [modalità item]
  flair_file_id     (str)   – ID file FLAIR (opzionale)
  participant_label (str)   – BIDS participant label (auto-detect se vuoto)
  threshold         (float) – soglia probabilità lesione 0.0–1.0 (default: 0.5)
  use_gpu           (bool)  – usa GPU se disponibile (default: True)
  output_base_dir   (str)   – directory output persistente
  timeout           (int)   – secondi max (default: 3600)
  job_id / job_token_id     – gestione stato Girder

Dipendenze worker:
  pip install lst-ai
  (richiede anche ANTs e FSL nel PATH)
"""

import logging
import os
import subprocess
import tempfile
from pathlib import Path

from celery.exceptions import Ignore

logger = logging.getLogger(__name__)

from girder_worker.app import app
from girder_worker.utils import girder_job

from ._helpers import (
    bids_find_dataset_root_from_folder,
    bids_find_modality_file,
    bids_resolve_participant_label,
    bids_resolve_participant_label_from_folder,
    bids_resolve_session_label,
    bids_upload_derivative,
    get_nifti_file_from_item,
    idempotency_guard,
    kill_proc,
    make_safe_progress,
    now_iso,
    resolve_dir,
    resolve_girder_url,
    set_job_cancelled,
    set_running,
    tool_version,
    update_diadema_tool,
    update_diadema_tool_on_folder,
)

_DEFAULT_LSTAI_OUTPUT_DIR = "/data/diadema/lstai"
_ENV_LSTAI_OUTPUT_DIR = "DIADEMA_LSTAI_OUTPUT_DIR"


@girder_job(title="DIADEMA – LST-AI")
@app.task(
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    ignore_result=True,
    name="girder_diadema_pipeline.tasks.run_lstai_task",
)
def run_lstai_task(task, **kwargs):
    import gzip as _gzip
    import time as _time

    from girder_client import GirderClient

    TASK_NAME = "run_lstai_task"

    session_folder_id = kwargs.get("session_folder_id")
    item_id = kwargs.get("item_id")
    file_id = kwargs.get("file_id")
    flair_file_id = kwargs.get("flair_file_id")
    override_t1w_file_id = kwargs.get("override_t1w_file_id") or None
    override_flair_file_id = kwargs.get("override_flair_file_id") or None
    participant_label_hint = kwargs.get("participant_label") or ""
    threshold = float(kwargs.get("threshold", 0.5))
    use_gpu = bool(kwargs.get("use_gpu", True))
    output_base_dir = kwargs.get("output_base_dir")
    timeout = int(kwargs.get("timeout", 3600))
    derivatives_root_id = kwargs.get("derivatives_root_id") or None
    job_id = kwargs.get("job_id")
    job_token_id = kwargs.get("job_token_id")

    girder_api_url = resolve_girder_url(task)
    girder_client_token = getattr(task.request, "girder_client_token", None)

    gc = GirderClient(apiUrl=girder_api_url)
    gc.token = girder_client_token

    is_session = bool(session_folder_id)

    if is_session:
        participant_label = bids_resolve_participant_label_from_folder(
            gc, session_folder_id, participant_label_hint
        )
        session_label = bids_resolve_session_label(gc, session_folder_id)
    else:
        participant_label = bids_resolve_participant_label(gc, item_id, participant_label_hint)
        session_label = None

    def _update_status(**data):
        if is_session:
            update_diadema_tool_on_folder(gc, session_folder_id, "lstai", **data)
        else:
            update_diadema_tool(gc, item_id, "lstai", **data)

    if idempotency_guard(girder_api_url, job_id, job_token_id, TASK_NAME):
        return {"status": "skipped", "reason": "job already terminal"}

    set_running(girder_api_url, job_id, job_token_id, TASK_NAME)
    progress = make_safe_progress(task, TASK_NAME)

    label_str = f"sub-{participant_label}" + (f"_ses-{session_label}" if session_label else "")
    progress(
        f"LST-AI: {label_str} ({'sessione' if is_session else 'item'})",
        total=100,
        current=5,
    )

    # ── Directory di output persistente ──────────────────────────────────────
    output_key = session_folder_id if is_session else item_id
    output_dir = resolve_dir(
        output_base_dir,
        _ENV_LSTAI_OUTPUT_DIR,
        _DEFAULT_LSTAI_OUTPUT_DIR,
        "output_base_dir",
        TASK_NAME,
    ) / str(output_key)
    output_dir.mkdir(parents=True, exist_ok=True)
    # ─────────────────────────────────────────────────────────────────────────

    derivatives_root_type = None
    if not derivatives_root_id and is_session:
        root_id, root_type = bids_find_dataset_root_from_folder(gc, session_folder_id)
        if root_id:
            derivatives_root_id = root_id
            derivatives_root_type = root_type

    with tempfile.TemporaryDirectory() as tmpdir:
        t1w_path = Path(tmpdir) / "t1w.nii.gz"
        flair_path = None
        actual_flair_file_id = None

        def _download_and_compress(dl_file_id, dest_path):
            gc.downloadFile(dl_file_id, str(dest_path))
            with open(dest_path, "rb") as f:
                if f.read(2) != b"\x1f\x8b":
                    raw = dest_path.read_bytes()
                    with _gzip.open(dest_path, "wb") as gz:
                        gz.write(raw)
                    del raw

        if is_session:
            # ── Modalità sessione: override esplicito o auto-detect ───────
            if override_t1w_file_id:
                progress("T1w (override)...", current=8)
                _download_and_compress(override_t1w_file_id, t1w_path)
            else:
                progress("Ricerca T1w nella sessione...", current=8)
                t1w_item = bids_find_modality_file(gc, session_folder_id, "T1w")
                if not t1w_item:
                    msg = f"Nessun file T1w trovato nella sessione {session_folder_id}"
                    _update_status(status="error", error={"message": msg, "timestamp": now_iso()})
                    raise Exception(msg)
                t1w_nifti = get_nifti_file_from_item(gc, str(t1w_item["_id"]))
                if not t1w_nifti:
                    msg = "Item T1w trovato ma senza file NIfTI allegato"
                    _update_status(status="error", error={"message": msg, "timestamp": now_iso()})
                    raise Exception(msg)
                t1w_dl_id = str(t1w_nifti["_id"])
                progress(f"Scaricamento T1w: {t1w_item.get('name', '')}", current=10)
                _download_and_compress(t1w_dl_id, t1w_path)

            # FLAIR: override esplicito o auto-detect
            if override_flair_file_id:
                actual_flair_file_id = override_flair_file_id
                flair_path = Path(tmpdir) / "flair.nii.gz"
                progress("FLAIR (override)...", current=13)
                _download_and_compress(override_flair_file_id, flair_path)
            else:
                flair_item = bids_find_modality_file(gc, session_folder_id, "FLAIR")
                if flair_item:
                    flair_nifti = get_nifti_file_from_item(gc, str(flair_item["_id"]))
                    if flair_nifti:
                        actual_flair_file_id = str(flair_nifti["_id"])
                        flair_path = Path(tmpdir) / "flair.nii.gz"
                        progress(f"Scaricamento FLAIR: {flair_item.get('name', '')}", current=13)
                        _download_and_compress(actual_flair_file_id, flair_path)
        else:
            # ── Modalità item singolo ─────────────────────────────────────
            if not file_id:
                msg = "file_id mancante (modalità item richiede file_id)"
                _update_status(status="error", error={"message": msg, "timestamp": now_iso()})
                raise Exception(msg)
            progress("Scaricamento T1w...", current=10)
            _download_and_compress(file_id, t1w_path)

            if flair_file_id:
                actual_flair_file_id = flair_file_id
                flair_path = Path(tmpdir) / "flair.nii.gz"
                progress("Scaricamento FLAIR...", current=13)
                _download_and_compress(flair_file_id, flair_path)

        # ── Costruzione comando lst_ai ────────────────────────────────────
        cmd = [
            "lst_ai",
            "--t1",
            str(t1w_path),
            "--output",
            str(output_dir),
            "--threshold",
            str(threshold),
        ]
        if flair_path and flair_path.exists():
            cmd += ["--flair", str(flair_path)]
        if not use_gpu:
            cmd.append("--no-gpu")

        progress(f"Avvio LST-AI: {' '.join(cmd)}", current=15)

        try:
            env = os.environ.copy()
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
                env=env,
            )

            _elapsed = 0
            _poll_interval = 15

            while proc.poll() is None:
                _time.sleep(_poll_interval)
                _elapsed += _poll_interval

                if _elapsed >= timeout:
                    kill_proc(proc, TASK_NAME)
                    raise subprocess.TimeoutExpired(cmd, timeout)

                pct = min(15 + int(_elapsed * 55 / timeout), 70)
                _cancel_requested = False
                _cancel_status = None
                if job_id:
                    try:
                        _cancel_status = gc.get(f"job/{job_id}").get("status")
                        progress(f"[poll] elapsed={_elapsed}s status={_cancel_status}", current=pct)
                        if _cancel_status in (5, 824):
                            _cancel_requested = True
                    except Exception as _poll_e:
                        logger.warning("[%s] poll status non-fatal: %s", TASK_NAME, _poll_e)

                if _cancel_requested:
                    progress(f"Cancellazione richiesta (status={_cancel_status}), termino LST-AI...", current=pct)
                    kill_proc(proc, TASK_NAME)
                    _update_status(
                        status="cancelled",
                        error={"message": "Job cancellato dall'utente", "timestamp": now_iso()},
                    )
                    set_job_cancelled(gc, job_id, TASK_NAME)
                    raise Ignore()

            if proc.returncode != 0:
                raise Exception(f"LST-AI fallito (exit {proc.returncode})")

            progress("LST-AI completato, raccolta risultati...", current=75)

            # ── Parse risultati ────────────────────────────────────────────
            lesion_count = None
            total_volume_ml = None
            lesion_mask_path = None

            # lst_ai genera typicamente: lesion_mask.nii.gz, report.json
            for f in output_dir.iterdir():
                if "lesion" in f.name.lower() and f.suffix in (".gz", ".nii"):
                    lesion_mask_path = f
                if f.name.endswith(".json"):
                    import json
                    try:
                        with open(f) as jf:
                            report = json.load(jf)
                        lesion_count = report.get("lesion_count") or report.get("n_lesions")
                        total_volume_ml = report.get("total_volume_ml") or report.get("volume_ml")
                    except Exception:
                        pass

            # ── Upload derivatives ─────────────────────────────────────────
            progress("Upload risultati su Girder (BIDS derivatives)...", current=85)
            uploaded = []
            derivative_item_ids = []
            bids_anchor = None if is_session else item_id

            for out_file in output_dir.iterdir():
                if out_file.is_file():
                    iid = bids_upload_derivative(
                        gc,
                        bids_anchor,
                        out_file,
                        datatype="anat",
                        participant_label=participant_label,
                        derivatives_root_id=derivatives_root_id,
                        derivatives_root_type=derivatives_root_type,
                        pipeline_name="lstai",
                    )
                    uploaded.append(out_file.name)
                    if iid:
                        derivative_item_ids.append(iid)

            results = {
                "timestamp": now_iso(),
                "lstai_version": tool_version("lst_ai"),
                "participant_label": participant_label,
                "session_label": session_label,
                "threshold": threshold,
                "flair_used": actual_flair_file_id is not None,
                "lesion_count": lesion_count,
                "total_volume_ml": total_volume_ml,
                "files_uploaded": uploaded,
                "derivative_item_ids": derivative_item_ids,
            }
            if not is_session:
                results["file_id"] = file_id
                results["flair_file_id"] = actual_flair_file_id
            else:
                results["session_folder_id"] = session_folder_id

            _update_status(results=results, status="completed")
            progress("LST-AI completato!", current=100)
            return {
                "status": "success",
                "lesion_count": lesion_count,
                "total_volume_ml": total_volume_ml,
            }

        except Ignore:
            raise

        except subprocess.TimeoutExpired:
            msg = f"LST-AI timeout dopo {timeout}s"
            logger.error("[%s] %s", TASK_NAME, msg)
            _update_status(status="error", error={"message": msg, "timestamp": now_iso()})
            raise Exception(msg)

        except Exception as exc:
            logger.exception("[%s] Errore non gestito: %s", TASK_NAME, exc)
            _update_status(status="error", error={"message": str(exc), "timestamp": now_iso()})
            raise
