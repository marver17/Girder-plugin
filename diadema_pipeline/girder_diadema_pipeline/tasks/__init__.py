"""
Package girder_diadema_pipeline.tasks
Re-esporta tutti i task Celery DIADEMA per backward compatibility.

Struttura:
  _helpers.py    – utility condivise (no tasks Celery)
  mriqc.py       – run_mriqc_task
  freesurfer.py  – run_freesurfer_task
  lstai.py       – run_lstai_task
"""

from .freesurfer import run_freesurfer_task, upload_freesurfer_results
from .lstai import run_lstai_task
from .mriqc import run_mriqc_task

__all__ = [
    "run_mriqc_task",
    "run_freesurfer_task",
    "upload_freesurfer_results",
    "run_lstai_task",
]
