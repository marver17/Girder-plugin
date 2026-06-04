"""
Task DIADEMA – FreeSurfer recon-all.

Directory configurabili (ordine di priorità):
  1. Parametro esplicito nella chiamata   → subjects_dir=...
  2. Variabile d'ambiente nel container   → DIADEMA_SUBJECTS_DIR
  3. Default hardcoded                    → /data/diadema/subjects

Il soggetto viene creato come:
  <subjects_dir>/diadema_{item_id[:12]}/

Parametri recon-all supportati:
  directive        str  : -all | -autorecon1 | -autorecon2 | -autorecon3 |
                          -autorecon2-cp | -autorecon2-wm   (default: -all)
  hemi             str  : both | lh | rh   (default: both)
  openmp_threads   int  : thread OpenMP 1-16   (default: 4)
  mprage           bool : -mprage (scanner MGH MP-RAGE protocol)   (default: False)
  wsatlas          bool : -wsatlas (skull stripping con atlas)   (default: False)
  deface           bool : -deface   (default: False)
  no_isrunning     bool : -no-isrunning (salta check "già in esecuzione",
                          raccomandato in container)   (default: True)
  extra_flags      str  : flag aggiuntivi passati verbatim a recon-all
  subjects_dir     str  : override SUBJECTS_DIR
  keep_subjects_dir bool: non cancellare la dir soggetto dopo upload (default: True)
  timeout          int  : secondi max, default 14400 (4 ore)

Output caricato su Girder:
  - aseg.stats        → volumi strutture subcorticali
  - lh/rh.aparc.stats → parcellazione corticale (atlas Desikan-Killiany)
  - lh/rh.aparc.a2009s.stats → parcellazione Destrieux (se presente)
  - recon-all.log     → log completo

Metadati salvati sull'item:
  diadema_freesurfer_results  → misure globali + volumi subcorticali + cortex
  diadema_freesurfer_status   → "completed" | "error" | "cancelled"
  diadema_freesurfer_error    → messaggio di errore (solo su errore)
"""

import datetime
import json
import logging
import os
import shlex
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

_DEFAULT_SUBJECTS_DIR = "/data/diadema/subjects"
_ENV_SUBJECTS_DIR = "DIADEMA_SUBJECTS_DIR"

# Direttive valide recon-all
_VALID_DIRECTIVES = {
    "-all",
    "-autorecon-all",
    "-autorecon1",
    "-autorecon2",
    "-autorecon2-cp",
    "-autorecon2-wm",
    "-autorecon3",
    "-autorecon-pial",
}


# ── Parser file .stats ────────────────────────────────────────────────────────


def _parse_global_measures(stats_path):
    """
    Estrae le righe '# Measure Name, , Description, Value, Units'
    da un file .stats di FreeSurfer.
    """
    measures = {}
    try:
        with open(stats_path) as f:
            for line in f:
                if "# Measure" not in line:
                    continue
                # formato: # Measure BrainSeg, BrainSegVol, Brain Segmentation Volume, 1234567.0, mm^3
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 4:
                    name = parts[0].replace("# Measure", "").strip()
                    try:
                        measures[name] = float(parts[3])
                    except (ValueError, IndexError):
                        pass
    except Exception as exc:
        logger.warning("[freesurfer] parse_global_measures %s: %s", stats_path, exc)
    return measures


def _parse_aseg_stats(stats_path):
    """
    Restituisce dict {StructName: volume_mm3} da aseg.stats.
    Formato colonne: Index SegId NVoxels Volume_mm3 StructName Mean StdDev Min Max Range
    """
    volumes = {}
    try:
        with open(stats_path) as f:
            for line in f:
                if line.startswith("#") or not line.strip():
                    continue
                parts = line.split()
                if len(parts) >= 5:
                    try:
                        volumes[parts[4]] = float(parts[3])
                    except (ValueError, IndexError):
                        pass
    except Exception as exc:
        logger.warning("[freesurfer] parse_aseg_stats %s: %s", stats_path, exc)
    return volumes


