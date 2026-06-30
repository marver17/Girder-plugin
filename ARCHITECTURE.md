# DIADEMA – Architettura del sistema

Questo documento descrive come i componenti dello stack DIADEMA interagiscono tra loro, dal boot dei container fino all'esecuzione di un job di analisi.

---

## 1. Panoramica dei componenti

```
╔══════════════════════════════════════════════════════════════════════╗
║                         HOST (docker network)                        ║
║                                                                      ║
║  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────────┐ ║
║  │   MongoDB    │   │    Redis     │   │        RabbitMQ          │ ║
║  │              │   │              │   │                          │ ║
║  │  Persistenza │   │ Notifiche    │   │  Message broker Celery   │ ║
║  │  dati Girder │   │ real-time    │   │  (code dei job)          │ ║
║  └──────┬───────┘   └──────┬───────┘   └────────────┬─────────────┘ ║
║         │                  │                        │               ║
║         └──────────────────┼────────────────────────┘               ║
║                            │                                        ║
║  ┌─────────────────────────▼──────────────────────────────────────┐ ║
║  │                    Girder Server                               │ ║
║  │            (diadema-test-girder :8080)                         │ ║
║  └────────────────────────────────────────────────────────────────┘ ║
║         │                  │               │              │         ║
║  ┌──────▼──────┐  ┌─────────▼──┐  ┌────────▼───┐  ┌───────▼────┐   ║
║  │celery-worker│  │diadema-    │  │freesurfer- │  │lstai-      │   ║
║  │             │  │mriqc-worker│  │worker      │  │worker      │   ║
║  │ coda:celery │  │coda:       │  │coda:       │  │coda:       │   ║
║  │             │  │diadema_mriqc│ │freesurfer  │  │lstai       │   ║
║  └─────────────┘  └────────────┘  └────────────┘  └────────────┘   ║
╚══════════════════════════════════════════════════════════════════════╝
```

---

## 2. Infrastruttura di supporto

### MongoDB
Il database principale dove Girder salva tutto: utenti, cartelle, file (metadati), job, impostazioni dei plugin, risultati delle analisi. I file binari (immagini NIfTI, output) **non** sono nel database ma nell'assetstore.

### Redis
Usato esclusivamente da Girder per le **notifiche real-time** verso il browser. Quando un job cambia stato (in esecuzione, completato, errore), Girder pubblica l'evento su Redis e il browser lo riceve via Server-Sent Events senza dover fare polling.

### RabbitMQ
Il **bus dei messaggi** tra Girder e i worker Celery. Girder non esegue mai direttamente l'elaborazione pesante: scrive un messaggio su una coda RabbitMQ e torna subito. Il worker legge il messaggio e inizia il lavoro. Questo disaccoppia completamente il server HTTP dall'elaborazione.

Ogni tipo di analisi ha la **propria coda dedicata**, così i worker specializzati ricevono solo i job di competenza:

```
  RabbitMQ
  ├── coda: celery          → celery-worker        (job generici)
  ├── coda: diadema_mriqc   → diadema-mriqc-worker (DIADEMA MRIQC)
  ├── coda: freesurfer      → freesurfer-worker    (FreeSurfer)
  └── coda: lstai           → lstai-worker         (LST-AI)
```

---

## 3. Sequenza di avvio

All'avvio dello stack, i container si avviano in ordine garantito dalle dipendenze:

```
  [1] MongoDB, Redis, RabbitMQ
        │  (healthcheck: pronti ad accettare connessioni)
        ▼
  [2] init-permissions
        │  (garantisce che il volume dell'assetstore sia
        │   scrivibile dall'utente girder prima che il server parta)
        ▼
  [3] Girder Server
        │  ┌─ installa i plugin (oauth2, nifti_viewer, diadema_pipeline)
        │  ├─ esegue bootstrap_girder.py
        │  │     ├── crea assetstore se non esiste
        │  │     ├── applica impostazioni (brand, policy registrazione, ...)
        │  │     └── crea utente admin se non esiste
        │  └─ avvia uvicorn girder.asgi:app (ASGI)
        │  (healthcheck: risponde su /api/v1/system/version)
        ▼
  [4] Tutti i worker
        │  (aspettano che Girder sia healthy prima di connettersi)
        └─ si connettono a RabbitMQ e restano in ascolto
```

---

## 4. Il ruolo di Girder Server

Girder è il cuore del sistema. Si occupa di:

