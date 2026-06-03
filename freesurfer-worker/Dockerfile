FROM freesurfer/freesurfer:8.1.0

# ── NOTA sulla licenza FreeSurfer ─────────────────────────────────────────────
# FreeSurfer richiede un file di licenza valido.
# Opzione A (runtime): monta il file e imposta FS_LICENSE nel docker-compose.yml
#   volumes:
#     - ./freesurfer_license.txt:/opt/freesurfer/license.txt
#   environment:
#     - FS_LICENSE=/opt/freesurfer/license.txt
#
# Opzione B (build-time): licenza inclusa nell'immagine
COPY license.txt /usr/local/freesurfer/license.txt
# ──────────────────────────────────────────────────────────────────────────────

# Dipendenze sistema: git (CentOS 7 → yum)
# Python 3.6 di CentOS 7 è troppo vecchio per Girder (richiede ≥3.10).
# Installiamo Miniconda per avere Python 3.10 senza toccare il sistema.
RUN yum install -y git bzip2 && \
    yum clean all && rm -rf /var/cache/yum

# Miniforge (conda-forge, nessun TOS Anaconda) per avere Python 3.10
RUN curl -fsSL https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh \
      -o /tmp/miniforge.sh && \
    bash /tmp/miniforge.sh -b -p /opt/conda && \
    rm /tmp/miniforge.sh

ENV PATH="/opt/conda/bin:$PATH"

RUN conda install -y python=3.10 pip && conda clean -afy

# Clone Girder v4-integration (stesso branch del container principale)
RUN git clone  --single-branch \
    https://github.com/girder/girder.git /opt/girder

# Build tools
RUN pip install --no-cache-dir setuptools setuptools_scm wheel

# Stack girder_worker (senza server web)
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
        --queues=freesurfer \
        --loglevel=info \
        --pool=solo \
        --concurrency=1 \
        --heartbeat-interval=0 \
        --include=girder_diadema_pipeline.tasks"]
