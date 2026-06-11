# Pinned: digest dell'immagine MRIQC v25.1.0.dev45 attualmente deployata
# ("latest" non è riproducibile e può rompere la compatibilità al rebuild)
FROM nipreps/mriqc@sha256:e4b8800c8fb716dc81ae6c7cf2009b4da09eec8ae3caba8aa2083ed4fa94d100

# Install git
RUN apt-get update && apt-get install -qy git && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Pinned al commit girder usato da server e worker (v5.0.10-4-g203cd86a4)
ARG GIRDER_REF=203cd86a409e0b3a88d619508b7372210ced7a60
RUN git clone https://github.com/girder/girder.git /opt/girder && \
    git -C /opt/girder checkout ${GIRDER_REF}

# Build tools (--upgrade: setuptools di sistema può essere <61 e non leggere
# i metadati PEP 621, producendo un pacchetto "UNKNOWN")
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
     "--queues=diadema_mriqc", \
     "--loglevel=info", \
     "--pool=solo", \
     "--concurrency=1", \
     "--heartbeat-interval=0", \
     "--include=girder_diadema_pipeline.tasks"]
