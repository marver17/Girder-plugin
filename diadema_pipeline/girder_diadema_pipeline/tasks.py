"""
Task Celery per DIADEMA Pipeline.
Stub con i 3 task – implementazione dettagliata arriverà con il backend.
"""

import os
from girder_worker.app import app
from girder_worker.utils import girder_job


def _get_girder_url(task):
    url = getattr(task.request, "girder_api_url", "http://localhost:8080/api/v1")
    env = os.environ.get("GIRDER_API_URL")
    if env and ("localhost" in url or "127.0.0.1" in url):
        url = env
    return url


def _idempotency_guard(task, job_id, job_token_id):
    """Ritorna True se il job è già in stato terminale (skip)."""
    from girder_client import GirderClient
    if not (job_id and job_token_id):
        return False
    try:
        gc = GirderClient(apiUrl=_get_girder_url(task))
        gc.token = job_token_id
        status = gc.get(f"job/{job_id}").get("status", 0)
        return status in (3, 4, 5)
    except Exception:
        return False


# ── MRI QC (MRIQC) ────────────────────────────────────────────────────────────

@girder_job(title="DIADEMA – MRI QC")
@app.task(bind=True)
def run_mriqc_task(task, **kwargs):
    from girder_client import GirderClient
    job_id = kwargs.get("job_id")
    job_token_id = kwargs.get("job_token_id")
    item_id = kwargs.get("item_id")

    if _idempotency_guard(task, job_id, job_token_id):
        return {"status": "skipped", "reason": "job already terminal"}

    gc = GirderClient(apiUrl=_get_girder_url(task))
    gc.token = getattr(task.request, "girder_client_token", None)

    # TODO: implementare la logica MRIQC (vedi nifti_qc/tasks.py come riferimento)
    raise NotImplementedError("run_mriqc_task: implementazione backend pendente")


# ── FreeSurfer recon-all ───────────────────────────────────────────────────────

@girder_job(title="DIADEMA – FreeSurfer")
@app.task(bind=True)
def run_freesurfer_task(task, **kwargs):
    from girder_client import GirderClient
    job_id = kwargs.get("job_id")
    job_token_id = kwargs.get("job_token_id")

    if _idempotency_guard(task, job_id, job_token_id):
        return {"status": "skipped", "reason": "job already terminal"}

    gc = GirderClient(apiUrl=_get_girder_url(task))
    gc.token = getattr(task.request, "girder_client_token", None)

    # TODO: implementare recon-all
    raise NotImplementedError("run_freesurfer_task: implementazione backend pendente")


# ── LST-AI ────────────────────────────────────────────────────────────────────

@girder_job(title="DIADEMA – LST-AI")
@app.task(bind=True)
def run_lstai_task(task, **kwargs):
    from girder_client import GirderClient
    job_id = kwargs.get("job_id")
    job_token_id = kwargs.get("job_token_id")

    if _idempotency_guard(task, job_id, job_token_id):
        return {"status": "skipped", "reason": "job already terminal"}

    gc = GirderClient(apiUrl=_get_girder_url(task))
    gc.token = getattr(task.request, "girder_client_token", None)

    # TODO: implementare LST-AI
    raise NotImplementedError("run_lstai_task: implementazione backend pendente")
