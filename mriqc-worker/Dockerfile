FROM nipreps/mriqc:latest

# Install git (needed to clone girder repos)
RUN apt-get update && apt-get install -qy git && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Clone Girder v4-integration branch (same as the main Girder container)
# Provides: girder-client, girder-worker, girder-plugin-worker
RUN git clone --branch v4-integration --single-branch \
    https://github.com/girder/girder.git /opt/girder

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

CMD ["sh", "-c", \
     "pip install --no-cache-dir -e /opt/nifti_qc && \
      celery -A girder_worker.app worker \
        --queues=mriqc \
        --loglevel=info \
        --pool=solo \
        --concurrency=1"]