def _parse_aparc_stats(stats_path):
    """
    Restituisce dict {region: {NumVert, SurfArea, GrayVol, ThickAvg, ThickStd}}
    da ?h.aparc.stats.
    Formato colonne: StructName NumVert SurfArea GrayVol ThickAvg ThickStd MeanCurv GausCurv FoldInd CurvInd
    """
    regions = {}
    try:
        with open(stats_path) as f:
            for line in f:
                if line.startswith("#") or not line.strip():
                    continue
                parts = line.split()
                if len(parts) >= 10:
                    regions[parts[0]] = {
                        "NumVert": int(parts[1]),
                        "SurfArea": int(parts[2]),
                        "GrayVol": int(parts[3]),
                        "ThickAvg": float(parts[4]),
                        "ThickStd": float(parts[5]),
                    }
    except Exception as exc:
        logger.warning("[freesurfer] parse_aparc_stats %s: %s", stats_path, exc)
    return regions


def _collect_stats(subject_dir):
    """
    Legge tutti i file stats disponibili nella directory soggetto.
    Restituisce un dict con misure globali, subcorticali e corticali.
    """
    stats_dir = subject_dir / "stats"
    result = {"global": {}, "subcortical": {}, "cortical": {"lh": {}, "rh": {}}}

    # aseg.stats – misure globali + volumi subcorticali
    aseg = stats_dir / "aseg.stats"
    if aseg.exists():
        result["global"].update(_parse_global_measures(aseg))
        result["subcortical"] = _parse_aseg_stats(aseg)

    # aparc.stats (Desikan-Killiany) per ciascun emisfero
    for hemi in ("lh", "rh"):
        aparc = stats_dir / f"{hemi}.aparc.stats"
        if aparc.exists():
            result["cortical"][hemi]["DK"] = _parse_aparc_stats(aparc)
            result["global"].update(
                {f"{hemi}_{k}": v for k, v in _parse_global_measures(aparc).items()}
            )

        # aparc.a2009s.stats (Destrieux) – presente solo dopo autorecon3
        aparc2009 = stats_dir / f"{hemi}.aparc.a2009s.stats"
        if aparc2009.exists():
            result["cortical"][hemi]["Destrieux"] = _parse_aparc_stats(aparc2009)

    return result


# ── Sub-task asincrono per upload risultati ──────────────────────────────────


