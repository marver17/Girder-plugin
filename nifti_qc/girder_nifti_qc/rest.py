"""
REST API endpoints for NIfTI Quality Control
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


def _worker_callback_url() -> str:
    """Return the Girder API URL that Celery workers can actually reach.

    When running in Docker, Girder's own getApiUrl() returns
    http://localhost:8080/api/v1 which is unreachable from other containers.
    Priority:
      1. GIRDER_WORKER_CALLBACK_URL env var (explicit override)
      2. getApiUrl() with localhost/127.0.0.1 replaced by the Docker service
         hostname 'girder' so workers on the same bridge network can reach it.
    """
    url = os.environ.get("GIRDER_WORKER_CALLBACK_URL") or getApiUrl()
    # If the URL still points to localhost (env var missing or Girder not
    # restarted after docker-compose change), rewrite it to the Docker service
    # hostname so the mriqc-worker container can call back on the bridge network.
    if "localhost" in url or "127.0.0.1" in url:
        url = url.replace("127.0.0.1", "girder").replace("localhost", "girder")
    return url


class NiftiQC(Resource):
    """REST resource for NIfTI quality control operations"""

    def __init__(self):
        super().__init__()
        self.resourceName = "nifti_qc"

        # Register routes
        self.route("POST", (":id", "run_mriqc"), self.runMRIQC)
        self.route("POST", (":id", "quick_check"), self.quickCheck)
        self.route("GET", (":id", "results"), self.getResults)
        self.route("DELETE", (":id", "results"), self.deleteResults)
        self.route("POST", ("cleanup_stuck_jobs",), self.cleanupStuckJobs)

    @access.user(scope=TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description("Run MRIQC quality control on NIfTI file")
        .notes(
            "This will launch a Girder Worker job that executes MRIQC in a Docker container. "
            "Processing time varies but typically takes 5-30 minutes depending on file size and complexity."
        )
        .modelParam(
            "id",
            model=Item,
            level=AccessType.WRITE,
            destName="item",
            description="The item containing the NIfTI file",
        )
        .param(
            "fileId",
            "ID of the specific NIfTI file to process (optional, will use first .nii/.nii.gz)",
            required=False,
        )
        .param(
            "participantLabel",
            "BIDS participant label (default: 001)",
            required=False,
            default="001",
        )
        .param(
            "modality",
            "MRI modality (T1w, T2w, bold, etc.)",
            required=False,
            default="T1w",
        )
        .param(
            "timeout",
            "Maximum execution time in seconds",
            required=False,
            dataType="integer",
            default=1800,
        )
        .errorResponse("Item not found", 404)
        .errorResponse("Write access denied", 403)
    )
    def runMRIQC(self, item, fileId, participantLabel, modality, timeout):
        """Launch MRIQC quality control job"""
        from .tasks import run_mriqc_task

        # Find NIfTI file
        if not fileId:
            files = list(File().find({"itemId": item["_id"]}))
            nifti_files = [f for f in files if f["name"].endswith((".nii", ".nii.gz"))]

            if not nifti_files:
                raise RestException("No NIfTI file found in this item")

            file_obj = nifti_files[0]
            fileId = str(file_obj["_id"])

        # Get file name for context
        file_obj = File().load(fileId, force=True)
        file_name = file_obj.get("name", "unknown") if file_obj else "unknown"

        job_title = f"MRIQC: {file_name} ({modality}, sub-{participantLabel})"

        # Crea il record Job su Girder PRIMA di inviare il task a Celery.
        # Il job deve esistere prima del token perché lo scope del token
        # include jobs.job_{id} — necessario per il polling dello stato.
        job = Job().createJob(
            title=job_title,
            type="mriqc",
            user=self.getCurrentUser(),
            handler="worker_handler",
        )
        # Job token: scope limitato all'aggiornamento di questo singolo job
        job_token = Job().createJobToken(job)

        # Token worker: creato dopo il job così possiamo includere lo scope
        # jobs.job_{id} che abilita la lettura dello stato del job.
        # Senza questo scope GET /job/{id} risponde 401 e il polling di
        # cancellazione non funziona.
        token = Token().createToken(
            user=self.getCurrentUser(),
            days=1,
            scope=[
                TokenScope.DATA_READ,
                TokenScope.DATA_WRITE,
                f"jobs.job_{str(job['_id'])}",
            ],
        )
        # jobInfoSpec è il formato atteso da girder_worker.utils._job_manager().
        # Deve corrispondere esattamente ai parametri del costruttore JobManager:
        #   logPrint, url, method, headers, reference
        # Passarlo direttamente nell'header fa sì che girder_before_task_publish
        # lo trovi già presente e salti create_task_job() (che creerebbe un
        # secondo job duplicato e userebbe URL irraggiungibili dall'host).
        job_info_spec = {
            "method": "PUT",
            "url": "/".join((_worker_callback_url(), "job", str(job["_id"]))),
            "reference": str(job["_id"]),
            "headers": {"Girder-Token": str(job_token["_id"])},
            "logPrint": True,
        }
        # Usa updateJob invece di scheduleJob: scheduleJob emette
        # l'evento jobs.schedule che girder_plugin_worker intercetta
        # e invia un secondo task legacy girder_worker.run — duplicato.
        Job().updateJob(job, status=JobStatus.QUEUED)

        # Segna l'item come in elaborazione
        Item().setMetadata(
            item,
            {
                "nifti_qc_status": "processing",
                "nifti_qc_job_id": str(job["_id"]),
                "nifti_qc_started": str(self.getCurrentUser()["_id"]),
            },
        )

        # Lancia il task Celery — jobInfoSpec passato come header Celery
        # (NON jobInfo) così girder_before_task_publish trova già jobInfoSpec,
        # salta create_task_job() ed il worker inizializza correttamente
        # task.job_manager senza creare job duplicati o incontrare URL localhost.
        try:
            celery_job = run_mriqc_task.apply_async(
                kwargs={
                    "item_id": str(item["_id"]),
                    "file_id": fileId,
                    "participant_label": participantLabel,
                    "modality": modality,
                    "timeout": timeout,
                    "file_name": file_name,
                    # Passati esplicitamente perché il task aggiorna lo stato
                    # del job via REST (non tramite job_manager che potrebbe
                    # essere None se task_prerun non si aggancia).
                    "job_id": str(job["_id"]),
                    "job_token_id": str(job_token["_id"]),
                },
                headers={
                    "girder_client_token": str(token["_id"]),
                    "girder_api_url": _worker_callback_url(),
                    "jobInfoSpec": job_info_spec,
                },
                queue="mriqc",
            )
            print(
                f"DEBUG REST runMRIQC: apply_async success, celery_id={celery_job.id}, job_id={str(job['_id'])}"
            )
            # Salva il Celery task ID sul job record: il handler cancel() di
            # girder_plugin_worker lo usa per revocare il task via AsyncResult.
            # Senza questo campo il Cancel button non funziona.
            Job().updateJob(job, otherFields={"celeryTaskId": celery_job.id})
        except Exception as e:
            print(f"DEBUG REST runMRIQC: apply_async FAILED: {e}")
            import traceback

            print(traceback.format_exc())
            raise RestException(f"Failed to submit MRIQC job: {e}", code=500)

        return {
            "job_id": str(job["_id"]),
            "celery_id": celery_job.id,
            "item_id": str(item["_id"]),
            "file_id": fileId,
            "status": "queued",
            "message": "MRIQC job submitted to worker. This may take 5-30 minutes.",
            "participant_label": participantLabel,
            "modality": modality,
        }

    @access.user(scope=TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description("Quick NIfTI structure check (no MRIQC)")
        .notes(
            "Fast validation that only checks NIfTI header and basic statistics. "
            "Use this for testing or quick validation."
        )
        .modelParam("id", model=Item, level=AccessType.WRITE, destName="item")
        .param("fileId", "ID of the NIfTI file", required=False)
    )
    def quickCheck(self, item, fileId):
        """Quick NIfTI validation without full MRIQC"""
        from .tasks import quick_nifti_check

        if not fileId:
            files = list(File().find({"itemId": item["_id"]}))
            nifti_files = [f for f in files if f["name"].endswith((".nii", ".nii.gz"))]

            if not nifti_files:
                raise RestException("No NIfTI file found")

            file_obj = nifti_files[0]
            fileId = str(file_obj["_id"])

        # Get file name for context
        file_obj = File().load(fileId, force=True)
        file_name = file_obj.get("name", "unknown") if file_obj else "unknown"

        # Crea il job prima del token (serve l'ID per lo scope)
        job = Job().createJob(
            title=f"Quick NIfTI Check: {file_name}",
            type="nifti_quick_check",
            user=self.getCurrentUser(),
            handler="worker_handler",
        )
        job_token = Job().createJobToken(job)

        token = Token().createToken(
            user=self.getCurrentUser(),
            days=1,
            scope=[
                TokenScope.DATA_READ,
                TokenScope.DATA_WRITE,
                f"jobs.job_{str(job['_id'])}",
            ],
        )
        job_info_spec = {
            "method": "PUT",
            "url": "/".join((_worker_callback_url(), "job", str(job["_id"]))),
            "reference": str(job["_id"]),
            "headers": {"Girder-Token": str(job_token["_id"])},
            "logPrint": True,
        }
        # Usa updateJob invece di scheduleJob (evita dispatch duplicato)
        Job().updateJob(job, status=JobStatus.QUEUED)

        # Lancia il task — jobInfoSpec come header Celery (non jobInfo).
        # Usa la coda 'mriqc': è l'unico worker Celery attivo nel docker-compose.
        celery_job = quick_nifti_check.apply_async(
            kwargs={
                "item_id": str(item["_id"]),
                "file_id": fileId,
                "file_name": file_name,
                "job_id": str(job["_id"]),
                "job_token_id": str(job_token["_id"]),
            },
            headers={
                "girder_client_token": str(token["_id"]),
                "girder_api_url": _worker_callback_url(),
                "jobInfoSpec": job_info_spec,
            },
            queue="mriqc",
        )
        # Salva il Celery task ID sul job: necessario per il Cancel button.
        Job().updateJob(job, otherFields={"celeryTaskId": celery_job.id})

        return {
            "job_id": str(job["_id"]),
            "celery_id": celery_job.id,
            "item_id": str(item["_id"]),
            "status": "queued",
            "message": "Quick check job submitted (fast, ~30 seconds)",
        }

    @access.public(scope=TokenScope.DATA_READ)
    @autoDescribeRoute(
        Description("Get QC results for an item").modelParam(
            "id", model=Item, level=AccessType.READ, destName="item"
        )
    )
    @filtermodel(model=Item)
    def getResults(self, item):
        """Retrieve QC results stored in item"""
        return item

    @access.user(scope=TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description("Delete QC results from item").modelParam(
            "id", model=Item, level=AccessType.WRITE, destName="item"
        )
    )
    def deleteResults(self, item):
        """Remove QC results from item metadata"""

        Item().setMetadata(
            item,
            {"nifti_qc_results": None, "nifti_qc_status": None, "nifti_qc_error": None},
        )

        return {"message": "QC results deleted"}

    @access.admin
    @autoDescribeRoute(
        Description(
            "Marca come ERROR tutti i job MRIQC/QuickCheck bloccati in QUEUED o RUNNING. "
            "Da usare dopo un crash/restart del worker per sbloccare la lista job."
        ).param(
            "dryRun",
            "Se true, elenca i job senza modificarli (default: false)",
            required=False,
            dataType="boolean",
            default=False,
        )
    )
    def cleanupStuckJobs(self, dryRun):
        """Reset job bloccati rimasti in QUEUED/RUNNING dopo un crash del worker."""
        import datetime

        stuck_types = {"mriqc", "nifti_quick_check"}
        # JobStatus: QUEUED=1, RUNNING=2
        stuck_statuses = [JobStatus.QUEUED, JobStatus.RUNNING]

        job_model = Job()
        stuck = list(
            job_model.find(
                {
                    "type": {"$in": list(stuck_types)},
                    "status": {"$in": stuck_statuses},
                }
            )
        )

        result = []
        for job in stuck:
            result.append(
                {
                    "job_id": str(job["_id"]),
                    "title": job.get("title", ""),
                    "type": job.get("type", ""),
                    "status": job.get("status"),
                    "updated": str(job.get("updated", "")),
                }
            )
            if not dryRun:
                job_model.updateJob(
                    job,
                    status=JobStatus.ERROR,
                    log=(
                        f"[nifti_qc] Job marcato come ERROR da cleanupStuckJobs "
                        f"alle {datetime.datetime.now(datetime.timezone.utc).isoformat()} "
                        "(worker crash / restart rilevato).\n"
                    ),
                )

        return {
            "dry_run": dryRun,
            "jobs_found": len(result),
            "jobs": result,
            "action": "listed only" if dryRun else "marked as ERROR",
        }
