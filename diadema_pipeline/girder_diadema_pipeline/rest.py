"""
REST API per DIADEMA Pipeline
Espone un endpoint generico POST /:id/run/:toolId
che accetta i parametri del tool e li invia alla coda Celery corretta.
"""

import logging
import os

from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import Resource, filtermodel, getApiUrl
from girder.constants import AccessType, TokenScope
from girder.exceptions import RestException
from girder.models.file import File
from girder.models.item import Item
from girder.models.setting import Setting
from girder.models.token import Token
from girder_jobs.constants import JobStatus
from girder_jobs.models.job import Job

logger = logging.getLogger(__name__)

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
        self.route("PUT", (":id", "processing", ":toolId"), self.updateProcessing)
        self.route("GET", (":id", "results"), self.getResults)
        self.route("DELETE", (":id", "results", ":toolId"), self.deleteResults)
        self.route("POST", ("cleanup_stuck_jobs",), self.cleanupStuckJobs)
        self.route("GET", ("settings",), self.getSettings)
        self.route("PUT", ("settings",), self.updateSettings)

    @access.user(scope=TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description("Avvia un tool DIADEMA su un item NIfTI")
        .modelParam(
            "id",
            model=Item,
            level=AccessType.WRITE,
            destName="item",
            description="ID dell'item Girder",
        )
        .param(
            "toolId", "Tool da eseguire: mriqc | freesurfer | lstai", paramType="path"
        )
        .param("fileId", "ID file specifico (opzionale)", required=False)
        # Parametri comuni
        .param(
            "participantLabel", "BIDS participant label", required=False, default="001"
        )
        # Parametri MRIQC
        .param(
            "modality",
            "Modalità MRI (T1w, T2w, bold, dwi)",
            required=False,
            default="T1w",
        )
        .param(
            "timeout",
            "Timeout in secondi",
            required=False,
            dataType="integer",
            default=1800,
        )
        .param(
            "outputBaseDir",
            "Directory output persistente per MRIQC "
            "(default: $DIADEMA_MRIQC_OUTPUT_DIR o /data/diadema/mriqc)",
            required=False,
            default="",
        )
        .param(
            "keepWorkDir",
            "Conserva la work dir MRIQC dopo l'esecuzione",
            required=False,
            dataType="boolean",
            default=False,
        )
        # Parametri FreeSurfer
        .param(
            "directive",
            "Direttiva recon-all: -all | -autorecon1 | -autorecon2 | "
            "-autorecon3 | -autorecon2-cp | -autorecon2-wm",
            required=False,
            default="-all",
        )
        .param("hemi", "Emisfero: both | lh | rh", required=False, default="both")
        .param(
            "openmpThreads",
            "Thread OpenMP per recon-all (1-16)",
            required=False,
            dataType="integer",
            default=4,
        )
        .param(
            "mprage",
            "Usa protocollo MGH MP-RAGE (-mprage)",
            required=False,
            dataType="boolean",
            default=False,
        )
        .param(
            "wsatlas",
            "Skull stripping con atlas (-wsatlas)",
            required=False,
            dataType="boolean",
            default=False,
        )
        .param(
            "deface",
            "Defacing del volume (-deface)",
            required=False,
            dataType="boolean",
            default=False,
        )
        .param(
            "noIsrunning",
            "Salta check 'already running' (raccomandato in container)",
            required=False,
            dataType="boolean",
            default=True,
        )
        .param(
            "extraFlags",
            "Flag extra verbatim per recon-all",
            required=False,
            default="",
        )
        .param(
            "subjectsDir",
            "Directory SUBJECTS_DIR FreeSurfer "
            "(default: $DIADEMA_SUBJECTS_DIR o /data/diadema/subjects)",
            required=False,
            default="",
        )
        .param(
            "keepSubjectsDir",
            "Conserva la cartella soggetto dopo l'esecuzione",
            required=False,
            dataType="boolean",
            default=True,
        )
        .param(
            "fsTimeout",
            "Timeout FreeSurfer in secondi (default 14400 = 4h)",
            required=False,
            dataType="integer",
            default=14400,
        )
        # Parametri LST-AI
        .param(
            "inputType",
            "Tipo input (T1+FLAIR, T1 only)",
            required=False,
            default="T1+FLAIR",
        )
        .param(
            "flairFileId",
            "ID file FLAIR (necessario se inputType=T1+FLAIR)",
            required=False,
        )
        .param(
            "threshold",
            "Soglia lesioni (0.0-1.0)",
            required=False,
            dataType="float",
            default=0.5,
        )
        .param("useGpu", "Usa GPU", required=False, dataType="boolean", default=True)
        .param(
            "force",
            "Forza riesecuzione anche se il tool è già in corso o completato",
            required=False,
            dataType="boolean",
            default=False,
        )
        .errorResponse("Tool non supportato", 400)
        .errorResponse("Job già in corso per questo item/tool", 409)
        .errorResponse("Item non trovato", 404)
    )
    def runTool(
        self,
        item,
        toolId,
        fileId,
        participantLabel,
        modality,
        timeout,
        outputBaseDir,
        keepWorkDir,
        directive,
        hemi,
        openmpThreads,
        mprage,
        wsatlas,
        deface,
        noIsrunning,
        extraFlags,
        subjectsDir,
        keepSubjectsDir,
        fsTimeout,
        inputType,
        flairFileId,
        threshold,
        useGpu,
        force,
        params,
    ):
        if toolId not in _TOOL_CONFIG:
            raise RestException(
                f"Tool non supportato: '{toolId}'. Valori ammessi: {list(_TOOL_CONFIG)}",
                400,
            )

        # ── Controllo double-run (protezione lato server) ─────────────────────
        if not force:
            current_status = (item.get("diadema") or {}).get(toolId, {}).get("status")
            if current_status in ("running", "queued", "processing"):
                raise RestException(
                    f"Un job '{toolId}' è già in corso su questo item "
                    f"(stato: {current_status}). Usa force=true per forzare.",
                    409,
                )
        # ─────────────────────────────────────────────────────────────────────

        # ── Lettura configurazione dal DB (Settings admin) ────────────────────
        from .settings import PluginSettings

        _settings_mriqc_dir = Setting().get(PluginSettings.MRIQC_OUTPUT_DIR) or None
        _settings_subjects_dir = Setting().get(PluginSettings.SUBJECTS_DIR) or None
        _settings_lstai_dir = Setting().get(PluginSettings.LSTAI_OUTPUT_DIR) or None
        # ─────────────────────────────────────────────────────────────────────

        cfg = _TOOL_CONFIG[toolId]

        # Importa il task corretto in modo lazy
        if toolId == "mriqc":
            from .tasks import run_mriqc_task as celery_task

            task_kwargs = dict(
                participant_label=participantLabel,
                modality=modality,
                timeout=timeout,
                # Priorità: kwarg esplicito → settings admin → env var → default
                output_base_dir=outputBaseDir or _settings_mriqc_dir or None,
                keep_work_dir=keepWorkDir,
            )
        elif toolId == "freesurfer":
            from .tasks import run_freesurfer_task as celery_task

            task_kwargs = dict(
                participant_label=participantLabel,
                directive=directive,
                hemi=hemi,
                openmp_threads=openmpThreads,
                mprage=mprage,
                wsatlas=wsatlas,
                deface=deface,
                no_isrunning=noIsrunning,
                extra_flags=extraFlags,
                # Priorità: kwarg esplicito → settings admin → env var → default
                subjects_dir=subjectsDir or _settings_subjects_dir or None,
                keep_subjects_dir=keepSubjectsDir,
                timeout=fsTimeout,
            )
        else:  # lstai
            from .tasks import run_lstai_task as celery_task

            # Validazione threshold
            if not (0.0 <= threshold <= 1.0):
                raise RestException(
                    f"threshold deve essere nell'intervallo [0.0, 1.0], ricevuto: {threshold}",
                    400,
                )
            task_kwargs = dict(
                participant_label=participantLabel,
                input_type=inputType,
                flair_file_id=flairFileId,
                threshold=threshold,
                use_gpu=useGpu,
                output_base_dir=_settings_lstai_dir or None,
            )

        # Trova il file
        if fileId:
            file_doc = File().load(
                fileId, user=self.getCurrentUser(), level=AccessType.READ
            )
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
            otherFields={
                "itemId": str(item["_id"]),
                "fileId": str(file_doc["_id"]),
                "tool": toolId,
            },
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

        # Scrivi subito lo stato 'queued' in item.diadema così:
        # - il check double-run funziona anche prima che il worker parta
        # - dopo un refresh la pagina vede lo stato e riprende il polling
        Item().update(
            {"_id": item["_id"]},
            {
                "$set": {
                    f"diadema.{toolId}.status": "queued",
                    f"diadema.{toolId}.job_id": job_id,
                }
            },
            multi=False,
        )

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
        Description("Restituisce tutti i risultati DIADEMA per un item").modelParam(
            "id", model=Item, level=AccessType.READ, destName="item"
        )
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
        Item().update(
            {"_id": item["_id"]},
            {"$unset": {f"diadema.{toolId}": ""}},
            multi=False,
        )
        return {"message": f"Risultati {toolId} cancellati"}

    @access.user(scope=TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description(
            "Aggiorna i dati di elaborazione DIADEMA per un tool (usato dai worker)"
        )
        .modelParam(
            "id",
            model=Item,
            level=AccessType.WRITE,
            destName="item",
            description="ID dell'item Girder",
        )
        .param("toolId", "Tool: mriqc | freesurfer | lstai", paramType="path")
        .jsonParam(
            "data",
            "Campi da aggiornare: status, results, error, job_id",
            requireObject=True,
            paramType="body",
        )
        .errorResponse("Tool non supportato", 400)
    )
    def updateProcessing(self, item, toolId, data, params):
        if toolId not in _TOOL_CONFIG:
            raise RestException(f"Tool non supportato: {toolId}", 400)
        Item().update(
            {"_id": item["_id"]},
            {"$set": {f"diadema.{toolId}.{k}": v for k, v in data.items()}},
            multi=False,
        )
        return {"updated": True, "tool": toolId, "fields": list(data.keys())}

    @access.admin
    @autoDescribeRoute(
        Description("Marca job DIADEMA bloccati come ERROR")
        .param(
            "dryRun",
            "Solo mostra senza modificare",
            dataType="boolean",
            required=False,
            default=False,
        )
        .param(
            "limit",
            "Numero massimo di job da processare",
            dataType="integer",
            required=False,
            default=100,
        )
    )
    def cleanupStuckJobs(self, dryRun, limit, params):
        job_types = [cfg["job_type"] for cfg in _TOOL_CONFIG.values()]
        stuck = list(
            Job().find(
                {
                    "type": {"$in": job_types},
                    "status": {"$in": [JobStatus.QUEUED, JobStatus.RUNNING]},
                },
                limit=limit,
            )
        )
        if not dryRun:
            for job in stuck:
                Job().updateJob(
                    job,
                    status=JobStatus.ERROR,
                    log="[diadema_pipeline] cleanup_stuck_jobs",
                )
        return {
            "dry_run": dryRun,
            "jobs_found": len(stuck),
            "limit": limit,
            "action": "none" if dryRun else "marked_as_error",
            "jobs": [
                {"id": str(j["_id"]), "type": j.get("type"), "title": j.get("title")}
                for j in stuck
            ],
        }

    # ── Settings endpoints ────────────────────────────────────────────────────

    @access.admin
    @autoDescribeRoute(
        Description("Restituisce la configurazione corrente del plugin DIADEMA")
    )
    def getSettings(self, params):
        from .settings import PluginSettings

        keys = [
            PluginSettings.OUTPUT_STORAGE,
            PluginSettings.MRIQC_OUTPUT_DIR,
            PluginSettings.SUBJECTS_DIR,
            PluginSettings.LSTAI_OUTPUT_DIR,
            PluginSettings.WIDGET_ENABLED,
            PluginSettings.WIDGET_FIELDS_MRIQC,
            PluginSettings.WIDGET_FIELDS_FREESURFER,
        ]
        return {key: Setting().get(key) for key in keys}

    @access.admin
    @autoDescribeRoute(
        Description(
            "Aggiorna uno o più valori di configurazione del plugin DIADEMA"
        ).jsonParam(
            "settings",
            "Oggetto JSON con coppie {chiave: valore}",
            requireObject=True,
            paramType="body",
        )
    )
    def updateSettings(self, settings, params):
        from .settings import PluginSettings

        allowed_keys = {
            PluginSettings.OUTPUT_STORAGE,
            PluginSettings.MRIQC_OUTPUT_DIR,
            PluginSettings.SUBJECTS_DIR,
            PluginSettings.LSTAI_OUTPUT_DIR,
            PluginSettings.WIDGET_ENABLED,
            PluginSettings.WIDGET_FIELDS_MRIQC,
            PluginSettings.WIDGET_FIELDS_FREESURFER,
        }
        unknown = set(settings.keys()) - allowed_keys
        if unknown:
            raise RestException(
                f"Chiavi non riconosciute: {sorted(unknown)}. "
                f"Chiavi valide: {sorted(allowed_keys)}",
                400,
            )
        updated = {}
        for key, value in settings.items():
            Setting().set(key, value)
            updated[key] = value
            logger.info("[diadema_pipeline] Settings aggiornati: %s = %r", key, value)
        return {"updated": updated}
