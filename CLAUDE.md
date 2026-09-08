# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

Three Girder 5 plugins (`oauth2/`, `nifti_viewer/`, `diadema_pipeline/`) plus the Docker
worker images that execute their neuroimaging pipelines (`diadema-mriqc-worker/`,
`freesurfer-worker/`, `lst-worker/`), and the deployment stacks under `deploy/`.

`ARCHITECTURE.md` is the authoritative description of how the pieces fit together
(job lifecycle, TLS, remote Kubernetes workers) — read it before changing anything
that crosses the Girder ↔ RabbitMQ ↔ worker boundary. `README.md` covers the stacks.

Code comments and docstrings are written in Italian; keep that language when editing them.

## Commands

Nothing runs directly on the host — everything is containerized.

```bash
# Dev stack (Girder on :8080, all workers, live-mounted at /workspace)
cp .env.example .env
docker compose up --build

# Rebuild plugin web clients after JS changes (run on the host, before/while the stack is up)
bash build-frontend.sh                  # all plugins with a web_client
bash build-frontend.sh diadema_pipeline # just one

# Deployment stacks
cd deploy/testing && docker compose up -d --build   # production-like, no LST-AI worker
cd deploy/full    && docker compose up -d --build   # + nginx TLS, WireGuard gateway, remote workers
```

Tests use `pytest-girder`, which spins up an in-process Girder server. Run them
inside the girder container (the plugins and Girder itself must be importable):

```bash
docker compose exec girder pytest /workspace/diadema_pipeline/plugin_tests/ -v
docker compose exec girder pytest /workspace/nifti_viewer/plugin_tests/ -v
docker compose exec girder pytest /workspace/nifti_viewer/plugin_tests/nifti_viewer_test.py::test_name -v
```

Python changes to a plugin require reinstalling it (`pip install /workspace/<plugin>`) or
restarting the container — the deploy entrypoints reinstall from `/workspace` on boot.

## Girder plugin conventions (framework-specific, not generic Python)

These are Girder 5 APIs; do not replace them with hand-rolled equivalents.

- **Registration**: a plugin is a `girder.plugin.GirderPlugin` subclass exposed through the
  `girder.plugin` entry point (`pyproject.toml` / `setup.py`). The entry-point *name* is the
  plugin's internal identifier. `DISPLAY_NAME` is the user-facing name.
- **`load(self, info)`** is the only initialization hook. `info["apiRoot"]` is where REST
  resources are attached (`info["apiRoot"].diadema_pipeline = DiademaResource()`), and
  `info["serverRoot"]` is passed to `registerPluginStaticContent`. Import submodules *inside*
  `load()`, not at module top level — importing `settings.py` there is what registers its
  validators/defaults.
- **REST**: subclass `girder.api.rest.Resource`, declare routes in `__init__` via
  `self.route(method, path_tuple, handler)`. Every handler needs an access decorator
  (`@access.public` / `@access.user(scope=TokenScope.…)` / `@access.admin`) *and*
  `@autoDescribeRoute(Description(...))`, which drives Swagger docs and coerces/validates
  parameters (a `modelParam` yields the loaded document, not an id).
- **Settings**: keys are plain strings namespaced by plugin (`"diadema.mriqc_output_dir"`),
  registered with `@setting_utilities.default(KEY)` and `@setting_utilities.validator(KEY)`.
  Validators raise `girder.exceptions.ValidationException`.
- **Events**: `events.bind(name, handler_name, fn)` / `events.trigger(name, info)`. Used here for
  cross-plugin wiring: `nifti_viewer` fires `nifti_viewer.register_widgets`, `diadema_pipeline`
  binds to it and registers a `WidgetProviderBase` subclass (see
  [widget_registry.py](nifti_viewer/girder_nifti_viewer/widget_registry.py)). The registration is
  attempted twice — immediately via `info["nifti_widget_registry"]` if that plugin loaded first,
  and via the event otherwise — because plugin load order is not guaranteed.
- **Exposing model fields**: custom document fields are invisible over REST until declared,
  e.g. `Item().exposeFields(level=AccessType.READ, fields={"diadema"})`.
- **Web client**: each plugin builds its own bundle (vite → `web_client/dist/`) and registers it
  with `registerPluginStaticContent(plugin=…, css=…, js=…, staticDir=…, tree=info["serverRoot"])`.
  The `dist/` output must be listed in `[tool.setuptools.package-data]` or it will not ship.

