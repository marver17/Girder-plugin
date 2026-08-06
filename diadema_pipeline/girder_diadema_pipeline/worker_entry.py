"""Worker entry point per DIADEMA Pipeline."""

import logging
import os
import ssl

logger = logging.getLogger(__name__)


def _patch_gw_signals():
    from urllib.parse import urlparse, urlunparse
    from celery.signals import task_postrun, task_prerun

    girder_api_url = os.environ.get("GIRDER_API_URL", "")
    if not girder_api_url:
        return

    correct_netloc = urlparse(girder_api_url).netloc

    def _rewrite_netloc(url):
        # Il produttore del task (Girder server locale) incorpora nel
        # jobInfoSpec/girder_api_url il PROPRIO GIRDER_API_URL (es. il nome
        # host Docker interno "nginx", o "localhost"): per un worker remoto,
        # sempre irraggiungibile. Riscriviamo sempre il netloc con quello
        # configurato per QUESTO worker (GIRDER_API_URL), incondizionatamente
        # — non solo per i pattern noti "localhost"/"127.0.0.1" (bug trovato
        # con un job reale sul cluster K8s: il produttore usava "nginx",
        # ignorato dal filtro precedente).
        parsed = urlparse(url)
        if not parsed.netloc or parsed.netloc == correct_netloc:
            return url
        return urlunparse(parsed._replace(netloc=correct_netloc))

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
                if url:
                    task.request.jobInfoSpec = {**spec, "url": _rewrite_netloc(url)}
            req_url = getattr(task.request, "girder_api_url", None)
            if req_url:
                task.request.girder_api_url = _rewrite_netloc(req_url)
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


def _apply_conf_overrides(app):
    app.conf.broker_heartbeat = 0
    app.conf.broker_transport_options = {
        **app.conf.broker_transport_options,
        "heartbeat": 0,
    }
    app.conf.worker_cancel_long_running_tasks_on_connection_loss = True

    # kombu/Celery non leggono REQUESTS_CA_BUNDLE (usata solo da `requests`
    # per le chiamate HTTP a Girder): la connessione AMQPS al broker va
    # configurata separatamente, altrimenti fallisce con "self-signed
    # certificate in certificate chain" anche con la CA giusta sul disco
    # (verificato con un worker remoto reale sul cluster K8s).
    broker_url = app.conf.broker_url or os.environ.get("CELERY_BROKER_URL", "")
    ca_bundle = os.environ.get("REQUESTS_CA_BUNDLE")
    if broker_url.startswith("amqps://") and ca_bundle:
        app.conf.broker_use_ssl = {
            "ca_certs": ca_bundle,
            "cert_reqs": ssl.CERT_REQUIRED,
        }
        # I worker remoti (AMQPS attraverso il tunnel) usano un utente
        # RabbitMQ con permessi ristretti via regex alla sola coda offloadata
        # (REMOTE_WORKER_QUEUES_REGEX in deploy/full/docker-compose.yml,
        # servizio init-rabbitmq-remote): niente accesso a "celery.pidbox" /
        # "reply.celery.pidbox", usati dal protocollo di controllo remoto di
        # Celery (ping/revoke/shutdown tra worker). --without-gossip/--mingle
        # nel comando non bastano a evitarli (coprono solo Gossip/Mingle, non
        # il bootstep "Control" del pidbox) — va disattivato qui via config.
        # Non lo disattiviamo per i worker locali (permessi pieni sul vhost)
        # per non perdere `celery control` in quell'ambiente.
        app.conf.worker_enable_remote_control = False

    # ── Code: fairness e robustezza per task lunghi ──────────────────────
    # prefetch=1: con acks_late e task molto lunghi un worker non deve
    # riservare un secondo messaggio che non può processare (i job in coda
    # resterebbero "presi" ma fermi). Con concurrency=1 questo garantisce
    # che ogni worker tenga in carico esattamente un job alla volta.
    app.conf.worker_prefetch_multiplier = 1
    # acks_late + reject_on_worker_lost espliciti a livello app (coerenti
    # coi decoratori @app.task): se il worker muore il messaggio torna in
    # coda invece di essere perso. L'idempotency_guard nei task evita la
    # doppia esecuzione in caso di ri-consegna.
    app.conf.task_acks_late = True
    app.conf.task_reject_on_worker_lost = True
    # I task non producono un "result" Celery utile (lo stato vive in
    # item.diadema), quindi evitiamo scritture inutili sul result backend.
    app.conf.task_ignore_result = True


class DiademaWorkerPlugin:
    def __init__(self, girder_worker_app):
        from celery.signals import worker_init

        self.app = girder_worker_app
        _patch_gw_signals()

        # girder_worker.app chiama discover_tasks(app) — che istanzia questo
        # plugin — PRIMA di app.config_from_object(..., force=True): scrivere
        # su self.app.conf qui, a import-time, verrebbe cancellato dal reload
        # forzato successivo (force=True sovrascrive anche conf già
        # modificata). worker_init gira dopo che la config è stata caricata
        # per intero, quindi è il punto sicuro per applicare gli override
        # (verificato: senza questo rinvio broker_use_ssl non aveva alcun
        # effetto, causando "self-signed certificate in certificate chain"
        # anche con la CA corretta montata).
        worker_init.connect(lambda **kwargs: _apply_conf_overrides(self.app), weak=False)

    def task_imports(self):
        return ["girder_diadema_pipeline.tasks"]


def load_worker_plugin(celery_app):
    return DiademaWorkerPlugin(celery_app)
