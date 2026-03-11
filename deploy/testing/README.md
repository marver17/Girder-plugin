# DIADEMA – Deploy Testing

Configurazione Docker Compose simil-produzione per la fase di testing.
Avvia tutti i servizi automaticamente con `docker compose up -d`.

A differenza del setup di sviluppo (`start-dev.sh`), qui:

- Girder parte come **processo non interattivo** (nessun bash manuale)
- Il celery worker generico è un **container separato** da Girder
- Tutti i segreti sono in un file **`.env`**
- I container non espongono porte interne all'host (solo Girder su `GIRDER_PORT`)

---

## Struttura

```
deploy/testing/
├── .env.example            ← template variabili d'ambiente
├── .env                    ← (da creare, non committare)
├── docker-compose.yml
├── entrypoint-girder.sh    ← installa plugin + avvia girder/worker
├── freesurfer_license.txt  ← (da ottenere, non committare)
└── README.md
```

---

## Setup iniziale

### 1. Variabili d'ambiente

```bash
cd deploy/testing
cp .env.example .env
# Modifica almeno le password:
#   RABBITMQ_PASS
```

### 2. Licenza FreeSurfer

Scarica la licenza gratuita su <https://surfer.nmr.mgh.harvard.edu/registration.html>
e copiala in questa cartella:

```bash
cp /path/to/license.txt deploy/testing/freesurfer_license.txt
```

Se non hai la licenza e vuoi avviare lo stack senza FreeSurfer:

```bash
docker compose up -d mongodb redis rabbitmq girder celery-worker mriqc-worker diadema-mriqc-worker
```

### 3. Build frontend

```bash
# Dalla root del progetto:
bash build-frontend.sh
```

### 4. Avvio

```bash
cd deploy/testing
docker compose up -d
```

---

## Servizi

| Container                           | Funzione                   | Coda Celery     |
| ----------------------------------- | -------------------------- | --------------- |
| `diadema-test-mongodb`              | Database Girder            | –               |
| `diadema-test-redis`                | Notifiche real-time Girder | –               |
| `diadema-test-rabbitmq`             | Message broker Celery      | –               |
| `diadema-test-girder`               | Girder HTTP server         | –               |
| `diadema-test-celery-worker`        | Worker Girder generico     | `celery`        |
| `diadema-test-mriqc-worker`         | Worker nifti_qc            | `mriqc`         |
| `diadema-test-diadema-mriqc-worker` | Worker DIADEMA MRIQC       | `diadema_mriqc` |
| `diadema-test-freesurfer-worker`    | Worker FreeSurfer          | `freesurfer`    |

---

## Porte esposte sull'host

| Servizio            | Porta default | Variabile `.env`     |
| ------------------- | ------------- | -------------------- |
| Girder UI / API     | `8080`        | `GIRDER_PORT`        |
| RabbitMQ Management | `15672`       | `RABBITMQ_MGMT_PORT` |

MongoDB e Redis **non** sono esposti sull'host (accesso solo tra container).

---

## Primo avvio: crea l'utente admin

Dopo che Girder è healthy (`docker compose ps`):

```bash
docker compose exec girder \
    girder-cli --api-url http://localhost:8080/api/v1 \
    user create \
    --login admin \
    --email admin@example.com \
    --password changeme \
    --admin
```

---

## Comandi utili

```bash
# Stato di tutti i container
docker compose ps

# Log in tempo reale
docker compose logs -f girder
docker compose logs -f celery-worker
docker compose logs -f diadema-mriqc-worker
docker compose logs -f diadema-freesurfer-worker

# Riavviare solo un servizio
docker compose restart girder

# Rebuild immagine + riavvio (dopo modifiche al Dockerfile)
docker compose up -d --build girder

# Fermare tutto (mantiene i volumi)
docker compose down

# Fermare e distruggere anche i dati
docker compose down -v
```

---

## Note

### Plugin installati automaticamente

All'avvio il container Girder esegue `entrypoint-girder.sh` che installa
in editable mode i plugin da `/workspace/`:

```
oauth2
nifti_viewer
nifti_qc
diadema_pipeline
```

I pacchetti vengono cachati nel volume `diadema-test-girder-data`
(`/home/girder/.local`) per velocizzare i riavvii successivi.

### Codice sorgente montato

Il sorgente del workspace è montato in sola lettura come volume nei container
worker. Questo permette di aggiornare il codice Python dei task senza
rebuilddare le immagini: basta `docker compose restart <worker>`.

### Build immagini worker

Le immagini `diadema-mriqc-worker` e `diadema-freesurfer-worker` sono pesanti
(contengono nipreps/mriqc e FreeSurfer completi). Il primo build richiede
diversi minuti. I build successivi usano la cache Docker.
