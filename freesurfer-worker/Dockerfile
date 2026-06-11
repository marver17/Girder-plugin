FROM freesurfer/freesurfer:8.1.0

# ── NOTA sulla licenza FreeSurfer ─────────────────────────────────────────────
# La licenza viene fornita a runtime tramite volume mount nel docker-compose:
#   volumes:
#     - ./license.txt:/usr/local/freesurfer/license.txt:ro
#   environment:
#     - FS_LICENSE=/usr/local/freesurfer/license.txt
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

# Clone Girder pinned allo stesso commit del container principale
ARG GIRDER_REF=203cd86a409e0b3a88d619508b7372210ced7a60
RUN git clone https://github.com/girder/girder.git /opt/girder && \
    git -C /opt/girder checkout ${GIRDER_REF}

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
