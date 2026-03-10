##TODO sistemare problema di upload. Vedere se c'è la possibilità di farlo asincrono rispetto al task, magari con un task secondario dedicato all'upload, in modo da non bloccare il task principale durante l'upload di file potenzialmente grandi (es. log completi o file stat).


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
import os
import shlex
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

_DEFAULT_SUBJECTS_DIR = "/data/diadema/subjects"
_ENV_SUBJECTS_DIR     = "DIADEMA_SUBJECTS_DIR"

# Direttive valide recon-all
_VALID_DIRECTIVES = {
    "-all", "-autorecon-all",
    "-autorecon1",
    "-autorecon2", "-autorecon2-cp", "-autorecon2-wm",
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
        print(f"[freesurfer] parse_global_measures {stats_path}: {exc}")
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
        print(f"[freesurfer] parse_aseg_stats {stats_path}: {exc}")
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
                        "NumVert":  int(parts[1]),
                        "SurfArea": int(parts[2]),
                        "GrayVol":  int(parts[3]),
                        "ThickAvg": float(parts[4]),
                        "ThickStd": float(parts[5]),
                    }
    except Exception as exc:
        print(f"[freesurfer] parse_aparc_stats {stats_path}: {exc}")
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
            result["global"].update({
                f"{hemi}_{k}": v
                for k, v in _parse_global_measures(aparc).items()
            })

        # aparc.a2009s.stats (Destrieux) – presente solo dopo autorecon3
        aparc2009 = stats_dir / f"{hemi}.aparc.a2009s.stats"
        if aparc2009.exists():
            result["cortical"][hemi]["Destrieux"] = _parse_aparc_stats(aparc2009)

    return result


# ── Task principale ───────────────────────────────────────────────────────────

@girder_job(title="DIADEMA – FreeSurfer")
@app.task(bind=True, acks_late=True, reject_on_worker_lost=True,
          name="girder_diadema_pipeline.tasks.run_freesurfer_task")