```
  Browser / Client
       │
       │  HTTP / REST API (:8080)
       ▼
  ┌──────────────────────────────────────────────┐
  │               Girder Server                  │
  │                                              │
  │  ┌────────────┐    ┌─────────────────────┐   │
  │  │    Auth    │    │    File Storage     │   │
  │  │            │    │                     │   │
  │  │ - login    │    │ - upload file NIfTI │   │
  │  │ - token    │    │ - download file     │   │
  │  │ - permessi │    │ - assetstore su     │   │
  │  └────────────┘    │   filesystem        │   │
  │                    └─────────────────────┘   │
  │  ┌──────────────────────────────────────┐    │
  │  │           Job tracking               │    │
  │  │                                      │    │
  │  │ - crea job con stato QUEUED          │    │
  │  │ - pubblica task su RabbitMQ          │    │
  │  │ - aggiorna stato (RUNNING/SUCCESS/   │    │
  │  │   ERROR) quando il worker risponde   │    │
  │  └──────────────────────────────────────┘    │
  │  ┌──────────────────────────────────────┐    │
  │  │              Plugin                  │    │
  │  │                                      │    │
  │  │ - aggiungono route REST              │    │
  │  │ - definiscono i task Celery          │    │
  │  │ - estendono l'interfaccia web        │    │
  │  └──────────────────────────────────────┘    │
  └──────────────────────────────────────────────┘
```

### L'assetstore
I file binari (immagini NIfTI, PDF di report, output delle analisi) non vengono salvati in MongoDB ma in una directory del filesystem chiamata **assetstore**. In MongoDB rimangono solo i metadati (nome, dimensione, checksum, percorso). Questo permette a Girder di gestire file anche molto grandi senza appesantire il database.

```
  Upload di un file NIfTI
  ┌──────────┐           ┌──────────────┐         ┌────────────────┐
  │  Client  │──────────►│    Girder    │────────►│   Assetstore   │
  │          │  HTTP PUT │              │  scrivi  │  (filesystem   │
  │          │           │  - valida    │  binario │   /data/       │
  │          │           │  - genera ID │         │   assetstore/) │
  │          │           │  - salva     │         └────────────────┘
  │          │◄──────────│    metadati  │
  │          │  file ID  │  su MongoDB  │────────►┌────────────────┐
  └──────────┘           └──────────────┘  salva  │    MongoDB     │
                                           metad. │  { _id, name,  │
                                                  │    size, path }│
                                                  └────────────────┘
```

---

## 5. Plugin: come estendono Girder

I plugin sono **pacchetti Python** installati nello stesso processo di Girder. Alla partenza Girder li carica automaticamente e ciascuno può:

- aggiungere **endpoint REST** propri (es. `/api/v1/diadema/launch`)
- definire **task Celery** che verranno eseguiti dai worker
- aggiungere **widget** all'interfaccia web

```
  Plugin installati nel container girder:

  girder_oauth2
  └── aggiunge login via provider OAuth2 esterno

  girder_nifti_viewer
  └── aggiunge widget UI per la visualizzazione 3D di file NIfTI

  girder_diadema_pipeline
  ├── aggiunge endpoint REST per lanciare le pipeline
  ├── definisce il task "diadema_mriqc" → coda diadema_mriqc
  └── definisce il task "freesurfer"    → coda freesurfer
```

---

## 6. I worker Celery

Ogni worker è un processo Python che rimane **in ascolto passiva** su RabbitMQ. Non espone porte HTTP. Non ha accesso diretto a MongoDB.

```
  Worker (stato idle)

  ┌─────────────────────────────────────┐
  │          celery-worker              │
  │                                     │
  │   Plugin installati:                │
  │   (stessi del Girder Server,        │
  │    necessari per importare          │
  │    le funzioni dei task)            │
  │                                     │
  │   ┌─────────────────────────────┐   │
  │   │   Celery process            │   │
  │   │   in ascolto su:            │   │
  │   │   amqp://rabbitmq:5672      │   │
  │   │   coda: celery              │   │
  │   │                             │   │
  │   │   [nessun messaggio] → wait │   │
  │   └─────────────────────────────┘   │
  └─────────────────────────────────────┘
```

### Perché i plugin devono essere installati anche nei worker?

I task Celery sono **funzioni Python** definite dentro i plugin. Quando il worker riceve un messaggio dalla coda, deve poter **importare** quella funzione per eseguirla. Se il plugin non fosse installato nel worker, l'importazione fallirebbe.

---

## 7. Ciclo di vita di un job

Sequenza completa dalla richiesta dell'utente al completamento:

