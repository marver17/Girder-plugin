"""
REST API per DIADEMA Pipeline
Espone un endpoint generico POST /:id/run/:toolId
che accetta i parametri del tool e li invia alla coda Celery corretta.
"""

import logging
import os

import cherrypy
from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import Resource, filtermodel, getApiUrl, getCurrentToken
from girder.constants import AccessType, TokenScope
from girder.exceptions import RestException
from girder.models.file import File
from girder.models.folder import Folder
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
        self.route("POST", (":id", "cancel", ":toolId"), self.cancelJob)
        self.route("POST", (":id", "reset", ":toolId"), self.resetJob)
        self.route("POST", ("job", ":jobId", "force_cancelled"), self.forceJobCancelled)
        self.route("PUT", (":id", "processing", ":toolId"), self.updateProcessing)
        self.route("GET", (":id", "results"), self.getResults)
        self.route("GET", (":id", "derivatives_root"), self.resolveDerivativesRoot)
        self.route("GET", (":id", "participant_label"), self.resolveParticipantLabel)
        self.route("DELETE", (":id", "results", ":toolId"), self.deleteResults)
        self.route("POST", ("cleanup_stuck_jobs",), self.cleanupStuckJobs)
        self.route("GET", ("settings",), self.getSettings)
        self.route("PUT", ("settings",), self.updateSettings)
        # Session-level endpoints (BIDS ses-XX / sub-XX folder)
        self.route("POST", ("session", ":folderId", "run", ":toolId"), self.runSessionTool)
        self.route("POST", ("session", ":folderId", "cancel", ":toolId"), self.cancelSessionJob)
        self.route("POST", ("session", ":folderId", "reset", ":toolId"), self.resetSessionJob)
        self.route("PUT", ("session", ":folderId", "processing", ":toolId"), self.updateSessionProcessing)
        self.route("GET", ("session", ":folderId", "results"), self.getSessionResults)
        self.route("GET", ("session", ":folderId", "participant_label"), self.resolveSessionParticipantLabel)
        self.route("GET", ("session", ":folderId", "files"), self.getSessionFiles)

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
            "participantLabel",
            "BIDS participant label (es. 003). Vuoto = rilevazione automatica da nome file/cartella",
            required=False,
            default="",
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
            "derivativesRootId",
            "ID folder Girder da usare come radice del dataset BIDS per i derivatives "
            "(lascia vuoto per stima automatica: risale la gerarchia cercando dataset_description.json)",
            required=False,
            default="",
        )
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
        derivativesRootId,
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
                derivatives_root_id=derivativesRootId or None,
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
                derivatives_root_id=derivativesRootId or None,
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

    @access.user(scope=TokenScope.DATA_READ)
    @autoDescribeRoute(
        Description(
            "Anteprima del participant label BIDS che verrebbe rilevato automaticamente per questo item."
        )
        .modelParam("id", model=Item, level=AccessType.READ, destName="item")
        .param(
            "hint",
            "Valore esplicito (come da form). Vuoto = auto-detect puro.",
            required=False,
            default="",
        )
    )
    def resolveParticipantLabel(self, item, hint, params):
        from girder_client import GirderClient

        from .tasks._helpers import bids_resolve_participant_label

        token = getCurrentToken()
        gc = GirderClient(apiUrl=cherrypy.request.base + "/api/v1")
        gc.token = str(token["_id"])

        item_id = str(item["_id"])
        resolved = bids_resolve_participant_label(gc, item_id, hint or None)

        # Determina la sorgente per l'UI
        hint_clean = (hint or "").strip().lstrip("sub-").lstrip("sub_")
        import re

        item_name = item.get("name", "")
        m_file = re.search(
            r"(?:^|[_\-.])sub[-_]([a-zA-Z0-9]+)", item_name, re.IGNORECASE
        )

        if hint_clean and re.sub(r"[^a-zA-Z0-9]", "", hint_clean):
            source = "manual"
        elif m_file and m_file.group(1) == resolved:
            source = "filename"
        elif resolved != "001":
            source = "folder"
        else:
            source = "fallback"

        return {
            "label": resolved,
            "subject_id": f"sub-{resolved}",
            "source": source,
            "item_name": item_name,
        }

    @access.user(scope=TokenScope.DATA_READ)
    @autoDescribeRoute(
        Description(
            "Stima la cartella radice del dataset BIDS per i derivatives di un item. "
            "Risale la gerarchia cercando dataset_description.json; fallback alla collection."
        )
        .modelParam("id", model=Item, level=AccessType.READ, destName="item")
        .param(
            "overrideId",
            "ID folder da usare come radice (override, opzionale)",
            required=False,
            default="",
        )
    )
    def resolveDerivativesRoot(self, item, overrideId, params):
        """Restituisce il path breadcrumb della radice BIDS stimata (o dell'override)."""

        def _folder_path(folder_id):
            """Costruisce il breadcrumb folder/sottofolder/../nome."""
            parts = []
            fid = folder_id
            for _ in range(15):
                try:
                    f = Folder().load(fid, force=True)
                    if not f:
                        break
                    parts.append(f["name"])
                    parent_type = f.get("parentCollection", "folder")
                    fid = str(f.get("parentId", ""))
                    if parent_type == "collection" or not fid:
                        # aggiungi il nome collection
                        from girder.models.collection import Collection

                        try:
                            col = Collection().load(f.get("parentId"), force=True)
                            if col:
                                parts.append(col["name"])
                        except Exception:
                            pass
                        break
                except Exception:
                    break
            parts.reverse()
            return " / ".join(parts) if parts else "(root)"

        if overrideId:
            # Verifica che la folder esista e restituisce il suo path
            try:
                folder = Folder().load(overrideId, force=True)
                if not folder:
                    return {"error": "Folder non trovata", "resolved": False}
                path = _folder_path(overrideId)
                return {
                    "resolved": True,
                    "root_id": overrideId,
                    "root_type": "folder",
                    "breadcrumb": path,
                    "derivatives_path": f"{path} / derivatives / mriqc / sub-xxx / anat",
                    "source": "override",
                }
            except Exception as exc:
                return {"error": str(exc), "resolved": False}

        # Stima automatica: risale la gerarchia
        folder_id = str(item.get("folderId", ""))
        if not folder_id:
            return {"resolved": False, "error": "Item senza folderId"}

        current_id = folder_id
        for _ in range(10):
            # Cerca dataset_description.json nella folder corrente
            desc = list(
                Item().find(
                    {
                        "folderId": Folder().load(current_id, force=True)["_id"],
                        "name": "dataset_description.json",
                    },
                    limit=1,
                )
            )
            if desc:
                path = _folder_path(current_id)
                return {
                    "resolved": True,
                    "root_id": current_id,
                    "root_type": "folder",
                    "breadcrumb": path,
                    "derivatives_path": f"{path} / derivatives / mriqc / sub-xxx / anat",
                    "source": "auto",
                }
            f = Folder().load(current_id, force=True)
            if not f:
                break
            parent_type = f.get("parentCollection", "folder")
            parent_id = str(f.get("parentId", ""))
            if not parent_id or parent_type == "collection":
                # Fallback: radice collection
                from girder.models.collection import Collection

                try:
                    col = Collection().load(f.get("parentId"), force=True)
                    col_name = col["name"] if col else "collection"
                    folder_path = _folder_path(folder_id)
                    return {
                        "resolved": True,
                        "root_id": parent_id,
                        "root_type": "collection",
                        "breadcrumb": col_name,
                        "derivatives_path": f"{col_name} / derivatives / mriqc / sub-xxx / anat",
                        "source": "fallback_collection",
                        "warning": (
                            "dataset_description.json non trovato nella gerarchia. "
                            "I derivatives verranno salvati nella radice della collection. "
                            "Considera di specificare manualmente il Dataset root ID."
                        ),
                    }
                except Exception:
                    break
            current_id = parent_id

        return {
            "resolved": False,
            "error": "Impossibile determinare la radice del dataset",
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
            "Forza lo stato di un job DIADEMA a CANCELLED (5), "
            "bypassa la validazione delle transizioni di stato di Girder. "
            "Usato dai worker quando la transizione CANCELING(824)→CANCELLED(5) "
            "viene rifiutata dalla normale API."
        ).param("jobId", "ID del job Girder", paramType="path")
    )
    def forceJobCancelled(self, jobId, params):
        from bson import ObjectId

        try:
            oid = ObjectId(jobId)
        except Exception:
            raise RestException(f"jobId non valido: {jobId}", 400)

        job = Job().load(oid, force=True)
        if not job:
            raise RestException(f"Job {jobId} non trovato", 404)

        # Aggiornamento diretto MongoDB — bypassa la validazione delle transizioni
        Job().update(
            {"_id": oid},
            {
                "$set": {
                    "status": 5,
                    "updated": __import__("datetime").datetime.utcnow(),
                }
            },
            multi=False,
        )
        return {"forced": True, "job_id": jobId, "status": 5}

    @access.user(scope=TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description(
            "Resetta forzatamente un tool DIADEMA bloccato (es. stuck in cancelling). "
            "Imposta job a CANCELLED (direct MongoDB) e item.diadema a 'cancelled'."
        )
        .modelParam("id", model=Item, level=AccessType.WRITE, destName="item")
        .param("toolId", "Tool: mriqc | freesurfer | lstai", paramType="path")
    )
    def resetJob(self, item, toolId, params):
        if toolId not in _TOOL_CONFIG:
            raise RestException(f"Tool non supportato: {toolId}", 400)

        diadema = item.get("diadema") or {}
        tool_data = diadema.get(toolId) or {}
        job_id = tool_data.get("job_id")

        # Forza il job a CANCELLED (5) via update diretto, bypass validazione Girder
        if job_id:
            import datetime

            from bson import ObjectId

            try:
                Job().update(
                    {"_id": ObjectId(job_id)},
                    {"$set": {"status": 5, "updated": datetime.datetime.utcnow()}},
                    multi=False,
                )
            except Exception as exc:
                logger.warning(
                    "resetJob: force-cancel job %s non-fatal: %s", job_id, exc
                )

        # Aggiorna item.diadema
        Item().update(
            {"_id": item["_id"]},
            {"$set": {f"diadema.{toolId}.status": "cancelled"}},
            multi=False,
        )
        return {"reset": True, "tool": toolId, "job_id": job_id}

    @access.user(scope=TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description("Cancella un job DIADEMA in corso")
        .modelParam("id", model=Item, level=AccessType.WRITE, destName="item")
        .param("toolId", "Tool: mriqc | freesurfer | lstai", paramType="path")
        .errorResponse("Tool non supportato", 400)
        .errorResponse("Nessun job attivo", 400)
        .errorResponse("Job non trovato", 404)
    )
    def cancelJob(self, item, toolId, params):
        if toolId not in _TOOL_CONFIG:
            raise RestException(f"Tool non supportato: {toolId}", 400)

        diadema = item.get("diadema") or {}
        tool_data = diadema.get(toolId) or {}
        status = tool_data.get("status")
        job_id = tool_data.get("job_id")

        if status not in ("running", "queued", "processing", "uploading"):
            raise RestException(
                f"Nessun job attivo per '{toolId}' (stato: {status})", 400
            )
        if not job_id:
            raise RestException(f"job_id non trovato per '{toolId}'", 400)

        from bson import ObjectId

        job = Job().load(ObjectId(job_id), force=True)
        if not job:
            raise RestException(f"Job {job_id} non trovato", 404)

        # Forza lo stato CANCELING (824) direttamente su MongoDB,
        # bypassando la validazione delle transizioni di stato di Girder
        # (che non ammette tutte le transizioni verso 824 da stati intermedi)
        Job().update(
            {"_id": job["_id"]},
            {"$set": {"status": 824}},
            multi=False,
        )

        # Aggiorna subito item.diadema per feedback immediato in UI
        Item().update(
            {"_id": item["_id"]},
            {"$set": {f"diadema.{toolId}.status": "cancelling"}},
            multi=False,
        )
        return {"cancelled": True, "job_id": job_id, "tool": toolId}

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
        import datetime

        job_types = [cfg["job_type"] for cfg in _TOOL_CONFIG.values()]
        # Stadi "attivi" + CANCELING (824)
        stuck_statuses = [JobStatus.QUEUED, JobStatus.RUNNING, 824]
        stuck = list(
            Job().find(
                {
                    "type": {"$in": job_types},
                    "status": {"$in": stuck_statuses},
                },
                limit=limit,
            )
        )
        if not dryRun:
            for job in stuck:
                # Usa update diretto MongoDB per evitare errori di transizione di stato
                Job().update(
                    {"_id": job["_id"]},
                    {
                        "$set": {
                            "status": JobStatus.ERROR,
                            "updated": datetime.datetime.utcnow(),
                        }
                    },
                    multi=False,
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

    # ── Session (BIDS ses-XX / sub-XX) endpoints ──────────────────────────────

    @access.user(scope=TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description("Avvia un tool DIADEMA su una sessione BIDS (cartella ses-XX o sub-XX)")
        .modelParam(
            "folderId",
            model=Folder,
            level=AccessType.WRITE,
            destName="folder",
            paramType="path",
            description="ID cartella sessione BIDS (ses-XX o sub-XX)",
        )
        .param("toolId", "Tool da eseguire: mriqc | freesurfer | lstai", paramType="path")
        .param(
            "participantLabel",
            "BIDS participant label (es. 003). Vuoto = rilevazione automatica",
            required=False,
            default="",
        )
        .param(
            "modality",
            "Filtro modalità MRIQC (T1w, T2w, bold, dwi). Vuoto = tutte",
            required=False,
            default="",
        )
        .param("timeout", "Timeout in secondi", required=False, dataType="integer", default=1800)
        .param("outputBaseDir", "Directory output persistente MRIQC", required=False, default="")
        .param("keepWorkDir", "Conserva work dir MRIQC", required=False, dataType="boolean", default=False)
        .param("directive", "Direttiva recon-all", required=False, default="-all")
        .param("hemi", "Emisfero: both | lh | rh", required=False, default="both")
        .param("openmpThreads", "Thread OpenMP", required=False, dataType="integer", default=4)
        .param("mprage", "Protocollo MGH MP-RAGE", required=False, dataType="boolean", default=False)
        .param("wsatlas", "Skull stripping con atlas", required=False, dataType="boolean", default=False)
        .param("deface", "Defacing del volume", required=False, dataType="boolean", default=False)
        .param("noIsrunning", "Salta check already running", required=False, dataType="boolean", default=True)
        .param("extraFlags", "Flag extra per recon-all", required=False, default="")
        .param("subjectsDir", "Directory SUBJECTS_DIR FreeSurfer", required=False, default="")
        .param("keepSubjectsDir", "Conserva cartella soggetto", required=False, dataType="boolean", default=True)
        .param("fsTimeout", "Timeout FreeSurfer in secondi", required=False, dataType="integer", default=14400)
        .param("threshold", "Soglia lesioni LST-AI (0.0-1.0)", required=False, dataType="float", default=0.5)
        .param("useGpu", "Usa GPU (LST-AI)", required=False, dataType="boolean", default=True)
        .param(
            "derivativesRootId",
            "ID folder radice dataset BIDS per derivatives",
            required=False,
            default="",
        )
        .param("force", "Forza riesecuzione", required=False, dataType="boolean", default=False)
        # Override file espliciti (opzionali — se vuoti usa auto-detect dalla sessione)
        .param("t1wFileId", "ID file T1w (override auto-detect, FreeSurfer/LST-AI)", required=False, default="")
        .param("t2wFileId", "ID file T2w (override auto-detect, FreeSurfer)", required=False, default="")
        .param("flairFileId", "ID file FLAIR (override auto-detect, LST-AI)", required=False, default="")
        .param("selectedFileIds", "ID file selezionati (CSV, override auto-detect, MRIQC)", required=False, default="")
        .errorResponse("Tool non supportato", 400)
        .errorResponse("Job già in corso per questa sessione/tool", 409)
        .errorResponse("Cartella non trovata", 404)
    )
    def runSessionTool(
        self,
        folder,
        toolId,
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
        threshold,
        useGpu,
        derivativesRootId,
        force,
        t1wFileId,
        t2wFileId,
        flairFileId,
        selectedFileIds,
        params,
    ):
        if toolId not in _TOOL_CONFIG:
            raise RestException(
                f"Tool non supportato: '{toolId}'. Valori ammessi: {list(_TOOL_CONFIG)}", 400
            )

        if not force:
            current_status = (folder.get("diadema") or {}).get(toolId, {}).get("status")
            if current_status in ("running", "queued", "processing"):
                raise RestException(
                    f"Un job '{toolId}' è già in corso su questa sessione "
                    f"(stato: {current_status}). Usa force=true per forzare.",
                    409,
                )

        from .settings import PluginSettings

        _settings_mriqc_dir = Setting().get(PluginSettings.MRIQC_OUTPUT_DIR) or None
        _settings_subjects_dir = Setting().get(PluginSettings.SUBJECTS_DIR) or None
        _settings_lstai_dir = Setting().get(PluginSettings.LSTAI_OUTPUT_DIR) or None

        cfg = _TOOL_CONFIG[toolId]

        if toolId == "mriqc":
            from .tasks import run_mriqc_task as celery_task

            # selectedFileIds: CSV di file ID → override auto-detect (es. "id1,id2")
            selected_ids = [f.strip() for f in (selectedFileIds or "").split(",") if f.strip()]
            task_kwargs = dict(
                session_folder_id=str(folder["_id"]),
                participant_label=participantLabel,
                modality_filter=modality or "",
                selected_file_ids=selected_ids or None,
                timeout=timeout,
                output_base_dir=outputBaseDir or _settings_mriqc_dir or None,
                keep_work_dir=keepWorkDir,
                derivatives_root_id=derivativesRootId or None,
            )
        elif toolId == "freesurfer":
            from .tasks import run_freesurfer_task as celery_task

            task_kwargs = dict(
                session_folder_id=str(folder["_id"]),
                participant_label=participantLabel,
                override_t1w_file_id=t1wFileId or None,
                override_t2w_file_id=t2wFileId or None,
                directive=directive,
                hemi=hemi,
                openmp_threads=openmpThreads,
                mprage=mprage,
                wsatlas=wsatlas,
                deface=deface,
                no_isrunning=noIsrunning,
                extra_flags=extraFlags,
                subjects_dir=subjectsDir or _settings_subjects_dir or None,
                keep_subjects_dir=keepSubjectsDir,
                timeout=fsTimeout,
                derivatives_root_id=derivativesRootId or None,
            )
        else:  # lstai
            from .tasks import run_lstai_task as celery_task

            if not (0.0 <= threshold <= 1.0):
                raise RestException(
                    f"threshold deve essere in [0.0, 1.0], ricevuto: {threshold}", 400
                )
            task_kwargs = dict(
                session_folder_id=str(folder["_id"]),
                participant_label=participantLabel,
                override_t1w_file_id=t1wFileId or None,
                override_flair_file_id=flairFileId or None,
                threshold=threshold,
                use_gpu=useGpu,
                output_base_dir=_settings_lstai_dir or None,
            )

        current_user = self.getCurrentUser()
        folder_id = str(folder["_id"])
        job = Job().createJob(
            title=f"{cfg['title_prefix']} – {folder['name']} (sessione)",
            type=cfg["job_type"],
            user=current_user,
            public=False,
            otherFields={
                "sessionFolderId": folder_id,
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

        Folder().update(
            {"_id": folder["_id"]},
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
            "session_folder_id": folder_id,
            "tool": toolId,
            "status": "queued",
        }

    @access.user(scope=TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description("Aggiorna i dati di elaborazione DIADEMA per un tool a livello sessione (usato dai worker)")
        .param("folderId", "ID cartella sessione", paramType="path")
        .param("toolId", "Tool: mriqc | freesurfer | lstai", paramType="path")
        .jsonParam("data", "Campi da aggiornare", requireObject=True, paramType="body")
    )
    def updateSessionProcessing(self, folderId, toolId, data, params):
        if toolId not in _TOOL_CONFIG:
            raise RestException(f"Tool non supportato: {toolId}", 400)
        from bson import ObjectId

        try:
            oid = ObjectId(folderId)
        except Exception:
            raise RestException(f"folderId non valido: {folderId}", 400)
        Folder().update(
            {"_id": oid},
            {"$set": {f"diadema.{toolId}.{k}": v for k, v in data.items()}},
            multi=False,
        )
        return {"updated": True, "tool": toolId, "fields": list(data.keys())}

    @access.public(scope=TokenScope.DATA_READ)
    @autoDescribeRoute(
        Description("Restituisce tutti i risultati DIADEMA per una sessione BIDS").modelParam(
            "folderId", model=Folder, level=AccessType.READ, destName="folder", paramType="path"
        )
    )
    def getSessionResults(self, folder, params):
        return {
            "folder_id": str(folder["_id"]),
            "folder_name": folder.get("name", ""),
            "diadema": folder.get("diadema") or {},
        }

    @access.user(scope=TokenScope.DATA_READ)
    @autoDescribeRoute(
        Description("Participant label BIDS per una cartella sessione").modelParam(
            "folderId", model=Folder, level=AccessType.READ, destName="folder", paramType="path"
        ).param("hint", "Valore esplicito (opzionale)", required=False, default="")
    )
    def resolveSessionParticipantLabel(self, folder, hint, params):
        from girder_client import GirderClient

        from .tasks._helpers import bids_resolve_participant_label_from_folder, bids_resolve_session_label

        token = getCurrentToken()
        gc = GirderClient(apiUrl=cherrypy.request.base + "/api/v1")
        gc.token = str(token["_id"])

        folder_id = str(folder["_id"])
        label = bids_resolve_participant_label_from_folder(gc, folder_id, hint or None)
        session = bids_resolve_session_label(gc, folder_id)

        return {
            "label": label,
            "subject_id": f"sub-{label}",
            "session_label": session,
            "session_id": f"ses-{session}" if session else None,
        }

    @access.user(scope=TokenScope.DATA_READ)
    @autoDescribeRoute(
        Description(
            "Elenca i file NIfTI nella sessione BIDS con modalità rilevata. "
            "Usato dal frontend per mostrare la preview file e permettere l'override."
        ).modelParam(
            "folderId", model=Folder, level=AccessType.READ, destName="folder", paramType="path"
        )
    )
    def getSessionFiles(self, folder, params):
        import cherrypy
        from girder_client import GirderClient

        from .tasks._helpers import (
            bids_detect_modality,
            bids_list_session_files,
            bids_resolve_participant_label_from_folder,
            bids_resolve_session_label,
        )

        token = getCurrentToken()
        gc = GirderClient(apiUrl=cherrypy.request.base + "/api/v1")
        gc.token = str(token["_id"])

        folder_id = str(folder["_id"])
        items = bids_list_session_files(gc, folder_id)

        files = []
        for item in items:
            name = item.get("name", "")
            modality, datatype = bids_detect_modality(name)
            item_files = gc.get(f"item/{item['_id']}/files", parameters={"limit": 1})
            file_id = str(item_files[0]["_id"]) if item_files else None
            files.append({
                "item_id": str(item["_id"]),
                "name": name,
                "modality": modality,
                "datatype": datatype,
                "file_id": file_id,
            })

        participant_label = bids_resolve_participant_label_from_folder(gc, folder_id)
        session_label = bids_resolve_session_label(gc, folder_id)

        return {
            "folder_id": folder_id,
            "participant_label": participant_label,
            "session_label": session_label,
            "files": files,
        }

    @access.user(scope=TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description("Cancella un job DIADEMA in corso su una sessione BIDS").modelParam(
            "folderId", model=Folder, level=AccessType.WRITE, destName="folder", paramType="path"
        ).param("toolId", "Tool: mriqc | freesurfer | lstai", paramType="path")
    )
    def cancelSessionJob(self, folder, toolId, params):
        if toolId not in _TOOL_CONFIG:
            raise RestException(f"Tool non supportato: {toolId}", 400)

        diadema = folder.get("diadema") or {}
        tool_data = diadema.get(toolId) or {}
        status = tool_data.get("status")
        job_id = tool_data.get("job_id")

        if status not in ("running", "queued", "processing", "uploading"):
            raise RestException(f"Nessun job attivo per '{toolId}' (stato: {status})", 400)
        if not job_id:
            raise RestException(f"job_id non trovato per '{toolId}'", 400)

        from bson import ObjectId

        job = Job().load(ObjectId(job_id), force=True)
        if not job:
            raise RestException(f"Job {job_id} non trovato", 404)

        Job().update({"_id": job["_id"]}, {"$set": {"status": 824}}, multi=False)
        Folder().update(
            {"_id": folder["_id"]},
            {"$set": {f"diadema.{toolId}.status": "cancelling"}},
            multi=False,
        )
        return {"cancelled": True, "job_id": job_id, "tool": toolId}

    @access.user(scope=TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description("Resetta un tool DIADEMA bloccato su una sessione BIDS").modelParam(
            "folderId", model=Folder, level=AccessType.WRITE, destName="folder", paramType="path"
        ).param("toolId", "Tool: mriqc | freesurfer | lstai", paramType="path")
    )
    def resetSessionJob(self, folder, toolId, params):
        if toolId not in _TOOL_CONFIG:
            raise RestException(f"Tool non supportato: {toolId}", 400)

        diadema = folder.get("diadema") or {}
        tool_data = diadema.get(toolId) or {}
        job_id = tool_data.get("job_id")

        if job_id:
            import datetime

            from bson import ObjectId

            try:
                Job().update(
                    {"_id": ObjectId(job_id)},
                    {"$set": {"status": 5, "updated": datetime.datetime.utcnow()}},
                    multi=False,
                )
            except Exception as exc:
                logger.warning("resetSessionJob: force-cancel job %s non-fatal: %s", job_id, exc)

        Folder().update(
            {"_id": folder["_id"]},
            {"$set": {f"diadema.{toolId}.status": "cancelled"}},
            multi=False,
        )
        return {"reset": True, "tool": toolId, "job_id": job_id}

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
