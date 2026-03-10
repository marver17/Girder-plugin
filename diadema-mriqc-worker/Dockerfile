FROM nipreps/mriqc:latest

# Install git
RUN apt-get update && apt-get install -qy git && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Clone Girder v4-integration branch
RUN git clone --branch v4-integration --single-branch \
    https://github.com/girder/girder.git /opt/girder

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
        --queues=diadema_mriqc \
        --loglevel=info \
        --pool=solo \
        --concurrency=1 \
        --heartbeat-interval=0 \
        --include=girder_diadema_pipeline.tasks"]
