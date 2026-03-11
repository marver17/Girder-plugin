"""
Task DIADEMA – LST-AI (lesion segmentation).

Stato: NON IMPLEMENTATO.
Questo stub gestisce correttamente lo stato Girder (idempotency guard, RUNNING,
errore applicativo esplicito) senza lanciare eccezioni non gestite.

Per implementare:
  1. Aggiungere il Dockerfile del worker LST-AI e il servizio in docker-compose.yml
  2. Installare `lst_ai` nel worker
  3. Implementare il download del file T1 (e FLAIR opzionale)
  4. Costruire il comando lst_ai e gestire il subprocess con polling cancel
  5. Parsare i risultati (lesion_count, total_volume_ml, lesion_mask_file_id)
  6. Impostare diadema.widget_enabled.lstai = true nelle Settings admin
"""

import logging

from girder_worker.app import app
from girder_worker.utils import girder_job

from ._helpers import (
    idempotency_guard,
    make_safe_progress,
    now_iso,
    resolve_girder_url,
    set_running,
    update_item_fields,
)

logger = logging.getLogger(__name__)

_NOT_IMPLEMENTED_MSG = (
    "LST-AI non è ancora disponibile in questa installazione. "
    "Contattare l'amministratore del sistema."
)


@girder_job(title="DIADEMA – LST-AI")
@app.task(bind=True, acks_late=True, reject_on_worker_lost=True,
          name="girder_diadema_pipeline.tasks.run_lstai_task")
def run_lstai_task(task, **kwargs):
    """
    Esegue LST-AI su file NIfTI (T1 ± FLAIR) per segmentazione lesioni WM.

    Parametri supportati (da implementare nel backend):
        item_id         (str)   – ID item Girder
        file_id         (str)   – ID file T1 NIfTI
        flair_file_id   (str)   – ID file FLAIR (opzionale, richiesto se input_type="T1+FLAIR")
        input_type      (str)   – "T1+FLAIR" | "T1 only"   (default: "T1+FLAIR")
        threshold       (float) – soglia probabilità lesione 0.0–1.0   (default: 0.5)
        use_gpu         (bool)  – usa GPU se disponibile   (default: True)
        output_base_dir (str)   – directory output persistente
        timeout         (int)   – secondi max   (default: 3600)
        job_id / job_token_id   – gestione stato Girder
    """
    from girder_client import GirderClient

    TASK_NAME    = "run_lstai_task"
    item_id      = kwargs.get("item_id")
    job_id       = kwargs.get("job_id")
    job_token_id = kwargs.get("job_token_id")

    girder_api_url      = resolve_girder_url(task)
    girder_client_token = getattr(task.request, "girder_client_token", None)

    gc = GirderClient(apiUrl=girder_api_url)
    gc.token = girder_client_token

    if idempotency_guard(girder_api_url, job_id, job_token_id, TASK_NAME):
        return {"status": "skipped", "reason": "job already terminal"}

    set_running(girder_api_url, job_id, job_token_id, TASK_NAME)
    progress = make_safe_progress(task, TASK_NAME)
    progress("LST-AI: tool non ancora implementato in questa installazione.",
             total=100, current=5)

    logger.warning("[%s] Tentativo di eseguire un task non implementato (item_id=%s)", TASK_NAME, item_id)

    update_item_fields(gc, item_id,
        diadema_lstai_status="not_implemented",
        diadema_lstai_error={
            "message": _NOT_IMPLEMENTED_MSG,
            "timestamp": now_iso(),
        },
    )

    # Termina il job Girder con stato ERROR per segnalarlo chiaramente nell'UI
    try:
        gc.put(f"job/{job_id}", parameters={"status": 4})  # 4 = ERROR
    except Exception as exc:
        logger.warning("[%s] set ERROR non-fatal: %s", TASK_NAME, exc)

    return {"status": "not_implemented", "message": _NOT_IMPLEMENTED_MSG}

