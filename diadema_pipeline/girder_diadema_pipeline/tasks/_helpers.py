"""
Helper condivisi tra tutti i task DIADEMA.

Ordine di priorità per resolve_dir:
  1. Valore esplicito passato come kwarg (può provenire dai Settings Girder)
  2. Variabile d'ambiente nel container worker
  3. Default hardcoded
"""

import datetime
import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def resolve_girder_url(task):
    """Ricava l'URL Girder dal request Celery, sostituendo localhost con il nome del container."""
    url = getattr(task.request, "girder_api_url", "http://localhost:8080/api/v1")
    env = os.environ.get("GIRDER_API_URL")
    if env and ("localhost" in url or "127.0.0.1" in url):
        url = env
    return url


def idempotency_guard(girder_api_url, job_id, job_token_id, task_name):
    """
    Ritorna True se il job è già in stato terminale (SUCCESS=3, ERROR=4, CANCELLED=5).
    Con acks_late=True, RabbitMQ ri-consegna il messaggio se la connessione cade dopo
    il completamento del task ma prima dell'ACK: questa guardia evita la doppia esecuzione.
    """
    from girder_client import GirderClient

    if not (job_id and job_token_id):
        return False
    try:
        gc = GirderClient(apiUrl=girder_api_url)
        gc.token = job_token_id
        status = gc.get(f"job/{job_id}").get("status", 0)
        if status in (3, 4, 5):
            print(
                f"[{task_name}] Job {job_id} già terminale ({status}), skip re-delivery"
            )
            return True
    except Exception as exc:
        print(f"[{task_name}] idempotency check non-fatal: {exc}")
    return False


def set_running(girder_api_url, job_id, job_token_id, task_name):
    """
    Transizione esplicita QUEUED→RUNNING (status=2).
    Il segnale task_prerun di girder_worker dovrebbe farlo, ma in alcune
    configurazioni non si aggancia: il job resterebbe in QUEUED.
    """
    from girder_client import GirderClient

    if not (job_id and job_token_id):
        return
    try:
        gc = GirderClient(apiUrl=girder_api_url)
        gc.token = job_token_id
        gc.put(f"job/{job_id}", parameters={"status": 2})
        logger.info("[%s] Job %s → RUNNING", task_name, job_id)
    except Exception as exc:
        logger.warning("[%s] set RUNNING fallito: %s", task_name, exc)


def make_safe_progress(task, task_name):
    """
    Restituisce una funzione safe_progress(message, current, total) che:
    - stampa su stdout (visibile in `docker logs`)
    - scrive in streaming nel log del job Girder (job_manager.write)
    - aggiorna la barra di avanzamento (updateProgress)
    Nessuna delle tre operazioni blocca il task se fallisce.
    """

    def safe_progress(message, current=None, total=None):
        logger.debug("[%s] %s", task_name, message)
        try:
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


def update_item_fields(gc, item_id, **fields):
    """Salva campi di metadati sull'item Girder senza sollevare eccezioni.

    DEPRECATO: usare update_diadema_tool() per i dati di elaborazione DIADEMA.
    """
    try:
        gc.put(f"item/{item_id}/metadata", json=fields)
    except Exception as exc:
        logger.warning("[diadema] update item %s fallito: %s", item_id, exc)


def update_diadema_tool(gc, item_id, tool_id, **data):
    """Aggiorna i dati di elaborazione per un tool DIADEMA.

    Scrive in item.diadema.{tool_id} (campo dedicato, separato da item.meta).
    I chiavi tipiche sono: status, results, error, job_id.
    """
    try:
        gc.put(f"diadema_pipeline/{item_id}/processing/{tool_id}", json=data)
    except Exception as exc:
        logger.warning(
            "[diadema] update_diadema_tool item=%s tool=%s fallito: %s",
            item_id,
            tool_id,
            exc,
        )


def set_job_cancelled(gc, job_id, task_name):
    """Imposta lo stato del job a CANCELLED (5) usando gc (token utente con scope jobs.*)."""
    try:
        gc.put(f"job/{job_id}", parameters={"status": 5})
        logger.info("[%s] Job %s → CANCELLED", task_name, job_id)
    except Exception as exc:
        logger.warning("[%s] set CANCELLED fallito: %s", task_name, exc)


def kill_proc(proc, task_name):
    """
    Tenta di terminare un subprocess e tutti i suoi figli (killpg SIGTERM).
    Fallback a kill() diretto se killpg non funziona.
    """
    import os
    import signal

    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=30)
    except Exception as exc:
        logger.warning("[%s] killpg non-fatal: %s", task_name, exc)
        try:
            proc.kill()
            proc.wait(timeout=10)
        except Exception:
            pass


def tool_version(cmd_name):
    """Legge la versione di un tool CLI (es. 'mriqc', 'recon-all')."""
    try:
        r = subprocess.run(
            [cmd_name, "--version"], capture_output=True, text=True, timeout=10
        )
        return r.stdout.strip() or r.stderr.strip()
    except Exception:
        return "unknown"


def now_iso():
    """Timestamp UTC ISO 8601."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def resolve_dir(explicit_path, env_var, default, label, task_name):
    """
    Ricava il path di una directory nell'ordine di priorità:
      1. explicit_path  – valore passato come kwarg (può provenire dai Settings Girder
                          iniettati dal layer REST al momento del dispatch del task)
      2. variabile d'ambiente nel container worker (env_var)
      3. valore di default hardcoded

    Crea la directory se non esiste e restituisce un oggetto pathlib.Path.
    """
    path_str = explicit_path or os.environ.get(env_var) or default
    path = Path(path_str)
    path.mkdir(parents=True, exist_ok=True)
    logger.info("[%s] %s: %s", task_name, label, path)
    return path
