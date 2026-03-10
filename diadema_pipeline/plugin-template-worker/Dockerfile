# ──────────────────────────────────────────────────────────────────────────────
# Worker Dockerfile per Plugin Template
# ──────────────────────────────────────────────────────────────────────────────
# COME ADATTARE:
#   1. Sostituisci l'immagine base con quella del tuo tool.
#      Es: python:3.11-slim  se il tool è un pacchetto Python puro
#          nipreps/mriqc:latest  se usi MRIQC
#          freesurfer/freesurfer:7.4  se usi FreeSurfer
#   2. Aggiungi i comandi RUN per installare il tuo tool se non è nell'immagine
#   3. Aggiorna --queues e --include con il nome del tuo plugin
#   4. Se il task dura < 60 s, puoi usare --pool=prefork al posto di --pool=solo
# ──────────────────────────────────────────────────────────────────────────────

# SOSTITUISCI con l'immagine base che contiene il tuo tool
FROM python:3.11-slim

# ── Dipendenze di sistema ─────────────────────────────────────────────────────
RUN apt-get update && apt-get install -qy git && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# ── Girder (stesso branch del container principale) ───────────────────────────
RUN git clone --branch v4-integration --single-branch \
    https://github.com/girder/girder.git /opt/girder

RUN pip install --no-cache-dir setuptools setuptools_scm wheel

# Installa solo i pacchetti necessari al worker Celery (senza il web server)
RUN pip install --no-cache-dir -e /opt/girder/clients/python
RUN pip install --no-cache-dir -e /opt/girder/worker
RUN pip install --no-cache-dir -e /opt/girder/plugins/worker

# ── Il plugin viene montato come volume (docker-compose.yml) ──────────────────
# e installato in modalità editable all'avvio del container.
# Questo consente di modificare tasks.py senza ricostruire l'immagine.
# In produzione: copia il plugin nell'immagine con COPY e installa qui.

WORKDIR /opt

# ── Override entrypoint ───────────────────────────────────────────────────────
# Necessario se l'immagine base imposta un ENTRYPOINT (es. nipreps/mriqc).
# Senza questo, CMD verrebbe passato come argomento al tool invece di essere
# eseguito come shell command.
ENTRYPOINT []

# ── Avvio worker ──────────────────────────────────────────────────────────────
CMD ["sh", "-c", \
     "pip install --no-cache-dir --no-build-isolation --no-deps -e /opt/plugin_template && \
      celery -A girder_worker.app worker \
        --queues=plugin_template \
        --loglevel=info \
        --pool=solo \
        --concurrency=1 \
        --heartbeat-interval=0 \
        --include=girder_plugin_template.tasks"]
# ↑ IMPORTANTE: --include è il fallback robusto per la registrazione del task.
#   task_imports() in worker_entry.py è il meccanismo principale (stevedore),
#   ma può non funzionare con alcune versioni di girder_worker.
#   Usa SEMPRE entrambi.