@girder_job(title="DIADEMA – FreeSurfer Upload")
@app.task(
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    name="girder_diadema_pipeline.tasks.upload_freesurfer_results",
)
def upload_freesurfer_results(task, **kwargs):
    """
    Sub-task dedicato all'upload dei risultati FreeSurfer su Girder.
    Viene dispatchato da run_freesurfer_task al termine di recon-all
    liberando il worker principale durante l'upload di file grandi.

    kwargs:
        item_id           (str)  – ID item Girder
        subject_dir       (str)  – Path assoluto della directory soggetto
        stats             (dict) – Già parsato da _collect_stats()
        result_meta       (dict) – Metadati extra per diadema_freesurfer_results
        keep_subjects_dir (bool) – Se False, rimuove subject_dir dopo l'upload
    """
    import tempfile

    from girder_client import GirderClient

    TASK_NAME = "upload_freesurfer_results"

    item_id = kwargs.get("item_id")
    session_folder_id = kwargs.get("session_folder_id")
    subject_dir_str = kwargs.get("subject_dir")
    stats = kwargs.get("stats", {})
    result_meta = kwargs.get("result_meta", {})
    keep_subjects_dir = bool(kwargs.get("keep_subjects_dir", True))
    derivatives_root_id = kwargs.get("derivatives_root_id") or None
    derivatives_root_type = kwargs.get("derivatives_root_type") or None
    participant_label_hint = kwargs.get("participant_label", "")

    girder_api_url = resolve_girder_url(task)
    girder_client_token = getattr(task.request, "girder_client_token", None)

    gc = GirderClient(apiUrl=girder_api_url)
    gc.token = girder_client_token

    is_session = bool(session_folder_id)

    if is_session:
        participant_label = bids_resolve_participant_label_from_folder(
            gc, session_folder_id, participant_label_hint
        )
    else:
        participant_label = bids_resolve_participant_label(gc, item_id, participant_label_hint)

    def _update_result(**data):
        if is_session:
            update_diadema_tool_on_folder(gc, session_folder_id, "freesurfer", **data)
        else:
            update_diadema_tool(gc, item_id, "freesurfer", **data)

    # Anchor item_id per bids_upload_derivative (usato solo per risalire dataset root)
    bids_anchor_id = item_id if not is_session else None

    progress = make_safe_progress(task, TASK_NAME)
    progress(
        "Upload risultati FreeSurfer su Girder (BIDS derivatives)...",
        total=100,
        current=5,
    )

    subject_dir = Path(subject_dir_str)
    uploaded = []
    derivative_item_ids = []

    # Log completo recon-all → derivatives/freesurfer/sub-xxx/
    log_file = subject_dir / "scripts" / "recon-all.log"
    if log_file.exists():
        iid = bids_upload_derivative(
            gc,
            bids_anchor_id,
            log_file,
            datatype="anat",
            participant_label=participant_label,
            derivatives_root_id=derivatives_root_id,
            derivatives_root_type=derivatives_root_type,
            pipeline_name="freesurfer",
        )
        uploaded.append("recon-all.log")
        if iid:
            derivative_item_ids.append(iid)
        progress("Log recon-all caricato.", current=30)

    # File *.stats
    stats_path = subject_dir / "stats"
    if stats_path.exists():
        stat_files = sorted(stats_path.glob("*.stats"))
        for i, sf in enumerate(stat_files):
            iid = bids_upload_derivative(
                gc,
                bids_anchor_id,
                sf,
                datatype="anat",
                participant_label=participant_label,
                derivatives_root_id=derivatives_root_id,
                pipeline_name="freesurfer",
            )
            uploaded.append(sf.name)
            if iid:
                derivative_item_ids.append(iid)
            pct = 30 + int((i + 1) / max(len(stat_files), 1) * 40)
            progress(f"Caricato {sf.name}", current=pct)

    # JSON statistiche (serializza il dict già parsato)
    with tempfile.NamedTemporaryFile(
        suffix="_freesurfer_stats.json", delete=False, mode="w"
    ) as tmp:
        json.dump(stats, tmp, indent=2)
        tmp_path = Path(tmp.name)
    try:
        iid = bids_upload_derivative(
            gc,
            bids_anchor_id,
            tmp_path,
            datatype="anat",
            participant_label=participant_label,
            derivatives_root_id=derivatives_root_id,
            derivatives_root_type=derivatives_root_type,
            pipeline_name="freesurfer",
        )
        uploaded.append("freesurfer_stats.json")
        if iid:
            derivative_item_ids.append(iid)
    finally:
        tmp_path.unlink(missing_ok=True)

    progress("Aggiornamento metadati...", current=90)
    _update_result(
        results={
            **result_meta,
            "stats": stats,
            "files_uploaded": uploaded,
            "derivative_item_ids": derivative_item_ids,
        },
        status="completed",
    )

    # Pulizia directory soggetto (opzionale)
    if not keep_subjects_dir:
        import shutil

        try:
            shutil.rmtree(subject_dir, ignore_errors=True)
            progress("Cartella soggetto rimossa.", current=98)
        except Exception as _rm_e:
            logger.warning("[%s] pulizia subjects dir non-fatal: %s", TASK_NAME, _rm_e)

    progress("Upload FreeSurfer completato!", current=100)
    return {"status": "success", "files_uploaded": uploaded}


# ── Task principale ───────────────────────────────────────────────────────────


