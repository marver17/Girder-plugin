# DIADEMA – System architecture

This document describes how the components of the DIADEMA stack interact with one another, from container boot up to the execution of an analysis job.

---

## 1. Component overview

```
╔══════════════════════════════════════════════════════════════════════╗
║                         HOST (docker network)                        ║
║                                                                      ║
║  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────────┐  ║
║  │   MongoDB    │   │    Redis     │   │        RabbitMQ          │  ║
║  │              │   │              │   │                          │  ║
║  │  Girder data │   │ Real-time    │   │  Celery message broker   │  ║
║  │  persistence │   │ notifications│   │  (job queues)            │  ║
║  └──────┬───────┘   └──────┬───────┘   └────────────┬─────────────┘  ║
║         │                  │                        │                ║
║         └──────────────────┼────────────────────────┘                ║
║                            │                                         ║
║  ┌─────────────────────────▼──────────────────────────────────────┐  ║
║  │                    Girder Server                               │  ║
║  │            (diadema-test-girder :8080)                         │  ║
║  └────────────────────────────────────────────────────────────────┘  ║
║         │                │               │               │           ║
║  ┌──────▼──────┐  ┌──────▼──────┐  ┌─────▼──────┐  ┌─────▼──────┐    ║
║  │celery-worker│  │diadema-     │  │freesurfer- │  │lstai-      │    ║
║  │             │  │mriqc-worker │  │worker      │  │worker      │    ║
║  │ queue:celery│  │queue:       │  │queue:      │  │queue:      │    ║
║  │             │  │diadema_mriqc│  │freesurfer  │  │lstai       │    ║
║  └─────────────┘  └─────────────┘  └────────────┘  └────────────┘    ║
╚══════════════════════════════════════════════════════════════════════╝
```

---

## 2. Supporting infrastructure

### MongoDB
The main database where Girder stores everything: users, folders, files (metadata), jobs, plugin settings, analysis results. Binary files (NIfTI images, output) are **not** in the database but in the assetstore.

### Redis
Used exclusively by Girder for **real-time notifications** to the browser. When a job changes state (running, completed, error), Girder publishes the event on Redis and the browser receives it via Server-Sent Events without having to poll.

### RabbitMQ
The **message bus** between Girder and the Celery workers. Girder never performs the heavy processing directly: it writes a message to a RabbitMQ queue and returns immediately. The worker reads the message and starts the work. This fully decouples the HTTP server from the processing.

Each type of analysis has its **own dedicated queue**, so the specialized workers only receive the jobs they are responsible for:

```
  RabbitMQ
  ├── queue: celery         → celery-worker        (generic jobs)
  ├── queue: diadema_mriqc  → diadema-mriqc-worker (DIADEMA MRIQC)
  ├── queue: freesurfer     → freesurfer-worker    (FreeSurfer)
  └── queue: lstai          → lstai-worker         (LST-AI)
```

---

## 3. Startup sequence

When the stack starts, the containers come up in an order guaranteed by their dependencies:

```
  [1] MongoDB, Redis, RabbitMQ
        │  (healthcheck: ready to accept connections)
        ▼
  [2] init-permissions
        │  (ensures the assetstore volume is writable by the
        │   girder user before the server starts)
        ▼
  [3] Girder Server
        │  ┌─ installs the plugins (oauth2, nifti_viewer, diadema_pipeline)
        │  ├─ runs bootstrap_girder.py
        │  │     ├── creates the assetstore if it does not exist
        │  │     ├── applies settings (brand, registration policy, ...)
        │  │     └── creates the admin user if it does not exist
        │  └─ starts uvicorn girder.asgi:app (ASGI)
        │  (healthcheck: responds on /api/v1/system/version)
        ▼
  [4] All workers
        │  (wait for Girder to be healthy before connecting)
        └─ connect to RabbitMQ and stay listening
```

---

## 4. The role of the Girder Server

Girder is the heart of the system. It is responsible for:

