# DIADEMA – Girder Plugins for Neuroimaging Data Management

This repository contains a collection of plugins and processing workers for
[Girder 5](https://girder.readthedocs.io/), an open-source platform for the
management and analysis of scientific data. They form the software contribution
of *"A Collaborative Framework for Neuroimaging Data Management Using Girder"*.

## Plugins

| Plugin | Directory | Version | Description |
|--------|-----------|---------|-------------|
| 🧠 **NIfTI Viewer** | `nifti_viewer/` | **1.0.0** | Interactive 2D viewer for NIfTI files with BIDS-aware browsing, automatic metadata extraction and advanced metadata search. |
| 🔐 **OAuth2** | `oauth2/` | **1.0.0** | OAuth2 authentication supporting multiple identity providers (Google, GitHub, Microsoft, Keycloak, Globus, CILogon, LinkedIn, Box, Bitbucket). |
| ⚙️ **DIADEMA Pipeline** | `diadema_pipeline/` | **0.1.0** | Orchestrates the neuroimaging processing pipeline (MRIQC, FreeSurfer, LST-AI) through Celery workers, with REST endpoints and a launch/monitoring UI. |

Each plugin follows [Semantic Versioning](https://semver.org/); see the
`CHANGELOG.md` inside each plugin directory.

## Processing workers

The DIADEMA Pipeline plugin dispatches long-running jobs to containerized
Celery workers. The task implementations live in
`diadema_pipeline/girder_diadema_pipeline/tasks/`; each worker is a Docker image
that loads them via entry points.

| Worker | Directory | Celery queue | Base image |
|--------|-----------|--------------|------------|
| MRIQC | `diadema-mriqc-worker/` | `diadema_mriqc` | `nipreps/mriqc` (pinned digest) |
| FreeSurfer | `freesurfer-worker/` | `freesurfer` | `freesurfer/freesurfer:8.1.0` |
| LST-AI | `lst-worker/` | `lstai` | `jqmcginnis/lst-ai:v1.2.0` |

All workers pin the same Girder commit as the server image for reproducibility.

## Requirements

- Girder 5.0+
- Python 3.9+
- Docker and Docker Compose (for the containerized deployments)

## Quick start (development)

The root `docker-compose.yml` brings up Girder, MongoDB, Redis, RabbitMQ and the
three workers for local development:

```bash
cp .env.example .env        # adjust credentials
docker compose up --build
```

Girder is then available at <http://localhost:8080>. The server is served as an
ASGI app via `uvicorn girder.asgi:app`, following the
[Girder 5 deployment guide](https://girder.readthedocs.io/en/latest/deployment.html).

## Deployment

Two compose stacks are provided under `deploy/`:

- **`deploy/testing/`** – production-like stack (Girder + infrastructure +
  MRIQC/FreeSurfer workers). The LST-AI worker is omitted here to keep the
  testing stack light; use the full stack to include it.
- **`deploy/full/`** – complete stack fronted by an **nginx** reverse proxy that
  terminates TLS, raises timeouts and disables buffering for large NIfTI
  transfers, as recommended by the Girder deployment guide.

For each stack:

```bash
cd deploy/full          # or deploy/testing
cp .env.example .env     # set admin credentials, RabbitMQ password, etc.
cp /path/to/freesurfer_license.txt ./freesurfer_license.txt
docker compose up -d --build
```

Secrets (`.env`, FreeSurfer license) are git-ignored and must be provided per
environment. An idempotent bootstrap step creates the admin user, the
filesystem assetstore and core settings on first start.

## Repository layout

```
.
├── oauth2/                  # OAuth2 plugin
├── nifti_viewer/            # NIfTI viewer plugin
├── diadema_pipeline/        # Pipeline orchestration plugin (+ worker tasks)
├── diadema-mriqc-worker/    # MRIQC worker image
├── freesurfer-worker/       # FreeSurfer worker image
├── lst-worker/              # LST-AI worker image
├── deploy/                  # testing and full deployment stacks
├── Dockerfile               # Girder 5 server image (ASGI / uvicorn)
└── docker-compose.yml       # development stack
```

## License

Apache License 2.0 — see [LICENSE](LICENSE).
