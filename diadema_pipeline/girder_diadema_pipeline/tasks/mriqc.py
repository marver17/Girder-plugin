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
import logging
import math
import os
import subprocess
import tempfile
from pathlib import Path

from celery.exceptions import Ignore

logger = logging.getLogger(__name__)

from girder_worker.app import app
from girder_worker.utils import girder_job

from ._helpers import (
    bids_detect_modality,
    bids_find_dataset_root_from_folder,
    bids_list_session_files,
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

def _sanitize_floats(obj):
    """Sostituisce NaN/Inf con None per garantire serializzazione JSON valida.
    Le metriche MRIQC possono contenere NaN quando un indicatore non è calcolabile.
    json.dumps() (usato internamente da requests/GirderClient) rifiuta NaN/Inf."""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _sanitize_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_floats(v) for v in obj]
    return obj


# Default dir se non viene passato nulla
_DEFAULT_MRIQC_OUTPUT_DIR = "/data/diadema/mriqc"
_ENV_MRIQC_OUTPUT_DIR = "DIADEMA_MRIQC_OUTPUT_DIR"


@girder_job(title="DIADEMA – MRI QC")
@app.task(
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    name="girder_diadema_pipeline.tasks.run_mriqc_task",
)
def run_mriqc_task(task, **kwargs):
    """
    Esegue MRIQC su un file NIfTI (item singolo) o su una sessione BIDS (cartella).

    Parametri (kwargs):
        item_id             (str)  – ID item Girder [modalità item]
        file_id             (str)  – ID file NIfTI [modalità item]
        file_name           (str)  – nome visualizzato nel log [modalità item]
        session_folder_id   (str)  – ID cartella sessione BIDS [modalità sessione]
        participant_label   (str)  – etichetta BIDS sub-XXX, default auto-detect
        modality            (str)  – T1w | T2w | bold | dwi (item) o filtro (sessione)
        modality_filter     (str)  – filtro modalità per modalità sessione (vuoto = tutte)
        timeout             (int)  – secondi max, default 1800
        output_base_dir     (str)  – directory radice output persistente
        keep_work_dir       (bool) – conserva i file di lavoro MRIQC, default False
        derivatives_root_id (str)  – ID folder radice dataset BIDS (override)
        job_id              (str)  – ID job Girder
        job_token_id        (str)  – token job
    """
    import gzip as _gzip
    import time as _time

    import nibabel as nib
    from girder_client import GirderClient

    TASK_NAME = "run_mriqc_task"

    session_folder_id = kwargs.get("session_folder_id")
    item_id = kwargs.get("item_id")
    file_id = kwargs.get("file_id")
    file_name = kwargs.get("file_name", "unknown file")
    participant_label_hint = kwargs.get("participant_label") or ""
    modality = kwargs.get("modality", "T1w")
    modality_filter = kwargs.get("modality_filter", "")
    timeout = int(kwargs.get("timeout", 1800))
    output_base_dir = kwargs.get("output_base_dir")
    keep_work_dir = bool(kwargs.get("keep_work_dir", False))
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
            update_diadema_tool_on_folder(gc, session_folder_id, "mriqc", **data)
        else:
            update_diadema_tool(gc, item_id, "mriqc", **data)

    if idempotency_guard(girder_api_url, job_id, job_token_id, TASK_NAME):
        return {"status": "skipped", "reason": "job already terminal"}

    set_running(girder_api_url, job_id, job_token_id, TASK_NAME)
    progress = make_safe_progress(task, TASK_NAME)

    label_str = f"sub-{participant_label}" + (f"_ses-{session_label}" if session_label else "")
    progress(
        f"MRIQC: {label_str} ({'sessione' if is_session else file_name})",
        total=100,
        current=5,
    )

    # ── Directory di output persistente ──────────────────────────────────────
    output_key = session_folder_id if is_session else item_id
    item_output_dir = resolve_dir(
        output_base_dir,
        _ENV_MRIQC_OUTPUT_DIR,
        _DEFAULT_MRIQC_OUTPUT_DIR,
        "output_base_dir",
        TASK_NAME,
    ) / str(output_key)
    output_dir = item_output_dir / "output"
    work_dir = item_output_dir / "work"
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    # ─────────────────────────────────────────────────────────────────────────

    derivatives_root_type = None
    if not derivatives_root_id and is_session:
        root_id, root_type = bids_find_dataset_root_from_folder(gc, session_folder_id)
        if root_id:
            derivatives_root_id = root_id
            derivatives_root_type = root_type  # "folder" o "collection"

    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = Path(tmpdir) / "input"
        input_dir.mkdir()

        (input_dir / "dataset_description.json").write_text(
            json.dumps(
                {"Name": "DIADEMA MRI QC", "BIDSVersion": "1.6.0", "DatasetType": "raw"}
            )
        )

        # ── Costruzione struttura BIDS input ──────────────────────────────────
        if is_session:
            # Recupera tutti i NIfTI dalla cartella sessione
            progress("Elenco file NIfTI nella sessione...", current=8)
            session_files = bids_list_session_files(gc, session_folder_id)
            if not session_files:
                msg = f"Nessun file NIfTI trovato nella sessione {session_folder_id}"
                _update_status(status="error", error={"message": msg, "timestamp": now_iso()})
                raise Exception(msg)

            downloaded_files = []  # list of (file_item, nifti_path, modality, datatype)

            for file_item in session_files:
                fname = file_item.get("name", "")
                detected_mod, detected_dtype = bids_detect_modality(fname)
                if not detected_mod:
                    logger.warning("[%s] Modalità non rilevata per %s, skip", TASK_NAME, fname)
                    continue
                if modality_filter and detected_mod.lower() != modality_filter.lower():
                    continue

                # Costruisce path BIDS corretto
                if detected_mod.lower() == "bold":
                    bids_stem = f"sub-{participant_label}"
                    if session_label:
                        bids_stem += f"_ses-{session_label}"
                    bids_stem += f"_task-rest_{detected_mod}"
                else:
                    bids_stem = f"sub-{participant_label}"
                    if session_label:
                        bids_stem += f"_ses-{session_label}"
                    bids_stem += f"_{detected_mod}"

                subpath = f"sub-{participant_label}"
                if session_label:
                    subpath += f"/ses-{session_label}"
                subpath += f"/{detected_dtype}"

                dest_dir = input_dir / subpath
                dest_dir.mkdir(parents=True, exist_ok=True)
                nifti_path = dest_dir / f"{bids_stem}.nii.gz"

                nifti_file = get_nifti_file_from_item(gc, str(file_item["_id"]))
                if not nifti_file:
                    continue
                dl_file_id = str(nifti_file["_id"])
                gc.downloadFile(dl_file_id, str(nifti_path))

                # Comprimi se non gzip
                with open(nifti_path, "rb") as f:
                    magic = f.read(2)
                if magic != b"\x1f\x8b":
                    raw = nifti_path.read_bytes()
                    import gzip as _gzip2
                    with _gzip2.open(nifti_path, "wb") as gz:
                        gz.write(raw)
                    del raw

                downloaded_files.append((file_item, nifti_path, detected_mod, detected_dtype))
                progress(f"Scaricato {fname} ({detected_mod})", current=10 + len(downloaded_files) * 3)

            if not downloaded_files:
                msg = "Nessun file NIfTI con modalità riconosciuta trovato nella sessione"
                _update_status(status="error", error={"message": msg, "timestamp": now_iso()})
                raise Exception(msg)

        else:
            # Modalità item singolo (comportamento originale)
            progress("Scaricamento file NIfTI...", current=10)
            file_info = gc.get(f"file/{file_id}")
            filename = file_info["name"]

            if modality == "bold":
                subdir, bids_filename = (
                    "func",
                    f"sub-{participant_label}_task-rest_{modality}.nii.gz",
                )
            elif modality == "dwi":
                subdir, bids_filename = "dwi", f"sub-{participant_label}_{modality}.nii.gz"
            else:
                subdir, bids_filename = "anat", f"sub-{participant_label}_{modality}.nii.gz"

            subject_dir = input_dir / f"sub-{participant_label}" / subdir
            subject_dir.mkdir(parents=True)
            nifti_path = subject_dir / bids_filename
            gc.downloadFile(file_id, str(nifti_path))

            with open(nifti_path, "rb") as f:
                magic = f.read(2)
            if magic != b"\x1f\x8b":
                progress(f"File non compresso ({magic!r}), comprimo in-place...", current=15)
                raw = nifti_path.read_bytes()
                with _gzip.open(nifti_path, "wb") as gz:
                    gz.write(raw)
                del raw

            img = nib.load(str(nifti_path))
            if img.shape[2] < 10:
                msg = (
                    f"Acquisizione 2D non supportata da MRIQC: shape={img.shape[:3]}, "
                    f"solo {img.shape[2]} slice (minimo 10)."
                )
                _update_status(status="error", error={"message": msg, "timestamp": now_iso()})
                raise Exception(msg)

        mriqc_cmd = [
            "mriqc",
            str(input_dir),
            str(output_dir),
            "participant",
            "--participant-label",
            participant_label,
            "--no-sub",
            "-w",
            str(work_dir),
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
                _cancel_status = None
                if job_id:
                    try:
                        _cancel_status = gc.get(f"job/{job_id}").get("status")
                        progress(
                            f"[poll] job status={_cancel_status}",
                            current=_elapsed * 50 // timeout + 30,
                        )
                        if _cancel_status in (5, 824):
                            _cancel_requested = True
                    except Exception as _poll_e:
                        logger.warning("[%s] poll status non-fatal: %s", TASK_NAME, _poll_e)

                if _cancel_requested:
                    progress(
                        f"Cancellazione richiesta (status={_cancel_status}), termino MRIQC...",
                        current=50,
                    )
                    kill_proc(proc, TASK_NAME)
                    _update_status(
                        status="cancelled",
                        error={"message": "Job cancellato dall'utente", "timestamp": now_iso()},
                    )
                    set_job_cancelled(gc, job_id, TASK_NAME)
                    raise Ignore()

            stdout, stderr = proc.communicate()
            if proc.returncode != 0:
                raise Exception(f"MRIQC fallito (exit {proc.returncode}):\n{stderr[-2000:]}")

            progress("MRIQC completato, raccolta risultati...", current=80)

            # ── Parse risultati e upload derivatives ──────────────────────────
            progress("Upload risultati su Girder (BIDS derivatives)...", current=90)
            uploaded = []
            derivative_item_ids = []

            if is_session:
                per_modality_metrics = {}
                mriqc_ver = tool_version("mriqc")

                # Log output directory per debug
                all_output = list(output_dir.glob("**/*"))
                progress(
                    f"Output MRIQC: {len(all_output)} file/dir in {output_dir}",
                    current=82,
                )
                logger.info("[%s] Output dir contents: %s", TASK_NAME,
                            [str(p.relative_to(output_dir)) for p in all_output if p.is_file()][:20])

                # Derivati root
                logger.info("[%s] derivatives_root_id=%s type=%s",
                            TASK_NAME, derivatives_root_id, derivatives_root_type)

                for file_item, nifti_path, detected_mod, detected_dtype in downloaded_files:
                    json_files = list(output_dir.glob(f"**/*_{detected_mod}.json"))
                    html_files = list(output_dir.glob(f"**/*_{detected_mod}*.html"))
                    logger.info("[%s] mod=%s json=%d html=%d",
                                TASK_NAME, detected_mod, len(json_files), len(html_files))

                    if json_files:
                        with open(json_files[0]) as f:
                            per_modality_metrics[detected_mod] = _sanitize_floats(json.load(f))

                    # Upload HTML e JSON come BIDS derivatives
                    for html_file in html_files:
                        did = bids_upload_derivative(
                            gc, None, html_file,
                            datatype=detected_dtype,
                            participant_label=participant_label,
                            derivatives_root_id=derivatives_root_id,
                            derivatives_root_type=derivatives_root_type,
                            pipeline_name="mriqc",
                        )
                        uploaded.append(html_file.name)
                        if did:
                            derivative_item_ids.append(did)
                    for jf in json_files:
                        did = bids_upload_derivative(
                            gc, None, jf,
                            datatype=detected_dtype,
                            participant_label=participant_label,
                            derivatives_root_id=derivatives_root_id,
                            derivatives_root_type=derivatives_root_type,
                            pipeline_name="mriqc",
                        )
                        uploaded.append(jf.name)
                        if did:
                            derivative_item_ids.append(did)

                    # Aggiorna anche l'item NIfTI singolo in modo che il widget
                    # del viewer NIfTI possa mostrare le metriche per quel file
                    item_metrics = per_modality_metrics.get(detected_mod, {})
                    update_diadema_tool(
                        gc, str(file_item["_id"]), "mriqc",
                        status="completed",
                        results={
                            "metrics": item_metrics,
                            "modality": detected_mod,
                            "timestamp": now_iso(),
                            "mriqc_version": mriqc_ver,
                            "participant_label": participant_label,
                            "session_label": session_label,
                            "session_folder_id": session_folder_id,
                            "reports_uploaded": [f for f in uploaded
                                                 if f.endswith(".html") or f.endswith(".json")],
                            "derivative_item_ids": derivative_item_ids,
                        },
                    )

                progress(f"Uploaded: {len(uploaded)} file, derivati: {len(derivative_item_ids)}", current=95)

                _update_status(
                    results={
                        "modalities": per_modality_metrics,
                        "timestamp": now_iso(),
                        "mriqc_version": mriqc_ver,
                        "participant_label": participant_label,
                        "session_label": session_label,
                        "session_folder_id": session_folder_id,
                        "files_count": len(downloaded_files),
                        "reports_uploaded": uploaded,
                        "derivative_item_ids": derivative_item_ids,
                    },
                    status="completed",
                )
                progress("Quality control sessione completato!", current=100)
                return {"status": "success", "session_folder_id": session_folder_id, "modalities": list(per_modality_metrics.keys())}

            else:
                # Modalità item singolo
                metrics = {}
                json_files = list(output_dir.glob(f"**/sub-{participant_label}_{modality}.json"))
                if json_files:
                    with open(json_files[0]) as f:
                        metrics = _sanitize_floats(json.load(f))

                if modality == "bold":
                    bids_datatype = "func"
                elif modality == "dwi":
                    bids_datatype = "dwi"
                else:
                    bids_datatype = "anat"

                for html_file in output_dir.glob("**/*.html"):
                    did = bids_upload_derivative(
                        gc, item_id, html_file,
                        datatype=bids_datatype,
                        participant_label=participant_label,
                        derivatives_root_id=derivatives_root_id,
                        pipeline_name="mriqc",
                    )
                    uploaded.append(html_file.name)
                    if did:
                        derivative_item_ids.append(did)
                for jf in json_files:
                    did = bids_upload_derivative(
                        gc, item_id, jf,
                        datatype=bids_datatype,
                        participant_label=participant_label,
                        derivatives_root_id=derivatives_root_id,
                        pipeline_name="mriqc",
                    )
                    uploaded.append(jf.name)
                    if did:
                        derivative_item_ids.append(did)

                _update_status(
                    results={
                        "metrics": metrics,
                        "timestamp": now_iso(),
                        "mriqc_version": tool_version("mriqc"),
                        "participant_label": participant_label,
                        "modality": modality,
                        "file_id": file_id,
                        "file_name": filename,
                        "output_dir": str(output_dir),
                        "reports_uploaded": uploaded,
                        "derivative_item_ids": derivative_item_ids,
                    },
                    status="completed",
                )
                progress("Quality control completato!", current=100)
                return {"status": "success", "item_id": item_id, "metrics": metrics}

        except Ignore:
            raise

        except subprocess.TimeoutExpired:
            msg = f"MRIQC timeout dopo {timeout}s"
            logger.error("[%s] %s", TASK_NAME, msg)
            _update_status(status="error", error={"message": msg, "timestamp": now_iso()})
            raise Exception(msg)

        except Exception as exc:
            logger.exception("[%s] Errore non gestito: %s", TASK_NAME, exc)
            _update_status(status="error", error={"message": str(exc), "timestamp": now_iso()})
            raise

        finally:
            if not keep_work_dir:
                import shutil
                try:
                    shutil.rmtree(work_dir, ignore_errors=True)
                    work_dir.mkdir(exist_ok=True)
                except Exception as _rm_e:
                    logger.warning("[%s] pulizia work dir non-fatal: %s", TASK_NAME, _rm_e)