Sources: [Girder plugin development docs](https://girder.readthedocs.io/en/latest/plugin-development.html).

## The DIADEMA pipeline: how a job actually flows

`diadema_pipeline` is the only non-trivial plugin. Two parallel REST surfaces exist for every
tool — **item-level** (`/:id/run/:toolId`) and **session-level** (`/session/:folderId/run/:toolId`,
which fans out over the NIfTI items of a BIDS session). Status is mirrored between the two by
`_propagate_item_status_to_session` / `_propagate_session_status_to_items` in
[rest.py](diadema_pipeline/girder_diadema_pipeline/rest.py); a change to one path usually needs the
mirror in the other.

State lives on the Girder document under the `diadema` field (per-tool sub-documents), written by
`update_diadema_tool` / `update_diadema_tool_on_folder`.

Tasks live in [tasks/](diadema_pipeline/girder_diadema_pipeline/tasks/) — one module per tool plus
`_helpers.py` (BIDS resolution, idempotency, progress, upload). They are Celery tasks loaded into
the workers through the **second** entry point, `girder_worker_plugins` →
`worker_entry:load_worker_plugin`. Routing is by queue name only (`diadema_mriqc`, `freesurfer`,
`lstai`); which machine runs a pipeline is a deployment choice, never a code change.

Workers never touch MongoDB or the assetstore — all I/O goes through the Girder REST API with a
job-scoped token.

### Adding a new pipeline tool — checklist

Derived from the pattern the three existing tools follow. Verify against the actual code before
relying on it blindly; this is a synthesis, not a guarantee every step is complete.

1. **Task module**: add `tasks/<tool>.py` following the shape of the existing modules, using
   `_helpers.py` for BIDS resolution, idempotency checks, progress reporting, and upload — don't
   reimplement these.
2. **REST routes** in `rest.py`: add both the item-level and session-level route for the tool.
   Wire `_propagate_item_status_to_session` and `_propagate_session_status_to_items` in *both*
   directions — this is the step most likely to be forgotten, since each mirror function alone
   looks sufficient.
3. **State field**: use `update_diadema_tool` / `update_diadema_tool_on_folder` to write the
   tool's sub-document under `diadema`; don't invent a parallel field.
4. **Settings** (if the tool needs configurable paths/options): register via
   `@setting_utilities.default(KEY)` / `@setting_utilities.validator(KEY)`, namespaced
   `"diadema.<tool>_<setting>"`.
5. **Queue routing**: pick or create a queue name for the tool and route the Celery task to it.
   Remember this only decides *which worker* runs it — the assignment of queues to physical/K8s
   workers happens at the deployment layer, not here.
6. **Worker image**: if the tool needs a new runtime environment, mirror the Dockerfile/entrypoint
   pattern of an existing worker (`diadema-mriqc-worker/`, `freesurfer-worker/`, or `lst-worker/`,
   whichever is closest to the new tool's dependencies) rather than designing a new layout.
7. **`worker_entry.py`**: touch it only if the new tool needs something the existing invariants
   don't already cover (see below) — most new tools shouldn't need to.
8. **Tests**: add a `plugin_tests/` module for the new tool following the pattern of the existing
   tests referenced under Commands.
9. **Deployment**: decide, as a deploy-config change, which stack and which worker(s) pick up the
   new queue — `deploy/testing`, `deploy/full`, or `deploy/k8s-remote-worker`.

### worker_entry.py is load-bearing

[worker_entry.py](diadema_pipeline/girder_diadema_pipeline/worker_entry.py) monkey-patches
`girder_worker` and overrides Celery config. Each patch documents a real production failure in its
comment; read them before touching anything there. The invariants that repeatedly broke:

- Config overrides must be applied on `worker_init`, not at import time — `girder_worker` calls
  `config_from_object(..., force=True)` after instantiating the plugin and would wipe them.
- **Never set `task_ignore_result = True`** — `girder_worker` needs the Celery result state to send
  the final PUT that closes the Girder Job; without it, jobs hang in `RUNNING` forever.
- `is_revoked` is wrapped to swallow failures: remote workers have RabbitMQ permissions restricted
  to their own queue and cannot reach the pidbox exchange, and the raw exception prevented jobs
  from reaching `SUCCESS`.
- The `girder_api_url` embedded in a task by the producer is rewritten unconditionally to this
  worker's own `GIRDER_API_URL` — the producer's hostname is meaningless to a remote worker.
- `DIADEMA_WORKER_MAX_TASKS` makes a worker self-terminate after N tasks. Set it only for
  Kubernetes `Job`-based workers (KEDA `ScaledJob`); never for the long-running compose workers.

## Deployment specifics worth knowing

- **`deploy/full`** terminates TLS at nginx with a self-signed internal CA generated by the
  `init-certs` service. Clients trust it via `REQUESTS_CA_BUNDLE`. Celery/kombu ignore that
  variable, so AMQPS is configured separately via `broker_use_ssl` in `worker_entry.py`.
- Plugin REST handlers that need to call back into their own Girder instance use
  `_internal_api_url()` (plain HTTP loopback), deliberately bypassing the public HTTPS URL to
  avoid a hairpin through nginx.
- **`deploy/k8s-remote-worker/`** offloads compute to an external cluster over WireGuard; its
  `README.md` and `CONNECTING-GIRDER-TO-CLUSTER.md` are the operational reference. Remote workers
  use `CELERY_RESULT_BACKEND=rpc://` since MongoDB is unreachable from there.
- `.env` files, `freesurfer_license.txt` and the internal CA are git-ignored and per-environment.
  Cluster IPs and hostnames are redacted from commits.

## High-risk files (quick reference)

Changes here have caused real production incidents or touch sensitive material. Read the
relevant section above in full before editing, and prefer the smallest possible diff.

| File / area | Why it's risky |
|---|---|
| `diadema_pipeline/girder_diadema_pipeline/worker_entry.py` | Each patch fixes a specific past production failure (see invariants above); reverting or "simplifying" any line likely reintroduces it. |
| `deploy/full/` (nginx TLS, `init-certs`) | Certificate/trust chain wiring; Celery's AMQPS trust is configured separately from `REQUESTS_CA_BUNDLE` and easy to break silently. |
| `.env`, `freesurfer_license.txt`, internal CA files | Git-ignored, per-environment secrets — never commit, never hardcode a value from one environment as a "default". |
| `rest.py` status-propagation functions | Item-level and session-level status are mirrored manually; a fix applied to only one side reintroduces drift. |