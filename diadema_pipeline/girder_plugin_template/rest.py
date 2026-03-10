"""
REST API per Plugin Template
──────────────────────────────────────────────────────────────────────────────
Pattern Girder REST:
  - Classe che estende Resource
  - self.resourceName definisce il path sotto /api/v1/
  - Route registrate nel __init__ con self.route(METHOD, PATH_TUPLE, HANDLER)
  - Decoratori: @access.user/public/admin + @autoDescribeRoute
  - @filtermodel su endpoint che restituiscono modelli Girder
──────────────────────────────────────────────────────────────────────────────
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
    """
    Restituisce l'URL dell'API Girder raggiungibile dal container worker.

    Problema: getApiUrl() può restituire http://localhost:8080/api/v1, che è
    irraggiungibile dall'interno di un container Docker. La env var
    GIRDER_WORKER_CALLBACK_URL permette di specificare l'hostname corretto
    (es. http://girder:8080/api/v1).
    """
    url = os.environ.get("GIRDER_WORKER_CALLBACK_URL") or getApiUrl()
    if "localhost" in url or "127.0.0.1" in url:
        url = url.replace("127.0.0.1", "girder").replace("localhost", "girder")
    return url


class PluginTemplateResource(Resource):
    """
    Resource REST per Plugin Template.

    Espone gli endpoint sotto /api/v1/plugin_template/
    """

    def __init__(self):
        super().__init__()
        self.resourceName = "plugin_template"

        # Registra le route: (metodo HTTP, tupla path, handler)
        # ":id" è un parametro dinamico (es. item ID)
        self.route("POST", (":id", "run"),     self.runTask)
        self.route("GET",  (":id", "results"), self.getResults)
        self.route("DELETE", (":id", "results"), self.deleteResults)
        self.route("POST", ("cleanup_stuck_jobs",), self.cleanupStuckJobs)

    # ──────────────────────────────────────────────────────────────────────────
    # POST /api/v1/plugin_template/:id/run
    # ──────────────────────────────────────────────────────────────────────────
    @access.user(scope=TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description("Avvia il task asincrono sull'item specificato")
        .notes(
            "Crea un Job Girder e lo invia alla coda Celery. "
            "Restituisce subito con lo stato 'queued'."
        )
        .modelParam(
            "id",
            model=Item,
            level=AccessType.WRITE,
            destName="item",
            description="ID dell'item Girder su cui eseguire il task",
        )
        .param(
            "fileId",
            "ID del file specifico (opzionale, usa il primo file dell'item se assente)",
            required=False,
        )
        # ── Aggiungi qui altri parametri specifici del tuo task ──
        # .param("myParam", "Descrizione", required=False, default="valore")
        .errorResponse("Item non trovato", 404)
        .errorResponse("Accesso negato", 403)
    )
    def runTask(self, item, fileId, params):
        """
        Pattern per avviare un task Celery con Girder Worker:

        1. Trova il file su cui operare (auto-detect se fileId non fornito)
        2. Crea il Job record su Girder (PRIMA del token: serve l'_id per lo scope)
        3. Costruisce jobInfoSpec
        4. Crea token con scope limitato
        5. Aggiorna lo stato del job a QUEUED (NON scheduleJob)
        6. apply_async con jobInfoSpec come HEADER Celery (non kwarg!)
        7. Salva celeryTaskId sul job (per il Cancel button)
        """
        from .tasks import plugin_template_task

        # ── 1. Trova il file ──────────────────────────────────────────────────
        if fileId:
            file_doc = File().load(fileId, user=self.getCurrentUser(), level=AccessType.READ)
            if file_doc is None:
                raise RestException(f"File {fileId} non trovato", 404)
        else:
            # Auto-detect: primo file dell'item
            files = list(Item().childFiles(item, limit=1))
            if not files:
                raise RestException("L'item non contiene file", 400)
            file_doc = files[0]

        # ── 2. Crea il Job record ─────────────────────────────────────────────
        # IMPORTANTE: crea il Job prima del token perché lo scope del token
        # include il job ID (jobs.job_<id>).
        current_user = self.getCurrentUser()
        job = Job().createJob(
            title=f"Plugin Template – {item['name']}",
            type="plugin_template",
            user=current_user,
            public=False,
            otherFields={
                "itemId": str(item["_id"]),
                "fileId": str(file_doc["_id"]),
            },
        )
        job_id = str(job["_id"])
        job_token = Job().createJobToken(job)
        job_token_id = str(job_token["_id"])

        # ── 3. jobInfoSpec ────────────────────────────────────────────────────
        # Formato atteso da girder_worker.utils.JobManager
        job_info_spec = {
            "method": "PUT",
            "url": f"{_worker_callback_url()}/job/{job_id}",
            "reference": job_id,
            "headers": {"Girder-Token": job_token_id},
            "logPrint": True,
        }

        # ── 4. Token con scope limitato ───────────────────────────────────────
        token = Token().createToken(
            user=current_user,
            days=1,
            scope=[
                TokenScope.DATA_READ,
                TokenScope.DATA_WRITE,
                f"jobs.job_{job_id}",
            ],
        )

        # ── 5. Aggiorna lo stato a QUEUED ─────────────────────────────────────
        # USA updateJob, NON scheduleJob.
        # scheduleJob scatena l'evento 'jobs.schedule' che girder_plugin_worker
        # consuma per fare apply_async → job duplicato!
        Job().updateJob(job, status=JobStatus.QUEUED)

        # ── 6. apply_async ────────────────────────────────────────────────────
        # jobInfoSpec va passato come HEADER Celery, non come kwarg.
        # girder_before_task_publish intercetta i kwargs riservati e crea
        # un job duplicato; passandoli come header li bypassa.
        celery_job = plugin_template_task.apply_async(
            kwargs=dict(
                item_id=str(item["_id"]),
                file_id=str(file_doc["_id"]),
                file_name=file_doc["name"],
                job_id=job_id,
                job_token_id=job_token_id,
                # ── aggiungi qui eventuali param extra ──
            ),
            headers={
                "girder_client_token": str(token["_id"]),
                "girder_api_url": _worker_callback_url(),
                "jobInfoSpec": job_info_spec,
            },
            queue="plugin_template",   # nome della coda Celery
        )

        # ── 7. Salva celeryTaskId ─────────────────────────────────────────────
        Job().updateJob(job, otherFields={"celeryTaskId": celery_job.id})

        return {
            "job_id": job_id,
            "celery_task_id": celery_job.id,
            "item_id": str(item["_id"]),
            "file_id": str(file_doc["_id"]),
            "status": "queued",
        }

    # ──────────────────────────────────────────────────────────────────────────
    # GET /api/v1/plugin_template/:id/results
    # ──────────────────────────────────────────────────────────────────────────
    @access.public(scope=TokenScope.DATA_READ)
    @autoDescribeRoute(
        Description("Restituisce i risultati del task per l'item specificato")
        .modelParam("id", model=Item, level=AccessType.READ, destName="item")
        .errorResponse("Item non trovato", 404)
    )
    @filtermodel(model=Item)
    def getResults(self, item, params):
        """
        @filtermodel applica il filtro di sicurezza Girder sull'item:
        rimuove i campi non esposti (quelli non in exposeFields).
        I campi "plugin_template_results" e "plugin_template_status"
        devono essere registrati in __init__.py con exposeFields().
        """
        return item

    # ──────────────────────────────────────────────────────────────────────────
    # DELETE /api/v1/plugin_template/:id/results
    # ──────────────────────────────────────────────────────────────────────────
    @access.user(scope=TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description("Cancella i risultati del task dall'item")
        .modelParam("id", model=Item, level=AccessType.WRITE, destName="item")
        .errorResponse("Item non trovato", 404)
    )
    def deleteResults(self, item, params):
        Item().setMetadata(
            item,
            {
                "plugin_template_results": None,
                "plugin_template_status": None,
                "plugin_template_error": None,
            },
        )
        return {"message": "Risultati cancellati"}

    # ──────────────────────────────────────────────────────────────────────────
    # POST /api/v1/plugin_template/cleanup_stuck_jobs
    # ──────────────────────────────────────────────────────────────────────────
    @access.admin
    @autoDescribeRoute(
        Description("Marca come ERROR i job bloccati in QUEUED o RUNNING")
        .notes("Endpoint admin. Utile in sviluppo dopo un crash del worker.")
        .param(
            "dryRun",
            "Se True, mostra i job senza modificarli",
            dataType="boolean",
            required=False,
            default=False,
        )
    )
    def cleanupStuckJobs(self, dryRun, params):
        stuck = list(
            Job().find(
                {"type": "plugin_template", "status": {"$in": [JobStatus.QUEUED, JobStatus.RUNNING]}}
            )
        )
        if not dryRun:
            for job in stuck:
                Job().updateJob(
                    job,
                    status=JobStatus.ERROR,
                    log="[plugin_template] cleanup_stuck_jobs: marcato come ERROR",
                )
        return {
            "dry_run": dryRun,
            "jobs_found": len(stuck),
            "action": "none" if dryRun else "marked_as_error",
            "jobs": [{"id": str(j["_id"]), "title": j.get("title")} for j in stuck],
        }
