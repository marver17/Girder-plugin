# girder-diadema-pipeline

Plugin Girder v5 per l'orchestrazione di tool di analisi neuroimaging:

- **MRIQC** – quality control di immagini MRI strutturali/funzionali
- **FreeSurfer recon-all** – segmentazione corticale e subcorticale
- **LST-AI** – segmentazione delle lesioni della sostanza bianca

Ogni tool gira in un container Docker separato come worker Celery. Il pannello UI si inietta in Girder nella view di ogni item NIfTI.

---

## Architettura

```
Girder (HTTP API)
  └── DiademaResource  (REST endpoints)
        ├── POST /:id/run/:toolId             → invia task alla coda Celery
        ├── POST /:id/cancel/:toolId          → cancella job in corso
        ├── POST /:id/reset/:toolId           → force-reset job bloccato
        ├── POST /job/:jobId/force_cancelled  → forza status=CANCELLED via MongoDB
        ├── PUT  /:id/processing/:toolId      → aggiorna metadati elaborazione
        ├── GET  /:id/results                 → restituisce risultati salvati
        ├── GET  /:id/derivatives_root        → radice cartella BIDS derivatives
        ├── GET  /:id/participant_label       → rileva automaticamente participant label
        ├── DELETE /:id/results/:toolId       → elimina risultati
        ├── POST /cleanup_stuck_jobs          → pulisce job bloccati
        ├── GET  /settings                    → legge settings del plugin
        └── PUT  /settings                    → aggiorna settings del plugin

Workers Celery (code separate)
  ├── diadema_mriqc  → tasks/mriqc.py       (run_mriqc_task)
  ├── freesurfer     → tasks/freesurfer.py  (run_freesurfer_task, upload_freesurfer_results)
  └── lstai          → tasks/lstai.py       (run_lstai_task)
```

I worker comunicano con Girder tramite `girder-client`. I risultati vengono salvati nel campo `item.diadema` e i file caricati nella struttura BIDS.

---

## Requisiti

- Python ≥ 3.10
- Girder ≥ 5.0.0a1
- girder-worker ≥ 5.0.0a1
- girder-plugin-worker ≥ 5.0.0a1
- girder-client ≥ 5.0.0a1
- nibabel ≥ 5.2.0
- numpy ≥ 1.24.0
- Node.js ≥ 18 (solo per build frontend)
- RabbitMQ (message broker Celery)
- MongoDB (usato da Girder)

---

## Installazione

### 1. Build del frontend

```bash
cd girder_diadema_pipeline/web_client
npm install
npm run build
```

I file compilati vengono messi in `web_client/dist/` e inclusi nel package Python grazie alla sezione `[tool.setuptools.package-data]` in `pyproject.toml`.

### 2. Installazione del plugin Python

```bash
pip install girder-diadema-pipeline
# oppure in sviluppo:
pip install -e /path/to/diadema_pipeline
```

### 3. Attivazione in Girder

Riavviare Girder — il plugin viene caricato automaticamente tramite l'entry point:

```
[project.entry-points."girder.plugin"]
diadema_pipeline = "girder_diadema_pipeline:DiademaPlugin"
```

Il file JS compilato viene servito da Girder su:
`/static/built/plugins/diadema_pipeline/diadema-pipeline.umd.cjs`

---

## Docker Compose

Il file `docker-compose.snippet.yml` contiene i blocchi da aggiungere al `docker-compose.yml` principale.

Variabili d'ambiente necessarie nei worker:

| Variabile | Descrizione |
|-----------|-------------|
| `GIRDER_API_URL` | URL dell'API Girder raggiungibile dal worker |
| `GIRDER_WORKER_CALLBACK_URL` | URL per i callback (può differire se su rete interna) |
| `FREESURFER_HOME` | (solo freesurfer-worker) path installazione FreeSurfer |
| `SUBJECTS_DIR` | (solo freesurfer-worker) directory output soggetti |
| `LSTAI_MODEL_DIR` | (solo lstai-worker) directory modelli LST-AI |
| `C_FORCE_ROOT` | `1` per permettere al worker di girare come root nel container |