```
  Browser / Client
       │
       │  HTTP / REST API (:8080)
       ▼
  ┌──────────────────────────────────────────────┐
  │               Girder Server                  │
  │                                              │
  │  ┌────────────┐    ┌─────────────────────┐   │
  │  │    Auth    │    │    File Storage     │   │
  │  │            │    │                     │   │
  │  │ - login    │    │ - upload NIfTI file │   │
  │  │ - token    │    │ - download file     │   │
  │  │ - perms    │    │ - assetstore on     │   │
  │  └────────────┘    │   filesystem        │   │
  │                    └─────────────────────┘   │
  │  ┌──────────────────────────────────────┐    │
  │  │           Job tracking               │    │
  │  │                                      │    │
  │  │ - creates job with state QUEUED      │    │
  │  │ - publishes task on RabbitMQ         │    │
  │  │ - updates state (RUNNING/SUCCESS/    │    │
  │  │   ERROR) when the worker responds    │    │
  │  └──────────────────────────────────────┘    │
  │  ┌──────────────────────────────────────┐    │
  │  │              Plugins                 │    │
  │  │                                      │    │
  │  │ - add their own REST routes          │    │
  │  │ - define the Celery tasks            │    │
  │  │ - extend the web interface           │    │
  │  └──────────────────────────────────────┘    │
  └──────────────────────────────────────────────┘
```

### The assetstore
Binary files (NIfTI images, report PDFs, analysis output) are not stored in MongoDB but in a filesystem directory called the **assetstore**. Only the metadata (name, size, checksum, path) remain in MongoDB. This lets Girder handle even very large files without burdening the database.

```
  Upload of a NIfTI file
  ┌──────────┐           ┌──────────────┐         ┌────────────────┐
  │  Client  │──────────►│    Girder    │────────►│   Assetstore   │
  │          │  HTTP PUT │              │  write  │  (filesystem   │
  │          │           │  - validate  │  binary │   /data/       │
  │          │           │  - generate  │         │   assetstore/) │
  │          │           │    an ID     │         └────────────────┘
  │          │◄──────────│  - save      │
  │          │  file ID  │    metadata  │────────►┌────────────────┐
  └──────────┘           │  on MongoDB  │  save   │    MongoDB     │
                         └──────────────┘  metad. │  { _id, name,  │
                                                  │    size, path }│
                                                  └────────────────┘
```

---

## 5. Plugins: how they extend Girder

The plugins are **Python packages** installed in the same process as Girder. At startup Girder loads them automatically and each one can:

- add its own **REST endpoints** (e.g. `/api/v1/diadema/launch`)
- define **Celery tasks** that will be executed by the workers
- add **widgets** to the web interface

```
  Plugins installed in the girder container:

  girder_oauth2
  └── adds login via an external OAuth2 provider

  girder_nifti_viewer
  └── adds a UI widget for 3D visualization of NIfTI files

  girder_diadema_pipeline
  ├── adds REST endpoints to launch the pipelines
  ├── defines the "diadema_mriqc" task → diadema_mriqc queue
  └── defines the "freesurfer" task    → freesurfer queue
```

---

## 6. The Celery workers

Each worker is a Python process that stays **passively listening** on RabbitMQ. It exposes no HTTP ports. It has no direct access to MongoDB.

```
  Worker (idle state)

  ┌─────────────────────────────────────┐
  │          celery-worker              │
  │                                     │
  │   Installed plugins:                │
  │   (same as the Girder Server,       │
  │    needed in order to import        │
  │    the task functions)              │
  │                                     │
  │   ┌─────────────────────────────┐   │
  │   │   Celery process            │   │
  │   │   listening on:             │   │
  │   │   amqp://rabbitmq:5672      │   │
  │   │   queue: celery             │   │
  │   │                             │   │
  │   │   [no message] → wait       │   │
  │   └─────────────────────────────┘   │
  └─────────────────────────────────────┘
```

### Why must the plugins be installed in the workers too?

The Celery tasks are **Python functions** defined inside the plugins. When the worker receives a message from the queue, it must be able to **import** that function in order to execute it. If the plugin were not installed in the worker, the import would fail.

---

## 7. Lifecycle of a job

Full sequence from the user's request to completion:

