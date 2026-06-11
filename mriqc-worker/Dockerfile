# Pinned: digest of the currently deployed MRIQC image (v25.1.0.dev45)
# ("latest" is not reproducible and may break compatibility on rebuild)
FROM nipreps/mriqc@sha256:e4b8800c8fb716dc81ae6c7cf2009b4da09eec8ae3caba8aa2083ed4fa94d100

# Install git (needed to clone girder repos)
RUN apt-get update && apt-get install -qy git && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Clone Girder pinned to the same commit used by the server and other workers
# Provides: girder-client, girder-worker, girder-plugin-worker
ARG GIRDER_REF=203cd86a409e0b3a88d619508b7372210ced7a60
RUN git clone https://github.com/girder/girder.git /opt/girder && \
    git -C /opt/girder checkout ${GIRDER_REF}

# Build tools needed for editable installs
RUN pip install --no-cache-dir setuptools setuptools_scm wheel

# Install only the packages needed by the Celery worker (no web server)
RUN pip install --no-cache-dir -e /opt/girder/clients/python
RUN pip install --no-cache-dir -e /opt/girder/worker
RUN pip install --no-cache-dir -e /opt/girder/plugins/worker

# nifti_qc plugin is mounted as a volume at /opt/nifti_qc (see docker-compose.yml)
# and installed in editable mode at container startup.
# This allows live-editing tasks.py without rebuilding the image.

WORKDIR /opt

# Override the base image entrypoint (nipreps/mriqc sets ENTRYPOINT ["mriqc"])
# Without this, CMD args would be passed to mriqc instead of running as a shell command.
ENTRYPOINT []

CMD ["sh", "-c", \
     "pip install --no-cache-dir --no-build-isolation --no-deps -e /opt/nifti_qc && \
      celery -A girder_worker.app worker \
        --queues=mriqc \
        --loglevel=info \
        --pool=solo \
        --concurrency=1 \
        --heartbeat-interval=0 \
        --include=girder_nifti_qc.tasks"]