def run_freesurfer_task(task, **kwargs):
    """
    Esegue FreeSurfer recon-all su un file NIfTI T1w.
    Vedi docstring del modulo per la lista completa dei parametri.
    """
    import time as _time
    from girder_client import GirderClient

    TASK_NAME = "run_freesurfer_task"

    # ── Parametri ─────────────────────────────────────────────────────────────
    item_id           = kwargs.get("item_id")
    file_id           = kwargs.get("file_id")
    file_name         = kwargs.get("file_name", "unknown file")
    participant_label = kwargs.get("participant_label", "001")
    directive         = kwargs.get("directive", "-all").strip()
    hemi              = kwargs.get("hemi", "both")              # both | lh | rh
    openmp_threads    = int(kwargs.get("openmp_threads", 4))
    mprage            = bool(kwargs.get("mprage", False))
    wsatlas           = bool(kwargs.get("wsatlas", False))
    deface            = bool(kwargs.get("deface", False))
    no_isrunning      = bool(kwargs.get("no_isrunning", True))  # salta check "already running"
    extra_flags       = kwargs.get("extra_flags", "")
    subjects_dir_kwarg= kwargs.get("subjects_dir")
    keep_subjects_dir = bool(kwargs.get("keep_subjects_dir", True))
    timeout           = int(kwargs.get("timeout", 14400))       # 4 ore default
    job_id            = kwargs.get("job_id")
    job_token_id      = kwargs.get("job_token_id")
    # ─────────────────────────────────────────────────────────────────────────

    girder_api_url      = resolve_girder_url(task)
    girder_client_token = getattr(task.request, "girder_client_token", None)

    gc = GirderClient(apiUrl=girder_api_url)
    gc.token = girder_client_token

    if idempotency_guard(girder_api_url, job_id, job_token_id, TASK_NAME):
        return {"status": "skipped", "reason": "job already terminal"}

    set_running(girder_api_url, job_id, job_token_id, TASK_NAME)
    progress = make_safe_progress(task, TASK_NAME)
    progress(f"FreeSurfer recon-all: {file_name} (sub-{participant_label})", total=100, current=5)

    # Validazione directive
    if directive not in _VALID_DIRECTIVES:
        msg = (f"Direttiva non valida: '{directive}'. "
               f"Valori ammessi: {sorted(_VALID_DIRECTIVES)}")
        update_item_fields(gc, item_id,
            diadema_freesurfer_status="error",
            diadema_freesurfer_error={"message": msg, "timestamp": now_iso()})
        raise Exception(msg)

    # ── SUBJECTS_DIR ──────────────────────────────────────────────────────────
    subjects_dir = resolve_dir(
        subjects_dir_kwarg, _ENV_SUBJECTS_DIR, _DEFAULT_SUBJECTS_DIR,
        "subjects_dir", TASK_NAME
    )
    # ID soggetto univoco per item (evita conflitti tra run sullo stesso partecipante)
    subject_id  = f"diadema_{item_id[:12]}"
    subject_dir = subjects_dir / subject_id
    # ─────────────────────────────────────────────────────────────────────────

    with tempfile.TemporaryDirectory() as tmpdir:
        nifti_path = Path(tmpdir) / "input.nii.gz"

        progress("Scaricamento file NIfTI...", current=10)
        gc.downloadFile(file_id, str(nifti_path))

        # Comprimi se non gzip
        with open(nifti_path, "rb") as f:
            magic = f.read(2)
        if magic != b"\x1f\x8b":
            import gzip as _gzip
            progress("File non compresso, comprimo in-place...", current=12)
            raw = nifti_path.read_bytes()
            with _gzip.open(nifti_path, "wb") as gz:
                gz.write(raw)
            del raw

        # ── Costruzione comando recon-all ──────────────────────────────────
        cmd = [
            "recon-all",
            "-subject", subject_id,
            "-i", str(nifti_path),
            directive,
            "-sd", str(subjects_dir),
            "-threads", str(openmp_threads),
        ]

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
                stderr=subprocess.STDOUT,   # unifica stdout+stderr per il log
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
                _cancel_status    = None
                if job_id:
                    try:
                        _cancel_status = gc.get(f"job/{job_id}").get("status")
                        if _cancel_status in (5, 824):
                            _cancel_requested = True
                    except Exception as _poll_e:
                        print(f"[{TASK_NAME}] poll status non-fatal: {_poll_e}")

                if _cancel_requested:
                    progress(f"Cancellazione richiesta (status={_cancel_status}), termino recon-all...", current=pct)
                    kill_proc(proc, TASK_NAME)
                    _log_thread.join(timeout=5)
                    update_item_fields(gc, item_id,
                        diadema_freesurfer_status="cancelled",
                        diadema_freesurfer_error={"message": "Job cancellato dall'utente", "timestamp": now_iso()})
                    set_job_cancelled(gc, job_id, TASK_NAME)
                    from celery.exceptions import Ignore
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

            # ── Upload file su Girder ──────────────────────────────────────
            progress("Upload risultati su Girder...", current=88)
            uploaded = []

            # Log completo
            log_file = subject_dir / "scripts" / "recon-all.log"
            if log_file.exists():
                gc.uploadFileToItem(item_id, str(log_file))
                uploaded.append("recon-all.log")

            # File stats
            stats_dir = subject_dir / "stats"
            if stats_dir.exists():
                for sf in stats_dir.glob("*.stats"):
                    gc.uploadFileToItem(item_id, str(sf))
                    uploaded.append(sf.name)

            # Salva JSON statistiche come file separato
            stats_json_path = Path(tmpdir) / "freesurfer_stats.json"
            stats_json_path.write_text(json.dumps(stats, indent=2))
            gc.uploadFileToItem(item_id, str(stats_json_path))
            uploaded.append("freesurfer_stats.json")

            update_item_fields(gc, item_id,
                diadema_freesurfer_results={
                    "stats":              stats,
                    "timestamp":          now_iso(),
                    "freesurfer_version": tool_version("recon-all"),
                    "participant_label":  participant_label,
                    "subject_id":         subject_id,
                    "subjects_dir":       str(subjects_dir),
                    "directive":          directive,
                    "file_id":            file_id,
                    "file_name":          gc.get(f"file/{file_id}")["name"],
                    "files_uploaded":     uploaded,
                },
                diadema_freesurfer_status="completed",
            )

            # Pulizia soggetto (opzionale)
            if not keep_subjects_dir:
                import shutil
                try:
                    shutil.rmtree(subject_dir, ignore_errors=True)
                    progress("Cartella soggetto rimossa.", current=98)
                except Exception as _rm_e:
                    print(f"[{TASK_NAME}] pulizia subjects dir non-fatal: {_rm_e}")

            progress("FreeSurfer recon-all completato!", current=100)
            return {
                "status":     "success",
                "item_id":    item_id,
                "subject_id": subject_id,
                "stats":      stats,
            }

        except subprocess.TimeoutExpired:
            msg = f"recon-all timeout dopo {timeout}s ({timeout // 3600}h)"
            update_item_fields(gc, item_id,
                diadema_freesurfer_status="error",
                diadema_freesurfer_error={"message": msg, "timestamp": now_iso()})
            raise Exception(msg)

        except Exception as exc:
            update_item_fields(gc, item_id,
                diadema_freesurfer_status="error",
                diadema_freesurfer_error={"message": str(exc), "timestamp": now_iso()})
            raise
