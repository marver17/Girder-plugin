"""
REST API per DIADEMA Pipeline
Espone un endpoint generico POST /:id/run/:toolId
che accetta i parametri del tool e li invia alla coda Celery corretta.
"""

import os

from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import Resource, filtermodel, getApiUrl
from girder.constants import AccessType, TokenScope
from girder.exceptions import RestException
from girder.models.file import File
from girder.models.item import Item
from girder.models.token import Token
from girder_jobs.constants import JobStatus
from girder_jobs.models.job import Job

# Tool supportati → coda Celery + task name (da aggiungere man mano)
_TOOL_CONFIG = {
    "mriqc": {
        "queue": "diadema_mriqc",
        "job_type": "diadema_mriqc",
        "title_prefix": "DIADEMA MRI QC",
        "result_field": "diadema_mriqc",
    },
    "freesurfer": {
        "queue": "freesurfer",
        "job_type": "diadema_freesurfer",
        "title_prefix": "DIADEMA FreeSurfer",
        "result_field": "diadema_freesurfer",
    },
    "lstai": {
        "queue": "lstai",
        "job_type": "diadema_lstai",
        "title_prefix": "DIADEMA LST-AI",
        "result_field": "diadema_lstai",
    },
}


def _worker_callback_url() -> str:
    url = os.environ.get("GIRDER_WORKER_CALLBACK_URL") or getApiUrl()
    if "localhost" in url or "127.0.0.1" in url:
        url = url.replace("127.0.0.1", "girder").replace("localhost", "girder")
    return url


