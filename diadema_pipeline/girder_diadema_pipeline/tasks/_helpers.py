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
import re
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
    Propaga l'eccezione in caso di fallimento: il task va in ERROR invece
    di tornare SUCCESS con dati mancanti.
    """
    try:
        gc.put(f"diadema_pipeline/{item_id}/processing/{tool_id}", json=data)
    except Exception as exc:
        logger.error(
            "[diadema] update_diadema_tool FAILED item=%s tool=%s: %s",
            item_id,
            tool_id,
            exc,
        )
        raise


def set_job_cancelled(gc, job_id, task_name):
    """Imposta lo stato del job a CANCELLED (5) usando gc (token utente con scope jobs.*)."""
    try:
        gc.put(f"job/{job_id}", parameters={"status": 5})
        logger.info("[%s] Job %s → CANCELLED", task_name, job_id)
    except Exception as exc:
        # La transizione CANCELING(824) → CANCELLED(5) non è accettata dalla normale API Girder.
        # Usiamo il nostro endpoint che bypassa la validazione via aggiornamento diretto MongoDB.
        logger.warning(
            "[%s] set CANCELLED normale fallito (%s), provo force_cancelled...",
            task_name,
            exc,
        )
        try:
            # Ricava il base URL dal gc già configurato
            base = gc.urlBase.rstrip("/")  # es. http://girder:8080/api/v1
            gc.post(f"diadema_pipeline/job/{job_id}/force_cancelled")
            logger.info("[%s] Job %s → CANCELLED (force)", task_name, job_id)
        except Exception as exc2:
            logger.warning("[%s] force_cancelled fallito: %s", task_name, exc2)


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


# ── Helper BIDS derivatives ───────────────────────────────────────────────────


def bids_get_or_create_folder(gc, parent_id, parent_type, name):
    """Restituisce l'ID di una Girder folder con `name` sotto `parent`, creandola se assente."""
    existing = gc.get(
        "folder",
        parameters={
            "parentType": parent_type,
            "parentId": parent_id,
            "name": name,
            "limit": 1,
        },
    )
    if existing:
        return str(existing[0]["_id"])
    new_folder = gc.post(
        "folder",
        parameters={"parentType": parent_type, "parentId": parent_id, "name": name},
    )
    return str(new_folder["_id"])


def bids_find_dataset_root(gc, item_id):
    """
    Stima la radice del dataset BIDS risalendo la gerarchia di folder a partire dall'item.

    Strategia:
     - Ad ogni livello cerca un item chiamato 'dataset_description.json' nella folder corrente.
     - Se lo trova, quella folder è la radice del dataset.
     - Se raggiunge il livello collection senza trovarlo, ritorna (collection_id, 'collection').

    Returns:
        (root_id: str, root_type: str)  dove root_type è 'folder' o 'collection'
    """
    try:
        item_doc = gc.get(f"item/{item_id}")
        folder_id = item_doc.get("folderId")
        if not folder_id:
            return (str(item_doc.get("collectionId", item_doc["_id"])), "collection")

        current_id = str(folder_id)
        current_type = "folder"

        # Risali al massimo 10 livelli per evitare loop infiniti
        for _ in range(10):
            # Controlla se c'è dataset_description.json in questa folder
            desc_items = gc.get(
                "item",
                parameters={
                    "folderId": current_id,
                    "name": "dataset_description.json",
                    "limit": 1,
                },
            )
            if desc_items:
                logger.info("[bids] Dataset root trovato: folder %s", current_id)
                return (current_id, "folder")

            # Risali al parent
            folder_doc = gc.get(f"folder/{current_id}")
            parent_type = folder_doc.get("parentCollection", "folder")
            parent_id = str(folder_doc.get("parentId", ""))

            if not parent_id:
                break

            if parent_type == "collection":
                logger.info("[bids] Dataset root: collection %s (fallback)", parent_id)
                return (parent_id, "collection")

            current_id = parent_id
            current_type = "folder"

        # Fallback: usa la folder padre diretta dell'item
        logger.warning("[bids] Dataset root non trovato, uso folder padre dell'item")
        return (str(folder_id), "folder")

    except Exception as exc:
        logger.warning("[bids] bids_find_dataset_root fallito: %s", exc)
        return (None, None)


