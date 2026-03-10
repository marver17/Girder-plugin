"""
Task DIADEMA – LST-AI (lesion segmentation).
Stub strutturato: guardia idempotency + RUNNING + placeholder implementazione.
"""

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


@girder_job(title="DIADEMA – LST-AI")
@app.task(bind=True, acks_late=True, reject_on_worker_lost=True,
          name="girder_diadema_pipeline.tasks.run_lstai_task")
def run_lstai_task(task, **kwargs):
    """
    Esegue LST-AI su file NIfTI (T1 ± FLAIR) per segmentazione lesioni WM.

    Parametri previsti (da implementare):
        item_id        (str)   – ID item Girder
        file_id        (str)   – ID file T1 NIfTI
        flair_file_id  (str)   – ID file FLAIR (opzionale, se input_type="T1+FLAIR")
        input_type     (str)   – "T1+FLAIR" | "T1 only"   (default: "T1+FLAIR")
        threshold      (float) – soglia probabilità lesione 0.0-1.0   (default: 0.5)
        use_gpu        (bool)  – usa GPU se disponibile   (default: True)
        output_base_dir(str)   – directory output persistente
                                 (env: DIADEMA_LSTAI_OUTPUT_DIR, default: /data/diadema/lstai)
        timeout        (int)   – secondi max   (default: 3600)
        job_id / job_token_id  – gestione stato Girder
    """
    from girder_client import GirderClient

    TASK_NAME  = "run_lstai_task"
    item_id    = kwargs.get("item_id")
    job_id     = kwargs.get("job_id")
    job_token_id = kwargs.get("job_token_id")

    girder_api_url      = resolve_girder_url(task)
    girder_client_token = getattr(task.request, "girder_client_token", None)

    gc = GirderClient(apiUrl=girder_api_url)
    gc.token = girder_client_token

    if idempotency_guard(girder_api_url, job_id, job_token_id, TASK_NAME):
        return {"status": "skipped", "reason": "job already terminal"}

    set_running(girder_api_url, job_id, job_token_id, TASK_NAME)
    progress = make_safe_progress(task, TASK_NAME)
    progress("LST-AI: implementazione in corso...", total=100, current=5)

    # TODO: implementare LST-AI
    update_item_fields(gc, item_id,
        diadema_lstai_status="error",
        diadema_lstai_error={"message": "LST-AI non ancora implementato", "timestamp": now_iso()})

    raise NotImplementedError("run_lstai_task: implementazione backend pendente")