```
  PHASE 1 – Request
  ════════════════════════════════════════════════════
  Browser
    │
    │  POST /api/v1/diadema/launch
    │  { fileId: "abc123", analysis: "mriqc" }
    │  Authorization: Bearer <token>
    ▼
  Girder Server
    │  - verifies token and permissions
    │  - creates a Job on MongoDB  → state: QUEUED
    │  - generates a temporary token for the worker
    │  - publishes a message on RabbitMQ (queue: diadema_mriqc)
    │    { job_id, file_id, girder_token, girder_api_url }
    ▼
  Response to the browser: { job_id, status: "queued" }


  PHASE 2 – Execution
  ════════════════════════════════════════════════════
  diadema-mriqc-worker
    │  (receives the message from RabbitMQ)
    │
    ├─ notifies Girder: state → RUNNING
    │     Girder updates MongoDB
    │     Girder sends an event to Redis → browser receives notification
    │
    ├─ GET /api/v1/file/{file_id}/download
    │     downloads the NIfTI file from the assetstore via REST
    │
    ├─ runs MRIQC locally in the container
    │     (neuroimaging tool installed in the Docker image)
    │
    └─ uploads the results to Girder
          POST /api/v1/item  (creates the result item)
          PUT  /api/v1/file  (uploads HTML/JSON report)


  PHASE 3 – Completion
  ════════════════════════════════════════════════════
  diadema-mriqc-worker
    │
    └─ notifies Girder: state → SUCCESS (or ERROR)
          Girder updates MongoDB
          Girder sends an event to Redis → browser receives final notification


  FINAL STATE
  ════════════════════════════════════════════════════
  Browser
    │  (has received the notification via Server-Sent Events)
    └─ GET /api/v1/job/{job_id}
         returns { status: "success", output_item_id: "xyz" }
```

### Job state diagram

```
  QUEUED ──────► RUNNING ──────► SUCCESS
                    │
                    └──────────► ERROR
```

---

## 8. How the workers communicate with Girder

The workers **have no direct access to MongoDB**. All communication happens through Girder's REST API, using a **temporary token** generated by Girder at the moment it creates the job.

```
  Worker                              Girder (HTTP)
    │                                      │
    ├── GET  /api/v1/file/{id}/download ──►│
    │◄─ binary file stream ────────────────┤
    │                                      │
    ├── POST /api/v1/item              ───►│
    │◄─ { item_id }                ────────┤
    │                                      │
    ├── PUT  /api/v1/file?parentId=...  ──►│
    │   (upload result)                    │
    │◄─ { file_id }                ────────┤
    │                                      │
    └── PUT  /api/v1/job/{id}          ───►│
        { status: "success" }              │
                                           │
                                    updates MongoDB
                                    notifies Redis → browser
```

This design has important advantages:
- the worker **has no database credentials** → security
- the temporary token has **permissions limited** to the specific job
- the worker can run on a **different machine** than Girder (scale-out)