def bids_resolve_participant_label(gc, item_id, hint=None):
    """
    Determina il BIDS participant label per un item Girder.

    Strategia (in ordine):
      1. ``hint`` esplicito (se non vuoto) – rimuove eventuale prefisso "sub-"
      2. Pattern ``sub-XXX`` nel nome del file/item
      3. Cartelle padre in gerarchia (risale fino a 8 livelli, cerca ``sub-XXX``)
      4. Fallback: stem del filename sanitizzato (solo [a-zA-Z0-9]), max 32 char

    Returns:
        str: participant label (senza prefisso ``sub-``)
    """
    hint = (hint or "").strip()
    if hint:
        # Rimuovi prefisso "sub-" se l'utente lo ha incluso per comodità
        if hint.lower().startswith("sub-"):
            hint = hint[4:]
        safe = re.sub(r"[^a-zA-Z0-9]", "", hint)
        return safe or "001"

    try:
        item_doc = gc.get(f"item/{item_id}")
        item_name = item_doc.get("name", "")

        # 1. Cerca sub-XXX nel nome file (es. sub-003_T1w.nii.gz)
        m = re.search(r"(?:^|[_\-.])sub[-_]([a-zA-Z0-9]+)", item_name, re.IGNORECASE)
        if m:
            logger.debug("[bids] participant_label da filename: %s", m.group(1))
            return m.group(1)

        # 2. Risali la gerarchia folder cercando sub-XXX
        folder_id = str(item_doc.get("folderId", ""))
        for _ in range(8):
            if not folder_id:
                break
            folder_doc = gc.get(f"folder/{folder_id}")
            folder_name = folder_doc.get("name", "")
            m = re.match(r"^sub[-_]([a-zA-Z0-9]+)$", folder_name, re.IGNORECASE)
            if m:
                logger.debug(
                    "[bids] participant_label da folder '%s': %s",
                    folder_name,
                    m.group(1),
                )
                return m.group(1)
            parent_type = folder_doc.get("parentCollection", "folder")
            if parent_type != "folder":
                break
            folder_id = str(folder_doc.get("parentId", ""))

        # 3. Fallback: stem del filename
        stem = item_name
        for ext in (".nii.gz", ".nii", ".json", ".tsv", ".csv", ".dcm"):
            if stem.lower().endswith(ext):
                stem = stem[: -len(ext)]
                break
        safe = re.sub(r"[^a-zA-Z0-9]", "", stem)
        if safe:
            logger.debug("[bids] participant_label da stem filename: %s", safe[:32])
            return safe[:32]

    except Exception as exc:
        logger.warning("[bids] bids_resolve_participant_label fallito: %s", exc)

    return "001"


# ── Helper BIDS sessione ──────────────────────────────────────────────────────

_BIDS_MODALITY_DATATYPE = {
    "t1w": "anat",
    "t2w": "anat",
    "flair": "anat",
    "pdw": "anat",
    "t2star": "anat",
    "bold": "func",
    "dwi": "dwi",
    "asl": "perf",
}


def get_nifti_file_from_item(gc, item_id):
    """
    Restituisce il file NIfTI (.nii.gz o .nii) dentro un item Girder.
    Un item BIDS tipicamente contiene sia il NIfTI che il JSON sidecar:
    questa funzione trova specificamente il file NIfTI evitando di restituire il JSON.
    Ritorna il dict del file, o None se non trovato.
    """
    try:
        files = gc.get(f"item/{item_id}/files", parameters={"limit": 20})
        for f in files:
            fname = f.get("name", "").lower()
            if fname.endswith(".nii.gz") or fname.endswith(".nii"):
                return f
    except Exception as exc:
        logger.warning("[bids] get_nifti_file_from_item item=%s fallito: %s", item_id, exc)
    return None