@girder_job(title="DIADEMA – FreeSurfer")
@app.task(
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    name="girder_diadema_pipeline.tasks.run_freesurfer_task",
)
def run_freesurfer_task(task, **kwargs):
    """
    Esegue FreeSurfer recon-all su un file NIfTI T1w.
    Vedi docstring del modulo per la lista completa dei parametri.
    """
    import time as _time

    from girder_client import GirderClient

    TASK_NAME = "run_freesurfer_task"

    # ── Parametri ─────────────────────────────────────────────────────────────
    session_folder_id = kwargs.get("session_folder_id")
    item_id = kwargs.get("item_id")
    file_id = kwargs.get("file_id")
    file_name = kwargs.get("file_name", "unknown file")
    participant_label_hint = kwargs.get("participant_label") or ""
    directive = kwargs.get("directive", "-all").strip()
    hemi = kwargs.get("hemi", "both")
    openmp_threads = int(kwargs.get("openmp_threads", 4))
    mprage = bool(kwargs.get("mprage", False))
    wsatlas = bool(kwargs.get("wsatlas", False))
    deface = bool(kwargs.get("deface", False))
    no_isrunning = bool(kwargs.get("no_isrunning", True))
    extra_flags = kwargs.get("extra_flags", "")
    subjects_dir_kwarg = kwargs.get("subjects_dir")
    keep_subjects_dir = bool(kwargs.get("keep_subjects_dir", True))
    timeout = int(kwargs.get("timeout", 14400))
    derivatives_root_id = kwargs.get("derivatives_root_id") or None
    override_t1w_file_id = kwargs.get("override_t1w_file_id") or None
    override_t2w_file_id = kwargs.get("override_t2w_file_id") or None
    job_id = kwargs.get("job_id")
    job_token_id = kwargs.get("job_token_id")
    # ─────────────────────────────────────────────────────────────────────────

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
            update_diadema_tool_on_folder(gc, session_folder_id, "freesurfer", **data)
        else:
            update_diadema_tool(gc, item_id, "freesurfer", **data)

    if idempotency_guard(girder_api_url, job_id, job_token_id, TASK_NAME):
        return {"status": "skipped", "reason": "job already terminal"}

    set_running(girder_api_url, job_id, job_token_id, TASK_NAME)
    progress = make_safe_progress(task, TASK_NAME)

    label_str = f"sub-{participant_label}" + (f"_ses-{session_label}" if session_label else "")
    progress(
        f"FreeSurfer recon-all: {label_str} ({'sessione' if is_session else file_name})",
        total=100,
        current=5,
    )

    # Validazione directive
    if directive not in _VALID_DIRECTIVES:
        msg = (
            f"Direttiva non valida: '{directive}'. "
            f"Valori ammessi: {sorted(_VALID_DIRECTIVES)}"
        )
        _update_status(status="error", error={"message": msg, "timestamp": now_iso()})
        raise Exception(msg)

    # ── SUBJECTS_DIR ──────────────────────────────────────────────────────────
    subjects_dir = resolve_dir(
        subjects_dir_kwarg,
        _ENV_SUBJECTS_DIR,
        _DEFAULT_SUBJECTS_DIR,
        "subjects_dir",
        TASK_NAME,
    )
    if is_session:
        # ID soggetto basato su participant_label+session: stabile tra re-run, permette resume
        ses_suffix = f"_{session_label}" if session_label else ""
        subject_id = f"diadema_{participant_label}{ses_suffix}"
    else:
        subject_id = f"diadema_{item_id[:12]}"
    subject_dir = subjects_dir / subject_id
    # ─────────────────────────────────────────────────────────────────────────

    derivatives_root_type = None
    if not derivatives_root_id and is_session:
        root_id, root_type = bids_find_dataset_root_from_folder(gc, session_folder_id)
        if root_id:
            derivatives_root_id = root_id
            derivatives_root_type = root_type

    with tempfile.TemporaryDirectory() as tmpdir:
        import gzip as _gzip

        nifti_path = Path(tmpdir) / "input.nii.gz"
        t2w_path = None
        t2w_file_id = None

        if is_session:
            # T1w: usa override esplicito oppure auto-detect
            if override_t1w_file_id:
                t1w_file_id = override_t1w_file_id
                file_name = gc.get(f"file/{t1w_file_id}").get("name", "T1w.nii.gz")
                progress(f"T1w (override): {file_name}", current=8)
            else:
                progress("Ricerca file T1w nella sessione...", current=8)
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
                t1w_file_id = str(t1w_nifti["_id"])
                file_name = t1w_item.get("name", "T1w.nii.gz")

            progress(f"Scaricamento T1w: {file_name}", current=10)
            gc.downloadFile(t1w_file_id, str(nifti_path))

            # T2w: usa override esplicito oppure auto-detect
            if override_t2w_file_id:
                t2w_file_id = override_t2w_file_id
                t2w_path = Path(tmpdir) / "t2w.nii.gz"
                progress("Scaricamento T2w (override)...", current=12)
                gc.downloadFile(t2w_file_id, str(t2w_path))
            else:
                t2w_item = bids_find_modality_file(gc, session_folder_id, "T2w")
                if t2w_item:
                    t2w_nifti = get_nifti_file_from_item(gc, str(t2w_item["_id"]))
                    if t2w_nifti:
                        t2w_file_id = str(t2w_nifti["_id"])
                        t2w_path = Path(tmpdir) / "t2w.nii.gz"
                        progress(f"Scaricamento T2w: {t2w_item.get('name', '')}", current=12)
                        gc.downloadFile(t2w_file_id, str(t2w_path))

            # Comprimi T2w se necessario
            if t2w_path and t2w_path.exists():
                with open(t2w_path, "rb") as f:
                    if f.read(2) != b"\x1f\x8b":
                        raw = t2w_path.read_bytes()
                        with _gzip.open(t2w_path, "wb") as gz:
                            gz.write(raw)
                        del raw
        else:
            progress("Scaricamento file NIfTI...", current=10)
            gc.downloadFile(file_id, str(nifti_path))

        # Comprimi T1w se non gzip
        with open(nifti_path, "rb") as f:
            magic = f.read(2)
        if magic != b"\x1f\x8b":
            progress("File non compresso, comprimo in-place...", current=12)
            raw = nifti_path.read_bytes()
            with _gzip.open(nifti_path, "wb") as gz:
                gz.write(raw)
            del raw

        # ── Costruzione comando recon-all ──────────────────────────────────
        cmd = [
            "recon-all",
            "-subject",
            subject_id,
            "-i",
            str(nifti_path),
            directive,
            "-sd",
            str(subjects_dir),
            "-threads",
            str(openmp_threads),
        ]
        # T2w opzionale per migliorare la ricostruzione della superficie piale
        if t2w_path and t2w_path.exists():
            cmd += ["-T2", str(t2w_path), "-T2pial"]

        if hemi in ("lh", "rh"):
            cmd += ["-hemi", hemi]
        if mprage:
            cmd.append("-mprage")
        if wsatlas:
            cmd.append("-wsatlas")
        if deface:
            cmd.append("-deface")
        if no_isrunning:
            cmd.append("-no-isrunning")
        if extra_flags.strip():
            cmd += shlex.split(extra_flags)

        progress(f"Avvio recon-all: {' '.join(cmd)}", current=15)

        # ── Ambiente FreeSurfer ────────────────────────────────────────────
        env = os.environ.copy()
        env["SUBJECTS_DIR"] = str(subjects_dir)
        # OpenMP
        env["OMP_NUM_THREADS"] = str(openmp_threads)
        # Evita warning MKL/OMP duplicate runtime
        env["KMP_DUPLICATE_LIB_OK"] = "True"

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # unifica stdout+stderr per il log
                text=True,
                start_new_session=True,
                env=env,
            )

            # Streaming live del log recon-all verso Girder
            import threading

            def _stream_log():
                for line in proc.stdout:
                    progress(line.rstrip())

            _log_thread = threading.Thread(target=_stream_log, daemon=True)
            _log_thread.start()

            _elapsed = 0
            _poll_interval = 30  # recon-all è lento, poll ogni 30s

            while proc.poll() is None:
                _time.sleep(_poll_interval)
                _elapsed += _poll_interval

                if _elapsed >= timeout:
                    kill_proc(proc, TASK_NAME)
                    raise subprocess.TimeoutExpired(cmd, timeout)

                pct = min(15 + int(_elapsed * 60 / timeout), 75)
                _cancel_requested = False
                _cancel_status = None
                if job_id:
                    try:
                        _cancel_status = gc.get(f"job/{job_id}").get("status")
                        if _cancel_status in (5, 824):
                            _cancel_requested = True
                    except Exception as _poll_e:
                        logger.warning(
                            "[%s] poll status non-fatal: %s", TASK_NAME, _poll_e
                        )

                if _cancel_requested:
                    progress(
                        f"Cancellazione richiesta (status={_cancel_status}), termino recon-all...",
                        current=pct,
                    )
                    kill_proc(proc, TASK_NAME)
                    _log_thread.join(timeout=5)
                    _update_status(
                        status="cancelled",
                        error={"message": "Job cancellato dall'utente", "timestamp": now_iso()},
                    )
                    set_job_cancelled(gc, job_id, TASK_NAME)
                    raise Ignore()

            _log_thread.join(timeout=10)

            if proc.returncode != 0:
                # Leggi ultime righe del log freesurfer per il messaggio di errore
                log_file = subject_dir / "scripts" / "recon-all.log"
                tail = ""
                if log_file.exists():
                    lines = log_file.read_text(errors="replace").splitlines()
                    tail = "\n".join(lines[-50:])
                raise Exception(f"recon-all fallito (exit {proc.returncode}):\n{tail}")

            progress("recon-all completato, raccolta statistiche...", current=80)

            # ── Parse risultati ────────────────────────────────────────────
            stats = _collect_stats(subject_dir)

            result_meta = {
                "timestamp": now_iso(),
                "freesurfer_version": tool_version("recon-all"),
                "participant_label": participant_label,
                "session_label": session_label,
                "subject_id": subject_id,
                "subjects_dir": str(subjects_dir),
                "directive": directive,
            }
            if is_session:
                result_meta["session_folder_id"] = session_folder_id
                result_meta["t2w_used"] = t2w_file_id is not None
            else:
                result_meta["file_id"] = file_id
                result_meta["file_name"] = gc.get(f"file/{file_id}")["name"]

            progress("Avvio upload risultati in background...", current=85)
            upload_freesurfer_results.apply_async(
                kwargs=dict(
                    item_id=item_id,
                    session_folder_id=session_folder_id,
                    subject_dir=str(subject_dir),
                    stats=stats,
                    result_meta=result_meta,
                    keep_subjects_dir=keep_subjects_dir,
                    derivatives_root_id=derivatives_root_id,
                    derivatives_root_type=derivatives_root_type,
                    participant_label=participant_label,
                ),
                headers={
                    "girder_client_token": girder_client_token,
                    "girder_api_url": girder_api_url,
                },
                queue="freesurfer",
            )

            _update_status(
                status="uploading",
                results={**result_meta, "stats": stats},
            )

            progress("recon-all completato! Upload statistiche avviato in background.", current=100)
            return {
                "status": "uploading",
                "subject_id": subject_id,
                **({"session_folder_id": session_folder_id} if is_session else {"item_id": item_id}),
            }

        except Ignore:
            raise

        except subprocess.TimeoutExpired:
            msg = f"recon-all timeout dopo {timeout}s ({timeout // 3600}h)"
            logger.error("[%s] %s", TASK_NAME, msg)
            _update_status(status="error", error={"message": msg, "timestamp": now_iso()})
            raise Exception(msg)

        except Exception as exc:
            logger.exception("[%s] Errore non gestito: %s", TASK_NAME, exc)
            _update_status(status="error", error={"message": str(exc), "timestamp": now_iso()})
            raise
