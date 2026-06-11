# DIADEMA LST-AI worker — Celery worker sulla coda "lstai"
# Base: jqmcginnis/lst-ai:v1.2.0 (Ubuntu 22.04, Python 3.10, torch cu121, CLI `lst`)
FROM jqmcginnis/lst-ai:v1.2.0

# Il task diadema invoca `lst_ai`; l'immagine espone la CLI come `lst`
RUN ln -s /usr/local/bin/lst /usr/local/bin/lst_ai

# Clone Girder pinned allo stesso commit degli altri worker (v5.0.10-4-g203cd86a4)
ARG GIRDER_REF=203cd86a409e0b3a88d619508b7372210ced7a60
RUN git clone https://github.com/girder/girder.git /opt/girder && \
    git -C /opt/girder checkout ${GIRDER_REF}

# Build tools (--upgrade obbligatorio: il setuptools 59.x di sistema di Ubuntu
# 22.04 non legge i metadati PEP 621 e installerebbe il plugin come "UNKNOWN")
RUN pip install --upgrade --no-cache-dir setuptools setuptools_scm wheel

# Stack girder_worker (senza web server)
RUN pip install --no-cache-dir -e /opt/girder/clients/python
RUN pip install --no-cache-dir -e /opt/girder/worker
RUN pip install --no-cache-dir -e /opt/girder/plugins/worker

# Plugin diadema_pipeline baked nell'immagine (install non-editable).
# Per il live-edit in dev, i compose dev/testing montano il sorgente su
# /opt/diadema_pipeline e sovrascrivono `command:` con una pip install -e.
COPY diadema_pipeline /opt/diadema_pipeline
RUN rm -rf /opt/diadema_pipeline/build /opt/diadema_pipeline/*.egg-info && \
    pip install --no-cache-dir --no-build-isolation --no-deps /opt/diadema_pipeline

WORKDIR /opt

ENTRYPOINT []

CMD ["celery", "-A", "girder_worker.app", "worker", \
     "--queues=lstai", \
     "--loglevel=info", \
     "--pool=solo", \
     "--concurrency=1", \
     "--heartbeat-interval=0", \
     "--include=girder_diadema_pipeline.tasks"]
