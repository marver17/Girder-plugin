"""
Girder Worker plugin entry point for NIfTI QC.

Questo modulo DEVE restare privo di import da girder_worker.app
per evitare il circular import durante il bootstrap di stevedore.
Il ciclo che si vuole evitare è:
  girder_worker.app → discover_tasks → stevedore → girder_nifti_qc.tasks
    → girder_worker.app  (circular!)

La soluzione standard è separare il descrittore del plugin
(questo file) dal modulo dei task (tasks.py).
"""

import os


def _patch_gw_task_prerun():
    """Rimpiazza localhost nella jobInfoSpec.url prima che gw_task_prerun la usi.

    Quando Girder (container 'girder') invia un task Celery, incorpora nel
    messaggio jobInfoSpec.url con l'URL del server. Se GIRDER_WORKER_CALLBACK_URL
    non è risolto correttamente, quella URL contiene 'localhost' — irraggiungibile
    dall'interno del container mriqc-worker.

    Questo wrapper intercetta gw_task_prerun PRIMA che costruisca il JobManager,
    sostituisce tutti i 'localhost/127.0.0.1' con l'hostname Docker corretto
    (letto da GIRDER_API_URL), poi chiama il gestore originale.
    """
    import re
    from urllib.parse import urlparse

    girder_api_url = os.environ.get("GIRDER_API_URL", "")
    if not girder_api_url:
        print("[nifti_qc] GIRDER_API_URL non impostato, skip patch gw_task_prerun")
        return

    parsed = urlparse(girder_api_url)
    correct_netloc = parsed.netloc  # es. "girder:8080"
    _LOCALHOST_RE = re.compile(r"(localhost|127\.0\.0\.1)(:\d+)?")

    # Ottieni il riferimento diretto a gw_task_prerun da girder_worker.app
    # (la funzione è registrata con @task_prerun.connect ed è un nome di modulo).
    try:
        import girder_worker.app as _gw_app

        original_fn = getattr(_gw_app, "gw_task_prerun", None)
    except ImportError:
        print("[nifti_qc] Impossibile importare girder_worker.app, skip patch")
        return

    if original_fn is None:
        print("[nifti_qc] gw_task_prerun non trovato in girder_worker.app, skip patch")
        return

    from celery.signals import task_prerun

    # Rimuovi il gestore originale e sostituiscilo con il wrapper.
    task_prerun.disconnect(original_fn)

    def patched_gw_task_prerun(task=None, **kwargs):
        # 1. Correggi jobInfoSpec.url (usata da gw_task_prerun per il JobManager)
        spec = getattr(task.request, "jobInfoSpec", None)
        if spec and isinstance(spec, dict):
            url = spec.get("url", "")
            if url and _LOCALHOST_RE.search(url):
                fixed_url = _LOCALHOST_RE.sub(correct_netloc, url)
                task.request.jobInfoSpec = {**spec, "url": fixed_url}
                print(f"[nifti_qc] jobInfoSpec.url patchato: {url!r} → {fixed_url!r}")

        # 2. Correggi girder_api_url nell'header del task (usata dai task stessi)
        req_api_url = getattr(task.request, "girder_api_url", None)
        if req_api_url and _LOCALHOST_RE.search(req_api_url):
            task.request.girder_api_url = _LOCALHOST_RE.sub(correct_netloc, req_api_url)

        # 3. Chiama il gestore originale con URL già corretti.
        # Wrappato in try/except: se il job è già in stato terminale (ERROR,
        # CANCELLED, SUCCESS) Girder risponde 400 e girder_worker solleva
        # StateTransitionException. In Celery 5.x un'eccezione in un receiver
        # di segnale impedisce l'esecuzione del task — quindi l'assorbiamo.
        try:
            original_fn(task=task, **kwargs)
        except Exception as _e:
            _msg = str(_e)
            # "Invalid state transition to '2'" è atteso durante un re-delivery
            # (acks_late): il job è già in stato terminale e gw_task_prerun cerca
            # di tornare a RUNNING. Non è un errore reale — logghiamo a DEBUG.
            if "Invalid state transition" in _msg and "Current state is '3'" in _msg:
                pass  # re-delivery su job già SUCCESS: ignorato silenziosamente
            else:
                print(
                    f"[nifti_qc] gw_task_prerun non-fatal (job già in stato terminale?): {_e}"
                )

    task_prerun.connect(patched_gw_task_prerun, weak=False)
    print(f"[nifti_qc] gw_task_prerun patchato: localhost → {correct_netloc}")


class NiftiQCWorkerPlugin:
    """Plugin descriptor for Girder Worker stevedore discovery."""

    def __init__(self, girder_worker_app):
        self.app = girder_worker_app
        # Installa il patch subito, mentre l'app Celery è ancora in fase di bootstrap.
        # A questo punto gw_task_prerun è già registrato (girder_worker.app è importato)
        # ma nessun task è ancora stato ricevuto — momento ideale per wrapparlo.
        _patch_gw_task_prerun()

        # ── Disabilita l'AMQP heartbeat ─────────────────────────────────────────
        # Con --pool=solo il thread principale è bloccato durante l'esecuzione
        # del task (MRIQC dura 5-30 min): Celery non può inviare heartbeat AMQP.
        # RabbitMQ chiude la connessione dopo il timeout (default 60 s) →
        # l'ACK del task completato fallisce → il messaggio viene ri-consegnato.
        # Impostare broker_heartbeat=0 disabilita il meccanismo côté client:
        # RabbitMQ non si aspetta heartbeat e non chiude la connessione.
        # Questo è il punto più tardivo in cui la configurazione può essere
        # iniettata prima che il worker stabilisca la connessione AMQP.
        self.app.conf.broker_heartbeat = 0
        self.app.conf.broker_transport_options = {
            **self.app.conf.broker_transport_options,
            "heartbeat": 0,
        }
        # Celery 5.x: se nonostante tutto la connessione cade mentre un task
        # è in esecuzione, cancella il task anziché lasciarlo completare senza
        # poter fare l'ACK (evita il re-delivery silenzioso).
        self.app.conf.worker_cancel_long_running_tasks_on_connection_loss = True
        # ────────────────────────────────────────────────────────────────────────

    def task_imports(self):
        """Restituisce la lista dei moduli che contengono i task Celery.

        girder_worker aggiunge questi moduli a CELERY_INCLUDE e li importa
        DOPO che girder_worker.app è completamente inizializzato,
        risolvendo il circular import.
        """
        return ["girder_nifti_qc.tasks"]


def load_worker_plugin(celery_app):
    """
    Entry point per stevedore (girder_worker_plugins).
    Chiamata da girder_worker durante il bootstrap.

    Args:
        celery_app: L'istanza dell'app Celery di girder_worker.

    Returns:
        NiftiQCWorkerPlugin: Istanza del plugin descriptor.
    """
    return NiftiQCWorkerPlugin(celery_app)