> In the full deployment (`deploy/full`) this worker↔Girder communication
> **no longer travels in clear text**: the workers call `https://nginx/api/v1`,
> verifying the certificate against an internal CA. See
> [section 12 – Communication security (TLS/HTTPS)](#12-communication-security-tlshttps).

---

## 9. Specialized workers vs. generic worker

```
  ┌────────────────┬──────────────┬──────────────────────────────────┐
  │   Container    │    Queue     │  What it runs                    │
  ├────────────────┼──────────────┼──────────────────────────────────┤
  │ celery-worker  │ celery       │ Generic Girder Worker jobs       │
  │                │              │ (e.g. conversions, non-          │
  │                │              │  specialized file operations)    │
  ├────────────────┼──────────────┼──────────────────────────────────┤
  │diadema-mriqc   │ diadema_mriqc│ DIADEMA MRIQC pipeline           │
  │   -worker      │              │ (custom version of the pipeline) │
  ├────────────────┼──────────────┼──────────────────────────────────┤
  │freesurfer      │ freesurfer   │ FreeSurfer cortical analysis     │
  │  -worker       │              │ (full FreeSurfer installed in    │
  │                │              │  the image, requires a license)  │
  └────────────────┴──────────────┴──────────────────────────────────┘
```

The specialized workers (mriqc, freesurfer) use **dedicated Docker images** because the neuroimaging tools they contain (nipreps/mriqc, FreeSurfer) are heavy pieces of software (tens of GB) that should not live in Girder's base image.

---

## 10. The Docker volumes

```
  ┌──────────────────────────────────────────────────────────────────┐
  │                        Persistent volumes                        │
  │                                                                  │
  │  mongodb_data          → MongoDB database                        │
  │  rabbitmq_data         → RabbitMQ queues and messages            │
  │  girder_data           → pip cache, girder user local data       │
  │  girder_assetstore     → binary files uploaded by users          │
  │  diadema_mriqc_data    → MRIQC output produced by the worker     │
  │  diadema_subjects_data → FreeSurfer subjects (can be >100GB)     │
  └──────────────────────────────────────────────────────────────────┘

  Note: girder_assetstore is shared only by the girder container.
  The workers ALWAYS access files through Girder's API,
  never by mounting the assetstore volume directly.
```

---

## 11. Ports exposed on the host

The externally visible ports depend on the stack.

**Dev stack (root `docker-compose.yml`)** – HTTP, convenient for development:

```
  HOST
  ├── :8080  →  Girder HTTP (UI + REST API)
  └── :15672 →  RabbitMQ Management UI (diagnostics)

  Everything else (MongoDB :27017, Redis :6379, internal queues)
  is reachable ONLY between the containers on the internal network.
```

**Full stack (`deploy/full`)** – the only public entry point is nginx, over HTTPS:

```
  HOST
  ├── :80    →  nginx  → 301 redirect to :443
  ├── :443   →  nginx  → TLS terminated here, internal proxy to girder:8080
  ├── :8081  →  Girder direct (admin/debug only, behind the proxy)
  └── :15672 →  RabbitMQ Management UI (diagnostics)
```

See [section 12 – Communication security (TLS/HTTPS)](#12-communication-security-tlshttps)
for the TLS details.

---

## 12. Communication security (TLS/HTTPS)

In the **full stack (`deploy/full`)** all application traffic is encrypted: both the
browser traffic to the interface and — crucially — the **job** traffic
(worker → Girder). TLS is terminated at **nginx**; behind the proxy, on the isolated
internal Docker network, traffic stays in HTTP towards `girder:8080`.

```
  browser ──HTTPS──▶ nginx:443 ──HTTP (internal network)──▶ girder:8080
  worker  ──HTTPS──▶ nginx:443 ──HTTP (internal network)──▶ girder:8080
                       ▲
                       └─ server certificate, SAN: nginx, localhost,
                          ${DIADEMA_PUBLIC_HOST}, 127.0.0.1
```

### Internal CA and certificate generation (`init-certs`)

A dedicated init service, **`init-certs`**, generates an **internal self-signed CA** and a
server certificate at first startup, stored in a shared volume (`certs`):

```
  [1] MongoDB, Redis, RabbitMQ  (healthy)
  [2] init-permissions          (assetstore volume writable)
  [2] init-certs                (generates ca.crt/ca.key + server.crt/server.key)
        │  - idempotent: if server.crt already exists, it regenerates nothing
        │  - SAN: DNS:nginx, DNS:localhost, DNS:${DIADEMA_PUBLIC_HOST}, IP:127.0.0.1
        ▼
  [3] Girder Server  →  [4] nginx + workers  (mount the `certs` volume read-only)
```

The CA is never committed: it lives only in the Docker volume. The browser will show a
warning about the self-signed certificate until `ca.crt` is imported into the local trust
store (extractable with `docker compose cp nginx:/etc/nginx/certs/ca.crt ./ca.crt`).

### Certificate verification in the jobs

The workers call Girder over `https://nginx/api/v1` (`GIRDER_API_URL` and
`GIRDER_WORKER_CALLBACK_URL` variables). Certificate verification is **not disabled**: each
client container (girder + workers) mounts the CA and points to it via the standard
**`REQUESTS_CA_BUNDLE=/etc/nginx/certs/ca.crt`** variable, so `GirderClient`/`requests`
validate the chain against the internal CA. An invalid certificate makes the call fail.

```
  worker
    │  GirderClient(apiUrl="https://nginx/api/v1")
    │  requests verifies the cert with REQUESTS_CA_BUNDLE → ca.crt
    ▼
  nginx (TLS) ──▶ girder:8080
```

### HTTP→HTTPS redirect

nginx accepts port 80 only to redirect (`301`) to `https://`. No application content
travels in clear text. The `X-Forwarded-Proto: https` header is propagated to Girder so
that the public URLs it generates are consistent.

### Server internal loopback

Some of the plugin's REST routes instantiate a `GirderClient` that calls back into the
**same** Girder instance during a browser request. With `X-Forwarded-Proto: https` the URL
derived from the request would become the public HTTPS address, causing the call to
needlessly leave through the network (hairpin via nginx). For this reason those calls use
an **internal loopback** over HTTP (`_internal_api_url()` → `http://localhost:8080/api/v1`)
that never leaves the container.

### Current limits (out of scope)

- The **dev stack** at the root stays pure HTTP (development convenience).
- The **RabbitMQ** broker (AMQP), **MongoDB** and **Redis** communicate in clear text but
  **only** on the internal Docker network, not exposed to the host.
- A public certificate (e.g. Let's Encrypt) is not provided: trust is based on the internal
  CA, suitable for container-to-container communication.
