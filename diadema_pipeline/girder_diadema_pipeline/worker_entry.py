"""Worker entry point per DIADEMA Pipeline."""

import logging
import os

logger = logging.getLogger(__name__)


def _patch_gw_signals():
    import re
    from urllib.parse import urlparse
    from celery.signals import task_postrun, task_prerun

    girder_api_url = os.environ.get("GIRDER_API_URL", "")
    if not girder_api_url:
        return

    correct_netloc = urlparse(girder_api_url).netloc
    _RE = re.compile(r"(localhost|127\.0\.0\.1)(:\d+)?")

    try:
        import girder_worker.app as _gw_app
    except ImportError:
        return

    original_prerun = getattr(_gw_app, "gw_task_prerun", None)
    if original_prerun:
        task_prerun.disconnect(original_prerun)

        def patched_prerun(task=None, **kwargs):
            spec = getattr(task.request, "jobInfoSpec", None)
            if spec and isinstance(spec, dict):
                url = spec.get("url", "")
                if url and _RE.search(url):
                    task.request.jobInfoSpec = {**spec, "url": _RE.sub(correct_netloc, url)}
            req_url = getattr(task.request, "girder_api_url", None)
            if req_url and _RE.search(req_url):
                task.request.girder_api_url = _RE.sub(correct_netloc, req_url)
            try:
                original_prerun(task=task, **kwargs)
            except Exception as e:
                msg = str(e)
                terminal = ("Current state is '3'", "Current state is '5'", "Current state is '824'")
                if not ("Invalid state transition" in msg and any(s in msg for s in terminal)):
                    logger.warning("[diadema_pipeline] gw_task_prerun non-fatal: %s", e)

        task_prerun.connect(patched_prerun, weak=False)

    original_postrun = getattr(_gw_app, "gw_task_postrun", None)
    if original_postrun:
        task_postrun.disconnect(original_postrun)

        def patched_postrun(**kwargs):
            try:
                original_postrun(**kwargs)
            except Exception as e:
                msg = str(e)
                terminal = ("Current state is '5'", "Current state is '824'")
                if not ("Invalid state transition" in msg and any(s in msg for s in terminal)):
                    logger.warning("[diadema_pipeline] gw_task_postrun non-fatal: %s", e)

        task_postrun.connect(patched_postrun, weak=False)

    logger.info("[diadema_pipeline] Segnali patchati: localhost → %s", correct_netloc)


class DiademaWorkerPlugin:
    def __init__(self, girder_worker_app):
        self.app = girder_worker_app
        _patch_gw_signals()
        self.app.conf.broker_heartbeat = 0
        self.app.conf.broker_transport_options = {
            **self.app.conf.broker_transport_options,
            "heartbeat": 0,
        }
        self.app.conf.worker_cancel_long_running_tasks_on_connection_loss = True

    def task_imports(self):
        return ["girder_diadema_pipeline.tasks"]


def load_worker_plugin(celery_app):
    return DiademaWorkerPlugin(celery_app)