```
  FASE 1 – Richiesta
  ════════════════════════════════════════════════════
  Browser
    │
    │  POST /api/v1/diadema/launch
    │  { fileId: "abc123", analysis: "mriqc" }
    │  Authorization: Bearer <token>
    ▼
  Girder Server
    │  - verifica token e permessi
    │  - crea Job su MongoDB  → stato: QUEUED
    │  - genera token temporaneo per il worker
    │  - pubblica messaggio su RabbitMQ (coda: diadema_mriqc)
    │    { job_id, file_id, girder_token, girder_api_url }
    ▼
  Risposta al browser: { job_id, status: "queued" }


  FASE 2 – Esecuzione
  ════════════════════════════════════════════════════
  diadema-mriqc-worker
    │  (riceve il messaggio da RabbitMQ)
    │
    ├─ notifica Girder: stato → RUNNING
    │     Girder aggiorna MongoDB
    │     Girder invia evento a Redis → browser riceve notifica
    │
    ├─ GET /api/v1/file/{file_id}/download
    │     scarica il file NIfTI dall'assetstore tramite REST
    │
    ├─ esegue MRIQC localmente nel container
    │     (tool neuroimaging installato nell'immagine Docker)
    │
    └─ carica i risultati su Girder
          POST /api/v1/item  (crea item risultato)
          PUT  /api/v1/file  (carica report HTML/JSON)


  FASE 3 – Completamento
  ════════════════════════════════════════════════════
  diadema-mriqc-worker
    │
    └─ notifica Girder: stato → SUCCESS (o ERROR)
          Girder aggiorna MongoDB
          Girder invia evento a Redis → browser riceve notifica finale


  STATO FINALE
  ════════════════════════════════════════════════════
  Browser
    │  (ha ricevuto notifica via Server-Sent Events)
    └─ GET /api/v1/job/{job_id}
         ritorna { status: "success", output_item_id: "xyz" }
```

### Diagramma degli stati del job

```
  QUEUED ──────► RUNNING ──────► SUCCESS
                    │
                    └──────────► ERROR
```

---

## 8. Come i worker comunicano con Girder

I worker **non hanno accesso diretto a MongoDB**. Tutta la comunicazione avviene tramite le REST API di Girder, usando un **token temporaneo** generato da Girder nel momento in cui crea il job.

```
  Worker                              Girder (HTTP)
    │                                      │
    ├── GET  /api/v1/file/{id}/download ──►│
    │◄─ stream del file binario ───────────┤
    │                                      │
    ├── POST /api/v1/item              ───►│
    │◄─ { item_id }                ────────┤
    │                                      │
    ├── PUT  /api/v1/file?parentId=...  ──►│
    │   (upload risultato)                 │
    │◄─ { file_id }                ────────┤
    │                                      │
    └── PUT  /api/v1/job/{id}          ───►│
        { status: "success" }             │
                                           │
                                    aggiorna MongoDB
                                    notifica Redis → browser
```

Questo design ha vantaggi importanti:
- il worker **non ha credenziali di database** → sicurezza
- il token temporaneo ha **permessi limitati** al job specifico
- il worker può girare su una **macchina diversa** da Girder (scale-out)

---

## 9. Worker specializzati vs. worker generico

```
  ┌────────────────┬──────────────┬──────────────────────────────────┐
  │    Container   │    Coda      │  Cosa esegue                     │
  ├────────────────┼──────────────┼──────────────────────────────────┤
  │ celery-worker  │ celery       │ Job generici di Girder Worker    │
  │                │              │ (es. conversioni, operazioni su  │
  │                │              │  file non specializzate)         │
  ├────────────────┼──────────────┼──────────────────────────────────┤
  │diadema-mriqc   │ diadema_mriqc│ MRIQC pipeline DIADEMA           │
  │   -worker      │              │ (versione custom della pipeline) │
  ├────────────────┼──────────────┼──────────────────────────────────┤
  │freesurfer      │ freesurfer   │ Analisi corticale FreeSurfer     │
  │  -worker       │              │ (FreeSurfer completo installato  │
  │                │              │  nell'immagine, richiede licenza)│
  └────────────────┴──────────────┴──────────────────────────────────┘
```

I worker specializzati (mriqc, freesurfer) usano **immagini Docker dedicate** perché i tool neuroimaging che contengono (nipreps/mriqc, FreeSurfer) sono software pesanti (decine di GB) che non devono stare nell'immagine base di Girder.

---

## 10. I volumi Docker

```
  ┌──────────────────────────────────────────────────────────────────┐
  │                        Volumi persistenti                        │
  │                                                                  │
  │  mongodb_data          → database MongoDB                        │
  │  rabbitmq_data         → code e messaggi RabbitMQ               │
  │  girder_data           → cache pip, dati locali utente girder    │
  │  girder_assetstore     → file binari caricati dagli utenti       │
  │  diadema_mriqc_data    → output MRIQC generati dal worker        │
  │  diadema_subjects_data → soggetti FreeSurfer (può essere >100GB) │
  └──────────────────────────────────────────────────────────────────┘

  Nota: girder_assetstore è condiviso solo dal container girder.
  I worker accedono ai file SEMPRE tramite le API di Girder,
  mai montando direttamente il volume dell'assetstore.
```

---

## 11. Porte esposte sull'host

Solo due porte sono visibili dall'esterno del Docker network:

```
  HOST
  ├── :8080  →  Girder HTTP (UI + API REST)
  └── :15672 →  RabbitMQ Management UI (diagnostica)

  Tutto il resto (MongoDB :27017, Redis :6379, code interne)
  è accessibile SOLO tra i container sulla rete diadema-test-network.
```
