/**
 * Definizione del tool MRI QC (MRIQC)
 *
 * Ogni tool è un oggetto con:
 *   id          → usato nella route REST: POST /diadema_pipeline/:itemId/run/:id
 *   label       → etichetta visibile nell'UI
 *   icon        → classe icona Girder (font-awesome subset)
 *   description → testo descrittivo nel radio item
 *   resultField → prefisso dei campi sull'item (es. diadema_mriqc_results)
 *   workerNote  → nota sul container richiesto (informativa)
 *   params[]    → lista parametri del form Advanced
 *
 * Ogni param ha:
 *   name     → key inviata al backend come query param
 *   label    → etichetta nel form
 *   type     → 'text' | 'number' | 'select' | 'checkbox'
 *   default  → valore di default
 *   options  → array di {value, label} per type='select'
 *   min/max  → per type='number'
 *   hint     → tooltip/small text opzionale
 */

const MriqcTool = {
    id: 'mriqc',
    label: 'MRI QC',
    icon: 'icon-chart-bar',
    description: 'MRIQC – Image Quality Metrics per RM strutturale e funzionale',
    resultField: 'diadema_mriqc',
    workerNote: 'Richiede il container mriqc-worker (nipreps/mriqc)',

    params: [
        {
            name: 'participantLabel',
            label: 'Participant Label',
            type: 'text',
            default: '001',
            hint: 'Etichetta BIDS (es. 001). Auto-rilevata dal nome file.',
        },
        {
            name: 'modality',
            label: 'Modalità MRI',
            type: 'select',
            default: 'T1w',
            hint: 'Auto-rilevata dal nome file quando possibile.',
            options: [
                { value: 'T1w',  label: 'T1-weighted (T1w)' },
                { value: 'T2w',  label: 'T2-weighted (T2w)' },
                { value: 'bold', label: 'BOLD fMRI' },
                { value: 'dwi',  label: 'Diffusion (DWI)' },
            ],
        },
        {
            name: 'timeout',
            label: 'Timeout (secondi)',
            type: 'number',
            default: 1800,
            min: 300,
            max: 7200,
            hint: 'MRIQC impiega tipicamente 5-30 min. Default: 30 min.',
        },
        {
            name: 'derivativesRootId',
            label: 'Dataset root (ID folder)',
            type: 'text',
            default: '',
            hint: 'ID Girder della folder radice del dataset BIDS (es. 64a1b2c3...). '
                + 'Lascia vuoto per stima automatica: risale la gerarchia cercando '
                + 'dataset_description.json.',
        },
    ],
};

export default MriqcTool;
