######### Dockerfile for Girder 5 #########
# Builds a Girder 5 server image with the DIADEMA plugins
# (oauth2, nifti_viewer, diadema_pipeline) pre-installed.
#
# Girder is served as an ASGI app via uvicorn, as recommended by the
# Girder 5 deployment guide:
#   https://girder.readthedocs.io/en/latest/deployment.html

FROM ubuntu:22.04

LABEL maintainer="Mario Verdicchio <marioverd95@gmail.com>"

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=en_US.UTF-8 \
    LC_ALL=C.UTF-8

# Pinned Girder commit for reproducible builds (matches the worker images).
ENV GIRDER_COMMIT=203cd86a409e0b3a88d619508b7372210ced7a60

RUN apt-get update && apt-get install -qy \
    gcc \
    libpython3-dev \
    python3-venv \
    git \
    libldap2-dev \
    libsasl2-dev \
    python3-pip \
    curl \
    locales \
    ca-certificates \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN groupadd -g 1000 girder && \
    useradd -m -u 1000 -g girder -s /bin/bash girder

# tini for correct signal handling / zombie reaping (PID 1)
RUN curl -LJ https://github.com/krallin/tini/releases/download/v0.19.0/tini -o /sbin/tini && \
    chmod +x /sbin/tini

# Node.js (for building plugin web clients)
RUN curl -sL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -qy nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Isolated virtualenv instead of --break-system-packages (PEP 668)
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip setuptools wheel "uvicorn[standard]"

RUN mkdir /girder && \
    mkdir -p /home/girder/.local/share/girder /workspace && \
    chown -R girder:girder /girder /home/girder /workspace /opt/venv

# Girder (pinned commit)
RUN git config --global --add safe.directory /girder && \
    git clone https://github.com/girder/girder.git /girder && \
    cd /girder && git checkout "$GIRDER_COMMIT"
RUN cd /girder/girder/web && npm i && npm run build
RUN pip install --no-cache-dir /girder

# ── Plugin: oauth2 ───────────────────────────────────────────────────────────
COPY ./oauth2 /plugins/oauth2
RUN pip install --no-cache-dir /plugins/oauth2

# ── Plugin: nifti_viewer (with frontend build) ───────────────────────────────
COPY ./nifti_viewer /plugins/nifti_viewer
RUN cd /plugins/nifti_viewer/girder_nifti_viewer/web_client && \
    npm install && npm run build
RUN pip install --no-cache-dir /plugins/nifti_viewer

# ── Plugin: diadema_pipeline (with frontend build) ───────────────────────────
COPY ./diadema_pipeline /plugins/diadema_pipeline
RUN cd /plugins/diadema_pipeline/girder_diadema_pipeline/web_client && \
    npm install && npm run build
RUN pip install --no-cache-dir /plugins/diadema_pipeline

# Trim npm cache to reduce image size
RUN npm cache clean --force

# I plugin sopra sono installati come root: le rispettive dist-info nel venv
# risultano root-owned. A runtime l'entrypoint reinstalla i plugin da /workspace
# come utente `girder` (live-edit) e non potrebbe sovrascriverle. Riallinea la
# proprietà del venv (e dei sorgenti baked) a `girder` DOPO le installazioni.
RUN chown -R girder:girder /opt/venv /plugins

EXPOSE 8080

USER girder

# tini as PID 1; default command serves Girder's ASGI app via uvicorn.
# (deploy/* compose files override `command` to run the entrypoint script,
#  which bootstraps Girder and then execs uvicorn.)
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["uvicorn", "girder.asgi:app", "--host", "0.0.0.0", "--port", "8080"]