def bids_list_session_files(gc, folder_id):
    """
    Elenca gli item NIfTI dentro una cartella sessione BIDS (ricorsivo).
    Rileva item NIfTI sia dal nome dell'item (se include .nii/.nii.gz)
    sia cercando il file NIfTI all'interno dell'item (per item con nome
    senza estensione che contengono NIfTI + JSON sidecar).
    """
    nifti_items = []

    def _collect(fid):
        items = gc.get("item", parameters={"folderId": fid, "limit": 200})
        for item in items:
            name = item.get("name", "")
            # Caso 1: il nome item termina in .nii/.nii.gz
            if name.lower().endswith((".nii.gz", ".nii")):
                nifti_items.append(item)
                continue
            # Caso 2: item senza estensione che contiene NIfTI + JSON
            # (struttura BIDS tipica: item "sub-001_T1w" con file .nii.gz e .json)
            modality, _ = bids_detect_modality(name)
            if modality:
                nifti_file = get_nifti_file_from_item(gc, str(item["_id"]))
                if nifti_file:
                    nifti_items.append(item)

        subfolders = gc.get(
            "folder",
            parameters={"parentType": "folder", "parentId": fid, "limit": 50},
        )
        for sf in subfolders:
            _collect(str(sf["_id"]))

    try:
        _collect(folder_id)
    except Exception as exc:
        logger.warning("[bids] bids_list_session_files fallito: %s", exc)
    return nifti_items


def bids_detect_modality(item_name):
    """
    Rileva la modalità BIDS dal nome del file NIfTI.
    Restituisce (modality, datatype) o (None, None) se non riconosciuto.
    Esempio: 'sub-001_ses-01_T1w.nii.gz' → ('T1w', 'anat')
    """
    stem = item_name
    for ext in (".nii.gz", ".nii"):
        if stem.lower().endswith(ext):
            stem = stem[: -len(ext)]
            break
    # Prende l'ultimo componente dopo '_'
    parts = re.split(r"[_\-]", stem)
    for part in reversed(parts):
        lower = part.lower()
        if lower in _BIDS_MODALITY_DATATYPE:
            return part, _BIDS_MODALITY_DATATYPE[lower]
    return None, None


def bids_find_modality_file(gc, folder_id, modality_suffix):
    """
    Trova il primo item NIfTI in folder_id (ricorsivo) col suffisso BIDS dato.
    Esempio: modality_suffix='T1w' → cerca *_T1w.nii.gz o *_T1w.nii
    Restituisce il dict item Girder, oppure None.
    """
    all_files = bids_list_session_files(gc, folder_id)
    suffix_lower = f"_{modality_suffix.lower()}"
    for item in all_files:
        stem = item.get("name", "")
        for ext in (".nii.gz", ".nii"):
            if stem.lower().endswith(ext):
                stem = stem[: -len(ext)]
                break
        if stem.lower().endswith(suffix_lower):
            return item
    return None


def bids_resolve_session_label(gc, folder_id):
    """
    Rileva il BIDS session label (ses-XX) dalla cartella o dalla gerarchia.
    Restituisce il label senza prefisso 'ses-' (es. '01'), o None.
    """
    try:
        fid = folder_id
        for _ in range(6):
            if not fid:
                break
            doc = gc.get(f"folder/{fid}")
            m = re.match(r"^ses[-_]([a-zA-Z0-9]+)$", doc.get("name", ""), re.IGNORECASE)
            if m:
                return m.group(1)
            if doc.get("parentCollection", "folder") != "folder":
                break
            fid = str(doc.get("parentId", ""))
    except Exception as exc:
        logger.warning("[bids] bids_resolve_session_label fallito: %s", exc)
    return None


def bids_resolve_participant_label_from_folder(gc, folder_id, hint=None):
    """
    Determina il BIDS participant label partendo da una cartella anziché da un item.
    Risale la gerarchia cercando sub-XXX.
    """
    hint = (hint or "").strip()
    if hint:
        if hint.lower().startswith("sub-"):
            hint = hint[4:]
        return re.sub(r"[^a-zA-Z0-9]", "", hint) or "001"
    try:
        fid = folder_id
        for _ in range(10):
            if not fid:
                break
            doc = gc.get(f"folder/{fid}")
            m = re.match(r"^sub[-_]([a-zA-Z0-9]+)$", doc.get("name", ""), re.IGNORECASE)
            if m:
                return m.group(1)
            if doc.get("parentCollection", "folder") != "folder":
                break
            fid = str(doc.get("parentId", ""))
    except Exception as exc:
        logger.warning("[bids] bids_resolve_participant_label_from_folder fallito: %s", exc)
    return "001"