---

## Struttura dati: `item.diadema`

Ogni item NIfTI elaborato accumula metadati nel campo `diadema`:

```json
{
  "diadema": {
    "mriqc": {
      "status": "success",
      "jobId": "...",
      "startTime": "2024-01-01T00:00:00",
      "endTime": "2024-01-01T00:05:00",
      "folderId": "...",
      "participantLabel": "001"
    },
    "freesurfer": {
      "status": "running",
      "jobId": "...",
      "startTime": "2024-01-01T00:00:00",
      "participantLabel": "001"
    },
    "lstai": {
      "status": "error",
      "jobId": "...",
      "error": "..."
    }
  }
}
```

Valori possibili di `status`: `inactive`, `queued`, `running`, `success`, `error`, `cancelled`, `cancelling`.

---

## REST API

### `POST /api/v1/diadema_pipeline/:itemId/run/:toolId`

Avvia un'elaborazione. Richiede accesso WRITE sull'item.
`toolId` ∈ `{mriqc, freesurfer, lstai}`

**Risposta:** oggetto Job Girder.

---

### `POST /api/v1/diadema_pipeline/:itemId/cancel/:toolId`

Cancella il job in corso. Usa aggiornamento diretto MongoDB per evitare problemi di validazione delle transizioni di stato Girder.

---

### `POST /api/v1/diadema_pipeline/:itemId/reset/:toolId`

Force-reset di un job bloccato in stato `cancelling (824)`. Imposta il job a `cancelled` e pulisce i metadati dell'item.

---

### `POST /api/v1/diadema_pipeline/job/:jobId/force_cancelled`

Forza lo stato di un job a `CANCELLED (5)` tramite aggiornamento diretto MongoDB.

---

### `GET /api/v1/diadema_pipeline/:itemId/participant_label`

Rileva automaticamente il participant label BIDS per l'item.

**Query params:** `hint` (opzionale, suggerimento manuale)

**Risposta:**
```json
{ "label": "001", "source": "filename" }
```

Strategie di risoluzione (ordine di priorità):
1. `hint` esplicito (sorgente: `manual`)
2. Pattern `sub-XXX` nel nome del file (sorgente: `filename`)
3. Pattern `sub-XXX` nella gerarchia di cartelle, fino a 8 livelli (sorgente: `folder`)
4. Stem del filename senza estensioni (sorgente: `stem`)
5. `"001"` come fallback (sorgente: `fallback`)

---

### `POST /api/v1/diadema_pipeline/cleanup_stuck_jobs`

Pulisce job in stati `QUEUED (1)`, `RUNNING (2)` o `CANCELING (824)` oltre una soglia temporale. Richiede privilegi di admin. Usa aggiornamento diretto MongoDB.

---

## Parametri per tool

### MRIQC

| Parametro | Tipo | Default | Descrizione |
|-----------|------|---------|-------------|
| `participantLabel` | string | auto-detected | Etichetta soggetto BIDS (`sub-XXX` senza prefisso) |
| `nThreads` | int | `4` | Numero di thread |
| `memGb` | float | `8.0` | Memoria in GB |
| `noSub` | bool | `true` | Disabilita invio dati a MRIQC server |

### FreeSurfer

| Parametro | Tipo | Default | Descrizione |
|-----------|------|---------|-------------|
| `participantLabel` | string | auto-detected | Etichetta soggetto BIDS |
| `extraFlags` | string | `""` | Flag aggiuntivi per `recon-all` |
| `resumeIfExists` | bool | `false` | Riprende run incompleto |

### LST-AI

| Parametro | Tipo | Default | Descrizione |
|-----------|------|---------|-------------|
| `participantLabel` | string | auto-detected | Etichetta soggetto BIDS |
| `device` | string | `"cpu"` | Device PyTorch (`cpu`, `cuda`) |

