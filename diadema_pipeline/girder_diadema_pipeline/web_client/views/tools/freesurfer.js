/**
 * Definizione del tool FreeSurfer recon-all
 */

const FreesurferTool = {
    id: 'freesurfer',
    label: 'FreeSurfer',
    icon: 'icon-cog',
    description: 'recon-all – Segmentazione corticale e sottocorticale',
    resultField: 'diadema_freesurfer',
    workerNote: 'Richiede il container freesurfer-worker (freesurfer/freesurfer)',

    params: [
        {
            name: 'participantLabel',
            label: 'Participant Label',
            type: 'text',
            default: '',
            hint: 'Etichetta BIDS senza prefisso sub- (es. 003). '
                + 'Lasciare vuoto: rilevata automaticamente da nome file → cartella padre → gerarchia.',
        },
        {
            name: 'directive',
            label: 'Direttiva recon-all',
            type: 'select',
            default: '-all',
            hint: '-all esegue la pipeline completa (~6-10 ore).',
            options: [
                { value: '-all',       label: '-all (pipeline completa)' },
                { value: '-autorecon1', label: '-autorecon1 (motion correction + skull strip)' },
                { value: '-autorecon2', label: '-autorecon2 (surface tessellation)' },
                { value: '-autorecon3', label: '-autorecon3 (cortical parcellation)' },
            ],
        },
        {
            name: 'openmpThreads',
            label: 'Thread OpenMP',
            type: 'number',
            default: 4,
            min: 1,
            max: 32,
            hint: 'Aumentare per accelerare su macchine multi-core.',
        },
        {
            name: 'extraFlags',
            label: 'Flag aggiuntivi',
            type: 'text',
            default: '',
            hint: 'Es: -no-isrunning -cw256. Lasciare vuoto per il default.',
        },
        {
            name: 'derivativesRootId',
            label: 'Dataset root (ID folder)',
            type: 'text',
            default: '',
            hint: 'ID Girder della folder radice del dataset BIDS. '
                + 'Lascia vuoto per stima automatica.',
        },
    ],
};

export default FreesurferTool;