def bids_find_dataset_root_from_folder(gc, folder_id):
    """
    Stima la radice del dataset BIDS risalendo la gerarchia da una cartella (non da un item).
    Stessa logica di bids_find_dataset_root.
    """
    try:
        current_id = folder_id
        for _ in range(10):
            desc_items = gc.get(
                "item",
                parameters={
                    "folderId": current_id,
                    "name": "dataset_description.json",
                    "limit": 1,
                },
            )
            if desc_items:
                logger.info("[bids] Dataset root trovato: folder %s", current_id)
                return (current_id, "folder")
            doc = gc.get(f"folder/{current_id}")
            parent_type = doc.get("parentCollection", "folder")
            parent_id = str(doc.get("parentId", ""))
            if not parent_id:
                break
            if parent_type == "collection":
                logger.info("[bids] Dataset root: collection %s (fallback)", parent_id)
                return (parent_id, "collection")
            current_id = parent_id
    except Exception as exc:
        logger.warning("[bids] bids_find_dataset_root_from_folder fallito: %s", exc)
    return (None, None)


def update_diadema_tool_on_folder(gc, folder_id, tool_id, **data):
    """Aggiorna i dati di elaborazione per un tool a livello di cartella sessione BIDS.
    Propaga l'eccezione in caso di fallimento: il task va in ERROR invece
    di tornare SUCCESS con dati mancanti.
    """
    try:
        gc.put(f"diadema_pipeline/session/{folder_id}/processing/{tool_id}", json=data)
    except Exception as exc:
        logger.error(
            "[diadema] update_diadema_tool_on_folder FAILED folder=%s tool=%s: %s",
            folder_id,
            tool_id,
            exc,
        )
        raise


def bids_upload_derivative(
    gc,
    item_id,
    file_path,
    datatype,
    participant_label,
    derivatives_root_id=None,
    derivatives_root_type=None,
    pipeline_name="mriqc",
    overwrite=True,
):
    """
    Uploada un file nella struttura BIDS derivatives di Girder:
        <dataset_root>/derivatives/<pipeline_name>/sub-<label>/<datatype>/<filename>

    Se derivatives_root_id è None, chiama bids_find_dataset_root per stimarlo.
    Se overwrite=True e l'item esiste già, sovrascrive i file.

    Returns:
        str: Girder item ID dell'item derivato, oppure None in caso di errore.
    """
    from pathlib import Path as _Path

    try:
        fpath = _Path(file_path)

        # Radice dataset
        if not derivatives_root_id:
            derivatives_root_id, derivatives_root_type = bids_find_dataset_root(
                gc, item_id
            )

        if not derivatives_root_id:
            logger.warning(
                "[bids] Impossibile determinare dataset root, skip upload derivato %s",
                fpath.name,
            )
            return None

        root_type = derivatives_root_type or "folder"

        # Costruisce la gerarchia: derivatives / pipeline / sub-xxx / datatype
        deriv_id = bids_get_or_create_folder(
            gc, derivatives_root_id, root_type, "derivatives"
        )
        pipe_id = bids_get_or_create_folder(gc, deriv_id, "folder", pipeline_name)
        sub_id = bids_get_or_create_folder(
            gc, pipe_id, "folder", f"sub-{participant_label}"
        )
        dtype_id = bids_get_or_create_folder(gc, sub_id, "folder", datatype)

        fname = fpath.name

        # Cerca item esistente con lo stesso nome
        existing_items = gc.get(
            "item",
            parameters={"folderId": dtype_id, "name": fname, "limit": 1},
        )

        if existing_items and overwrite:
            target_item_id = str(existing_items[0]["_id"])
            # Cancella i file esistenti sull'item prima di ricaricare
            old_files = gc.get(f"item/{target_item_id}/files", parameters={"limit": 50})
            for of in old_files:
                try:
                    gc.delete(f"file/{of['_id']}")
                except Exception:
                    pass
            logger.info("[bids] Sovrascrittura %s (item %s)", fname, target_item_id)
        elif existing_items:
            target_item_id = str(existing_items[0]["_id"])
            logger.info("[bids] Item esistente, skip (overwrite=False): %s", fname)
            return target_item_id
        else:
            # Crea nuovo item nella folder
            new_item = gc.post(
                "item",
                parameters={"folderId": dtype_id, "name": fname},
            )
            target_item_id = str(new_item["_id"])
            logger.info("[bids] Nuovo item derivato %s", fname)

        gc.uploadFileToItem(target_item_id, str(fpath))
        logger.info("[bids] Upload completato: %s → item %s", fname, target_item_id)
        return target_item_id

    except Exception as exc:
        logger.warning(
            "[bids] bids_upload_derivative fallito per %s: %s", file_path, exc
        )
        return None