class DiademaResource(Resource):
    def __init__(self):
        super().__init__()
        self.resourceName = "diadema_pipeline"

        self.route("POST", (":id", "run", ":toolId"), self.runTool)
        self.route("GET",  (":id", "results"),        self.getResults)
        self.route("DELETE", (":id", "results", ":toolId"), self.deleteResults)
        self.route("POST", ("cleanup_stuck_jobs",),   self.cleanupStuckJobs)

    @access.user(scope=TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description("Avvia un tool DIADEMA su un item NIfTI")
        .modelParam("id", model=Item, level=AccessType.WRITE, destName="item",
                    description="ID dell'item Girder")
        .param("toolId", "Tool da eseguire: mriqc | freesurfer | lstai",
               paramType="path")
        .param("fileId", "ID file specifico (opzionale)", required=False)
        # Parametri comuni
        .param("participantLabel", "BIDS participant label", required=False, default="001")
        # Parametri MRIQC
        .param("modality", "Modalità MRI (T1w, T2w, bold, dwi)", required=False, default="T1w")
        .param("timeout", "Timeout in secondi", required=False, dataType="integer", default=1800)
        # Parametri FreeSurfer
        .param("directive", "Direttiva recon-all", required=False, default="-all")
        .param("openmpThreads", "Thread OpenMP", required=False, dataType="integer", default=4)
        .param("extraFlags", "Flag extra per recon-all", required=False, default="")
        # Parametri LST-AI
        .param("inputType", "Tipo input (T1+FLAIR, T1 only)", required=False, default="T1+FLAIR")
        .param("threshold", "Soglia lesioni (0.0-1.0)", required=False, dataType="float", default=0.5)
        .param("useGpu", "Usa GPU", required=False, dataType="boolean", default=True)
        .errorResponse("Tool non supportato", 400)
        .errorResponse("Item non trovato", 404)
    )
    def runTool(self, item, toolId, fileId, participantLabel, modality, timeout,
                directive, openmpThreads, extraFlags, inputType, threshold, useGpu, params):
        if toolId not in _TOOL_CONFIG:
            raise RestException(f"Tool non supportato: '{toolId}'. Valori ammessi: {list(_TOOL_CONFIG)}", 400)

        cfg = _TOOL_CONFIG[toolId]

        # Importa il task corretto in modo lazy
        if toolId == "mriqc":
            from .tasks import run_mriqc_task as celery_task
            task_kwargs = dict(
                participant_label=participantLabel,
                modality=modality,
                timeout=timeout,
            )
        elif toolId == "freesurfer":
            from .tasks import run_freesurfer_task as celery_task
            task_kwargs = dict(
                participant_label=participantLabel,
                directive=directive,
                openmp_threads=openmpThreads,
                extra_flags=extraFlags,
            )
        else:  # lstai
            from .tasks import run_lstai_task as celery_task
            task_kwargs = dict(
                participant_label=participantLabel,
                input_type=inputType,
                threshold=threshold,
                use_gpu=useGpu,
            )

        # Trova il file
        if fileId:
            file_doc = File().load(fileId, user=self.getCurrentUser(), level=AccessType.READ)
            if file_doc is None:
                raise RestException(f"File {fileId} non trovato", 404)
        else:
            files = list(Item().childFiles(item, limit=1))
            if not files:
                raise RestException("L'item non contiene file", 400)
            file_doc = files[0]

        current_user = self.getCurrentUser()
        job = Job().createJob(
            title=f"{cfg['title_prefix']} – {item['name']}",
            type=cfg["job_type"],
            user=current_user,
            public=False,
            otherFields={"itemId": str(item["_id"]), "fileId": str(file_doc["_id"]), "tool": toolId},
        )
        job_id = str(job["_id"])
        job_token = Job().createJobToken(job)
        job_token_id = str(job_token["_id"])

        job_info_spec = {
            "method": "PUT",
            "url": f"{_worker_callback_url()}/job/{job_id}",
            "reference": job_id,
            "headers": {"Girder-Token": job_token_id},
            "logPrint": True,
        }

        token = Token().createToken(
            user=current_user,
            days=1,
            scope=[TokenScope.DATA_READ, TokenScope.DATA_WRITE, f"jobs.job_{job_id}"],
        )

        Job().updateJob(job, status=JobStatus.QUEUED)

        celery_job = celery_task.apply_async(
            kwargs=dict(
                item_id=str(item["_id"]),
                file_id=str(file_doc["_id"]),
                file_name=file_doc["name"],
                job_id=job_id,
                job_token_id=job_token_id,
                **task_kwargs,
            ),
            headers={
                "girder_client_token": str(token["_id"]),
                "girder_api_url": _worker_callback_url(),
                "jobInfoSpec": job_info_spec,
            },
            queue=cfg["queue"],
        )

        Job().updateJob(job, otherFields={"celeryTaskId": celery_job.id})

        return {
            "job_id": job_id,
            "celery_task_id": celery_job.id,
            "item_id": str(item["_id"]),
            "tool": toolId,
            "status": "queued",
        }

    @access.public(scope=TokenScope.DATA_READ)
    @autoDescribeRoute(
        Description("Restituisce tutti i risultati DIADEMA per un item")
        .modelParam("id", model=Item, level=AccessType.READ, destName="item")
    )
    @filtermodel(model=Item)
    def getResults(self, item, params):
        return item

    @access.user(scope=TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description("Cancella i risultati di un tool dall'item")
        .modelParam("id", model=Item, level=AccessType.WRITE, destName="item")
        .param("toolId", "Tool: mriqc | freesurfer | lstai", paramType="path")
    )
    def deleteResults(self, item, toolId, params):
        if toolId not in _TOOL_CONFIG:
            raise RestException(f"Tool non supportato: {toolId}", 400)
        field = _TOOL_CONFIG[toolId]["result_field"]
        Item().setMetadata(item, {
            f"{field}_results": None,
            f"{field}_status": None,
            f"{field}_error": None,
        })
        return {"message": f"Risultati {toolId} cancellati"}

    @access.admin
    @autoDescribeRoute(
        Description("Marca job DIADEMA bloccati come ERROR")
        .param("dryRun", "Solo mostra senza modificare", dataType="boolean",
               required=False, default=False)
    )
    def cleanupStuckJobs(self, dryRun, params):
        job_types = [cfg["job_type"] for cfg in _TOOL_CONFIG.values()]
        stuck = list(Job().find({
            "type": {"$in": job_types},
            "status": {"$in": [JobStatus.QUEUED, JobStatus.RUNNING]},
        }))
        if not dryRun:
            for job in stuck:
                Job().updateJob(job, status=JobStatus.ERROR,
                                log="[diadema_pipeline] cleanup_stuck_jobs")
        return {
            "dry_run": dryRun,
            "jobs_found": len(stuck),
            "action": "none" if dryRun else "marked_as_error",
            "jobs": [{"id": str(j["_id"]), "type": j.get("type"), "title": j.get("title")} for j in stuck],
        }
