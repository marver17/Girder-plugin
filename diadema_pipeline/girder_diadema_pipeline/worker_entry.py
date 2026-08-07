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

    # gw_task_success (signal task_success, girder_worker/app.py) chiama
    # is_revoked(sender) PRIMA di impostare lo stato SUCCESS del Job, per
    # distinguere un completamento normale da una cancellazione. is_revoked
    # usa il meccanismo di controllo remoto di Celery (app.control.inspect,
    # richiede l'exchange "reply.celery.pidbox"), a cui l'utente RabbitMQ
    # remoto non ha accesso per design (permessi ristretti alla sola coda
    # offloadata). L'AccessRefused che ne risulta non è né AttributeError
    # né StateTransitionException — gw_task_success non lo cattura — quindi
    # l'eccezione esce prima di raggiungere _update_status(..., SUCCESS): il
    # Job Girder resta bloccato a RUNNING(2) per sempre anche a task
    # completato con successo (causa isolata con un job MRIQC reale sul
    # cluster K8s). gw_task_failure non ha questo problema (non chiama
    # is_revoked), infatti i task falliti transitano correttamente a ERROR.
    # Fix: sovrascrivere l'attributo is_revoked sul modulo girder_worker.app
    # (dove gw_task_success/gw_task_failure lo risolvono come nome globale a
    # runtime) con una versione che tratta un fallimento del controllo
    # remoto come "non revocato" invece di propagare l'eccezione.
    original_is_revoked = getattr(_gw_app, "is_revoked", None)
    if original_is_revoked:
        def safe_is_revoked(task):
            try:
                return original_is_revoked(task)
            except Exception as e:
                logger.warning(
                    "[diadema_pipeline] is_revoked fallito (pidbox non "
                    "accessibile), assumo non revocato: %s", e,
                )
                return False

        _gw_app.is_revoked = safe_is_revoked

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
    # NON impostare task_ignore_result=True: girder_worker si appoggia allo
    # stato del task tracciato da Celery (AsyncResult) per decidere quando
    # inviare a Girder la PUT finale che chiude il Job (SUCCESS/ERROR). Con
    # ignore_result=True quello stato non viene mai salvato da nessuna parte
    # (nemmeno in locale) e la PUT finale non parte mai: il Job Girder resta
    # bloccato a RUNNING(2) per sempre anche a task riuscito (verificato con
    # un job reale sul cluster K8s dopo aver introdotto ignore_result=True
    # per errore in un fix precedente). Il backend "cache+memory://" (vedi
    # CELERY_RESULT_BACKEND) è già sufficiente a evitare scritture AMQP sul
    # result backend verso l'exchange "amq.default" ristretto: non serve
    # anche disattivare il tracking del risultato.


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
