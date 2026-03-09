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


class NiftiQCWorkerPlugin:
    """Plugin descriptor for Girder Worker stevedore discovery."""

    def __init__(self, girder_worker_app):
        self.app = girder_worker_app

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
