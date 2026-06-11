# DIADEMA LST-AI worker — Celery worker sulla coda "lstai"
# Base: jqmcginnis/lst-ai:v1.2.0 (Ubuntu 22.04, Python 3.10, torch cu121, CLI `lst`)
FROM jqmcginnis/lst-ai:v1.2.0

# Il task diadema invoca `lst_ai`; l'immagine espone la CLI come `lst`
RUN ln -s /usr/local/bin/lst /usr/local/bin/lst_ai

# Clone Girder pinned allo stesso commit degli altri worker (v5.0.10-4-g203cd86a4)
ARG GIRDER_REF=203cd86a409e0b3a88d619508b7372210ced7a60
RUN git clone https://github.com/girder/girder.git /opt/girder && \
    git -C /opt/girder checkout ${GIRDER_REF}

# Build tools
RUN pip install --no-cache-dir setuptools setuptools_scm wheel

# Stack girder_worker (senza web server)
RUN pip install --no-cache-dir -e /opt/girder/clients/python
RUN pip install --no-cache-dir -e /opt/girder/worker
RUN pip install --no-cache-dir -e /opt/girder/plugins/worker

# diadema_pipeline è montato come volume a /opt/diadema_pipeline
# e installato in editable mode all'avvio (live-edit di tasks.py senza rebuild)

WORKDIR /opt

ENTRYPOINT []

CMD ["sh", "-c", \
     "pip install --no-cache-dir --no-build-isolation --no-deps -e /opt/diadema_pipeline && \
      celery -A girder_worker.app worker \
        --queues=lstai \
        --loglevel=info \
        --pool=solo \
        --concurrency=1 \
        --heartbeat-interval=0 \
        --include=girder_diadema_pipeline.tasks"]
