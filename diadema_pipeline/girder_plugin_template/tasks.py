"""
Task Celery per Plugin Template
──────────────────────────────────────────────────────────────────────────────
PATTERN OBBLIGATORI:
  1. Doppio decoratore: @girder_job + @app.task(bind=True)
  2. Solo **kwargs come firma (mai argomenti posizionali dopo `task`):
     girder_worker "consuma" gli header riservati e li sposta su task.request
  3. Parametri riservati (girder_client_token, girder_api_url) si leggono
     da task.request, non da kwargs
  4. Guardia di idempotenza all'inizio (acks_late re-delivery)
  5. Override localhost → Docker hostname se necessario
──────────────────────────────────────────────────────────────────────────────
"""

import os

from girder_worker.app import app
from girder_worker.utils import girder_job


@girder_job(title="Plugin Template Task")
@app.task(bind=True)
def plugin_template_task(task, **kwargs):
    """
    Task principale del plugin.

    kwargs (inviati da rest.py via apply_async):
        item_id (str):       ID dell'item Girder
        file_id (str):       ID del file su cui operare
        file_name (str):     nome del file (per i log)
        job_id (str):        ID del Job Girder (per la guardia idempotenza)
        job_token_id (str):  token del job (per aggiornare lo stato)

    Parametri riservati (letti da task.request, non da kwargs):
        girder_client_token: token per autenticarsi al server Girder
        girder_api_url:      URL dell'API Girder raggiungibile dal worker
    """
    from girder_client import GirderClient

    # ── Estrai kwargs ─────────────────────────────────────────────────────────
    item_id      = kwargs.get("item_id")
    file_id      = kwargs.get("file_id")
    file_name    = kwargs.get("file_name", "unknown")
    job_id       = kwargs.get("job_id")
    job_token_id = kwargs.get("job_token_id")

    # ── Parametri riservati: girder_worker li sposta in task.request ──────────
    girder_client_token = getattr(task.request, "girder_client_token", None)
    girder_api_url = getattr(
        task.request, "girder_api_url", "http://localhost:8080/api/v1"
    )

    # Override localhost con la env var GIRDER_API_URL se presente.
    # Necessario quando jobInfoSpec contiene ancora "localhost" dopo il patch
    # di worker_entry.py (raro, ma possibile in alcune configurazioni).
    girder_api_url_env = os.environ.get("GIRDER_API_URL")
    if girder_api_url_env and (
        "localhost" in girder_api_url or "127.0.0.1" in girder_api_url
    ):
        girder_api_url = girder_api_url_env

    # ── Guardia di idempotenza (acks_late re-delivery) ────────────────────────
    # Con acks_late=True (default di girder_worker), se il worker crasha
    # mentre esegue il task, RabbitMQ ri-consegna il messaggio.
    # Questa guardia evita di ri-eseguire task già completati.
    #   Stati terminali: 3=SUCCESS  4=ERROR  5=CANCELLED
    if job_id and job_token_id:
        try:
            _gc = GirderClient(apiUrl=girder_api_url)
            _gc.token = job_token_id
            _job = _gc.get(f"job/{job_id}")
            _status = _job.get("status", 0)
            if _status in (3, 4, 5):
                print(
                    f"[plugin_template_task] Job {job_id} già in stato terminale "
                    f"({_status}), skip"
                )
                return {
                    "status": "skipped",
                    "reason": "job already in terminal state",
                    "job_status": _status,
                }
        except Exception as _e:
            # Non riusciamo a verificare lo stato: procediamo cauti
            print(f"[plugin_template_task] Impossibile verificare stato job: {_e}")

    # ── Client Girder autenticato ─────────────────────────────────────────────
    gc = GirderClient(apiUrl=girder_api_url)
    gc.token = girder_client_token

    print(f"[plugin_template_task] Inizio elaborazione: {file_name} (item={item_id})")

    try:
        # ── SCARICA IL FILE ───────────────────────────────────────────────────
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory(prefix="plugin_template_") as tmp_dir:
            tmp_path = Path(tmp_dir)
            input_file = tmp_path / file_name

            print(f"[plugin_template_task] Download file {file_id}...")
            gc.downloadFile(file_id, str(input_file))

            # ── QUI VAI LA LOGICA DEL TUO PLUGIN ─────────────────────────────
            # Esempio: analisi, conversione, elaborazione...
            #
            # result = my_analysis_function(input_file)
            #
            # In questo template usiamo un risultato fittizio:
            result = {
                "file_name": file_name,
                "file_size_bytes": input_file.stat().st_size,
                "status": "success",
                # aggiungi qui i tuoi risultati
            }
            # ─────────────────────────────────────────────────────────────────

        # ── SALVA I RISULTATI SULL'ITEM ───────────────────────────────────────
        gc.put(
            f"item/{item_id}",
            data={
                "metadata": {
                    "plugin_template_results": result,
                    "plugin_template_status": "completed",
                },
            },
        )

        print(f"[plugin_template_task] Completato: {file_name}")
        return result

    except Exception as e:
        # ── SALVA L'ERRORE SULL'ITEM ──────────────────────────────────────────
        error_msg = str(e)
        print(f"[plugin_template_task] ERRORE: {error_msg}")
        try:
            gc.put(
                f"item/{item_id}",
                data={
                    "metadata": {
                        "plugin_template_status": "error",
                        "plugin_template_error": error_msg,
                    },
                },
            )
        except Exception:
            pass  # Se non riusciamo ad aggiornare l'item, lasciamo che girder_worker
                  # imposti lo stato ERROR sul job tramite gw_task_postrun

        raise  # Ri-solleva per far segnare il job come ERROR da girder_worker
