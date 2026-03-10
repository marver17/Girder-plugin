"""
Girder Worker plugin entry point per Plugin Template
──────────────────────────────────────────────────────────────────────────────
REGOLE CRITICHE:
  1. Questo file NON deve importare girder_worker.app a livello di modulo.
     Lo importa solo all'interno delle funzioni, dopo che stevedore ha
     completato il bootstrap. In caso contrario si genera un circular import:
       girder_worker.app → discover_tasks → stevedore
         → girder_plugin_template.worker_entry → girder_worker.app  (LOOP!)

  2. task_imports() restituisce la lista dei moduli con i task Celery.
     girder_worker li importa DOPO il bootstrap, risolvendo il circular import.

  3. Il metodo __init__ della classe descriptor è il punto ideale per
     configurare l'app Celery (broker_heartbeat, ecc.) prima che il worker
     stabilisca la connessione AMQP.
──────────────────────────────────────────────────────────────────────────────
"""

import os


def _patch_gw_signals():
    """
    Patch opzionale dei segnali Celery gw_task_prerun / gw_task_postrun.

    QUANDO USARLA:
      - Il worker gira in un container Docker diverso da Girder.
      - L'URL nella jobInfoSpec può contenere "localhost" irraggiungibile
        dall'interno del container.
      - Si vuole assorbire silenziosamente le StateTransitionException
        che girder_worker solleva su job già in stato terminale (SUCCESS,
        CANCELLED, ecc.) durante un re-delivery.

    QUANDO NON USARLA:
      - Worker e Girder usano lo stesso hostname.
      - Non hai task lunghi con acks_late.

    In caso di dubbio, lascia questa funzione (non fa danni).
    """
    import re
    from urllib.parse import urlparse
    from celery.signals import task_postrun, task_prerun

    girder_api_url = os.environ.get("GIRDER_API_URL", "")
    if not girder_api_url:
        print("[plugin_template] GIRDER_API_URL non impostato, skip patch segnali")
        return

    parsed = urlparse(girder_api_url)
    correct_netloc = parsed.netloc   # es. "girder:8080"
    _LOCALHOST_RE = re.compile(r"(localhost|127\.0\.0\.1)(:\d+)?")

    # ── Patch gw_task_prerun ──────────────────────────────────────────────────
    try:
        import girder_worker.app as _gw_app
    except ImportError:
        print("[plugin_template] Impossibile importare girder_worker.app, skip patch")
        return

    original_prerun = getattr(_gw_app, "gw_task_prerun", None)
    if original_prerun is None:
        print("[plugin_template] gw_task_prerun non trovato, skip patch")
        return

    task_prerun.disconnect(original_prerun)

    def patched_prerun(task=None, **kwargs):
        # 1. Correggi jobInfoSpec.url
        spec = getattr(task.request, "jobInfoSpec", None)
        if spec and isinstance(spec, dict):
            url = spec.get("url", "")
            if url and _LOCALHOST_RE.search(url):
                task.request.jobInfoSpec = {
                    **spec, "url": _LOCALHOST_RE.sub(correct_netloc, url)
                }
        # 2. Correggi girder_api_url nell'header del task
        req_url = getattr(task.request, "girder_api_url", None)
        if req_url and _LOCALHOST_RE.search(req_url):
            task.request.girder_api_url = _LOCALHOST_RE.sub(correct_netloc, req_url)
        # 3. Chiama l'handler originale, assorbi eccezioni attese
        try:
            original_prerun(task=task, **kwargs)
        except Exception as _e:
            _msg = str(_e)
            # "Invalid state transition" su job già SUCCESS/CANCELLED è atteso
            # durante un re-delivery (acks_late). Non è un errore reale.
            _terminal_states = ("Current state is '3'", "Current state is '5'", "Current state is '824'")
            if "Invalid state transition" in _msg and any(s in _msg for s in _terminal_states):
                pass  # silenzioso
            else:
                print(f"[plugin_template] gw_task_prerun non-fatal: {_e}")

    task_prerun.connect(patched_prerun, weak=False)

    # ── Patch gw_task_postrun ─────────────────────────────────────────────────
    original_postrun = getattr(_gw_app, "gw_task_postrun", None)
    if original_postrun:
        task_postrun.disconnect(original_postrun)

        def patched_postrun(**kwargs):
            try:
                original_postrun(**kwargs)
            except Exception as _e:
                _msg = str(_e)
                _terminal_states = ("Current state is '5'", "Current state is '824'")
                if "Invalid state transition" in _msg and any(s in _msg for s in _terminal_states):
                    pass
                else:
                    print(f"[plugin_template] gw_task_postrun non-fatal: {_e}")

        task_postrun.connect(patched_postrun, weak=False)

    print(f"[plugin_template] Segnali Celery patchati: localhost → {correct_netloc}")


class PluginTemplateWorkerPlugin:
    """
    Descriptor del plugin per girder_worker (pattern stevedore).

    girder_worker istanzia questa classe passando l'app Celery come argomento.
    Gli hook principali sono:
      - __init__: configura l'app Celery, installa i patch sui segnali
      - task_imports(): restituisce i moduli dei task (chiamato DOPO il bootstrap)
    """

    def __init__(self, girder_worker_app):
        self.app = girder_worker_app

        # Installa i patch sui segnali Celery.
        # Questo è il momento giusto: girder_worker.app è già importato
        # (siamo stati chiamati da esso), ma nessun task è ancora stato ricevuto.
        _patch_gw_signals()

        # ── Disabilita heartbeat AMQP ─────────────────────────────────────────
        # NECESSARIO se i task durano più di ~60 secondi con --pool=solo.
        #
        # Con --pool=solo il thread principale è bloccato durante l'esecuzione
        # del task. Celery non può inviare heartbeat AMQP.
        # RabbitMQ chiude la connessione dopo il timeout (default 60 s).
        # L'ACK del task completato fallisce → il messaggio viene ri-consegnato
        # all'infinito (re-delivery loop).
        #
        # broker_heartbeat=0 disabilita il meccanismo lato client:
        # RabbitMQ non si aspetta heartbeat e non chiude la connessione.
        #
        # RIMUOVI o commenta questo blocco se i tuoi task durano < 60 s
        # oppure usi --pool=prefork/gevent (che non bloccano il main thread).
        self.app.conf.broker_heartbeat = 0
        self.app.conf.broker_transport_options = {
            **self.app.conf.broker_transport_options,
            "heartbeat": 0,
        }
        # Se nonostante tutto la connessione cade durante un task,
        # cancellalo invece di lasciarlo completare senza poter fare l'ACK.
        self.app.conf.worker_cancel_long_running_tasks_on_connection_loss = True

    def task_imports(self):
        """
        Restituisce la lista dei moduli che contengono task Celery.

        girder_worker aggiunge questi moduli a CELERY_INCLUDE e li importa
        DOPO che girder_worker.app è completamente inizializzato.
        Questo risolve il circular import:
          girder_worker.app → (stevedore bootstrap) → worker_entry.py
            → task_imports() → ["girder_plugin_template.tasks"]
              → importato dopo bootstrap ✓
        """
        return ["girder_plugin_template.tasks"]


def load_worker_plugin(celery_app):
    """
    Entry point stevedore (girder_worker_plugins).

    Viene chiamata da girder_worker durante il bootstrap.
    Deve restituire un'istanza del plugin descriptor.

    Args:
        celery_app: L'istanza dell'app Celery di girder_worker.

    Returns:
        PluginTemplateWorkerPlugin
    """
    return PluginTemplateWorkerPlugin(celery_app)