---

## Struttura BIDS derivatives

I risultati vengono caricati nella struttura:

```
<derivatives_root>/
  <toolId>/
    sub-<participantLabel>/
      <file output>
```

La radice derivatives viene determinata risalendo la gerarchia delle cartelle finché non si trova un item `dataset_description.json`, poi cercando la sotto-cartella `derivatives`. Se non trovata, viene creata nella cartella padre dell'item.

---

## Frontend

Il pannello UI viene iniettato automaticamente nella view di ogni item NIfTI (`.nii`, `.nii.gz`).

### Funzionalità

- **Run** – avvia il tool selezionato con i parametri del form
- **Cancel** – cancella il job in corso (visibile in stati `queued`/`running`)
- **Force Reset** – ripristina un job bloccato in `cancelling` (pulsante arancione)
- **Participant label preview** – banner verde che mostra il label rilevato automaticamente con la sorgente, aggiornato in tempo reale
- **Pre-fill** – il campo `Participant Label` viene pre-compilato con il valore rilevato all'apertura del form
- **Risultati** – link ai risultati dopo l'elaborazione

### Filtro item NIfTI

Il pannello è visibile solo su item NIfTI. Verifica a tre livelli:
1. Il nome file termina per `.nii` o `.nii.gz`
2. Il documento item contiene il campo `diadema`
3. Verifica asincrona tramite `GET /item/:id/files`

---

## Note implementative

### Idempotenza (acks_late)

Con `acks_late=True` e `reject_on_worker_lost=True`, la funzione `idempotency_guard()` in `_helpers.py` verifica lo stato del job prima di iniziare per evitare esecuzioni doppie su re-delivery.

### Cancellazione cooperativa

Il task controlla periodicamente lo stato del job. Se trova stato `824` (CANCELING):
1. Termina il processo in corso
2. Chiama `set_job_cancelled()` → `PUT /job/:id?status=5`
3. Se fallisce, chiama `POST /diadema_pipeline/job/:id/force_cancelled` (MongoDB diretto)
4. Solleva `Ignore` per evitare che Celery segni il task come errore

> **Importante:** `from celery.exceptions import Ignore` deve essere importato **solo a livello di modulo**. Un import all'interno della funzione causa `UnboundLocalError` perché Python tratta `Ignore` come variabile locale in tutta la funzione.

### Transizioni di stato Girder

| Codice | Nome | Note |
|--------|------|------|
| 0 | INACTIVE | Job creato ma non in coda |
| 1 | QUEUED | In attesa nel broker |
| 2 | RUNNING | In esecuzione |
| 3 | SUCCESS | Completato |
| 4 | ERROR | Errore |
| 5 | CANCELLED | Cancellato |
| 824 | CANCELING | Le transizioni `RUNNING→CANCELING` e `CANCELING→CANCELLED` richiedono `Job().update()` diretto su MongoDB |

---

## Sviluppo

```bash
# Installazione in modalità sviluppo
cd /workspace/diadema_pipeline
pip install -e .

# Build frontend (dopo modifiche a web_client/)
cd girder_diadema_pipeline/web_client
npm install && npm run build

# Avvio stack completo
cd /workspace
bash start-dev.sh
```

### Aggiungere un nuovo tool

1. Creare `tasks/<tool>.py` con il task Celery
2. Aggiungere la configurazione in `_TOOL_CONFIG` in `rest.py`
3. Creare `web_client/views/tools/<tool>.js` con i parametri del form
4. Registrare la vista in `web_client/views/DiademaPanel.js`
5. Aggiornare `worker_entry.py`
6. Creare il `Dockerfile` in `<tool>-worker/`
7. Aggiungere il servizio in `docker-compose.snippet.yml`

---

## Licenza

Apache-2.0 — vedi [LICENSE](../LICENSE)
