"""
Configurazione DIADEMA Pipeline.

Le impostazioni sono accessibili dall'Admin UI di Girder:
  Impostazioni → (sezione DIADEMA Pipeline)

Ordine di priorità per le directory:
  1. Valore in Settings (questa configurazione)
  2. Variabile d'ambiente nel container (DIADEMA_MRIQC_OUTPUT_DIR, ecc.)
  3. Default hardcoded (/data/diadema/...)
"""

import logging

from girder.exceptions import ValidationException
from girder.utility import setting_utilities

logger = logging.getLogger(__name__)


class PluginSettings:
    # ── Dove salvare i risultati ─────────────────────────────────────────────
    # "item"        → metadata + file sull'item Girder (default, retrocompatibile)
    # "derivatives" → cartella derivatives/ BIDS sul filesystem del worker
    OUTPUT_STORAGE = "diadema.output_storage"

    # ── Directory di output per ogni tool ───────────────────────────────────
    # Se vuoto, viene usata la variabile d'ambiente o il default hardcoded.
    MRIQC_OUTPUT_DIR = "diadema.mriqc_output_dir"
    SUBJECTS_DIR = "diadema.subjects_dir"
    LSTAI_OUTPUT_DIR = "diadema.lstai_output_dir"

    # ── Visibilità tool nel widget ───────────────────────────────────────────
    # Dict {"mriqc": bool, "freesurfer": bool, "lstai": bool}
    WIDGET_ENABLED = "diadema.widget_enabled"

    # ── Campi da visualizzare nel widget MRIQC ────────────────────────────────
    # Lista di chiavi IQM dall'output MRIQC (es. ["snr_total", "cnr", ...])
    WIDGET_FIELDS_MRIQC = "diadema.widget_fields_mriqc"

    # ── Strutture da visualizzare nel widget FreeSurfer ───────────────────────
    # Lista di chiavi presenti in stats.subcortical o stats.global
    WIDGET_FIELDS_FREESURFER = "diadema.widget_fields_freesurfer"


# ── Default ──────────────────────────────────────────────────────────────────

_DEFAULT_WIDGET_ENABLED = {
    "mriqc": True,
    "freesurfer": True,
    "lstai": False,  # non ancora implementato
}

_DEFAULT_WIDGET_FIELDS_MRIQC = [
    "snr_total",
    "cnr",
    "fwhm_avg",
    "efc",
    "fber",
    "qi_1",
    "qi_2",
    "inu_range",
    "wm2max",
]

_DEFAULT_WIDGET_FIELDS_FREESURFER = [
    "Left-Hippocampus",
    "Right-Hippocampus",
    "Left-Amygdala",
    "Right-Amygdala",
    "Left-Thalamus-Proper",
    "Right-Thalamus-Proper",
    "BrainSegVol",
    "EstimatedTotalIntraCranialVol",
]


@setting_utilities.default(PluginSettings.OUTPUT_STORAGE)
def _default_output_storage():
    return "item"


@setting_utilities.default(PluginSettings.MRIQC_OUTPUT_DIR)
def _default_mriqc_output_dir():
    return ""


@setting_utilities.default(PluginSettings.SUBJECTS_DIR)
def _default_subjects_dir():
    return ""


@setting_utilities.default(PluginSettings.LSTAI_OUTPUT_DIR)
def _default_lstai_output_dir():
    return ""


@setting_utilities.default(PluginSettings.WIDGET_ENABLED)
def _default_widget_enabled():
    return dict(_DEFAULT_WIDGET_ENABLED)


@setting_utilities.default(PluginSettings.WIDGET_FIELDS_MRIQC)
def _default_widget_fields_mriqc():
    return list(_DEFAULT_WIDGET_FIELDS_MRIQC)


@setting_utilities.default(PluginSettings.WIDGET_FIELDS_FREESURFER)
def _default_widget_fields_freesurfer():
    return list(_DEFAULT_WIDGET_FIELDS_FREESURFER)


# ── Validatori ───────────────────────────────────────────────────────────────


@setting_utilities.validator(PluginSettings.OUTPUT_STORAGE)
def _validate_output_storage(doc):
    valid = {"item", "derivatives"}
    if doc["value"] not in valid:
        raise ValidationException(
            f"output_storage deve essere uno tra: {sorted(valid)}", "value"
        )


@setting_utilities.validator(PluginSettings.MRIQC_OUTPUT_DIR)
def _validate_mriqc_output_dir(doc):
    if not isinstance(doc["value"], str):
        raise ValidationException("mriqc_output_dir deve essere una stringa", "value")


@setting_utilities.validator(PluginSettings.SUBJECTS_DIR)
def _validate_subjects_dir(doc):
    if not isinstance(doc["value"], str):
        raise ValidationException("subjects_dir deve essere una stringa", "value")


@setting_utilities.validator(PluginSettings.LSTAI_OUTPUT_DIR)
def _validate_lstai_output_dir(doc):
    if not isinstance(doc["value"], str):
        raise ValidationException("lstai_output_dir deve essere una stringa", "value")


@setting_utilities.validator(PluginSettings.WIDGET_ENABLED)
def _validate_widget_enabled(doc):
    if not isinstance(doc["value"], dict):
        raise ValidationException(
            "widget_enabled deve essere un oggetto JSON "
            '{"mriqc": bool, "freesurfer": bool, "lstai": bool}',
            "value",
        )
    known_tools = {"mriqc", "freesurfer", "lstai"}
    for k, v in doc["value"].items():
        if k not in known_tools:
            raise ValidationException(
                f"Tool non riconosciuto in widget_enabled: '{k}'. "
                f"Valori ammessi: {sorted(known_tools)}",
                "value",
            )
        if not isinstance(v, bool):
            raise ValidationException(
                f"Il valore per '{k}' in widget_enabled deve essere true o false",
                "value",
            )


@setting_utilities.validator(PluginSettings.WIDGET_FIELDS_MRIQC)
def _validate_widget_fields_mriqc(doc):
    if not isinstance(doc["value"], list):
        raise ValidationException(
            "widget_fields_mriqc deve essere una lista JSON di stringhe", "value"
        )


@setting_utilities.validator(PluginSettings.WIDGET_FIELDS_FREESURFER)
def _validate_widget_fields_freesurfer(doc):
    if not isinstance(doc["value"], list):
        raise ValidationException(
            "widget_fields_freesurfer deve essere una lista JSON di stringhe", "value"
        )
