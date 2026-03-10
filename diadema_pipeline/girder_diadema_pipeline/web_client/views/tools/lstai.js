/**
 * Definizione del tool LST-AI (Lesion Segmentation Tool)
 */

const LstaiTool = {
    id: 'lstai',
    label: 'LST-AI',
    icon: 'icon-search',
    description: 'LST-AI – Segmentazione automatica lesioni WM con deep learning',
    resultField: 'diadema_lstai',
    workerNote: 'Richiede il container lstai-worker con LST-AI installato',

    params: [
        {
            name: 'participantLabel',
            label: 'Participant Label',
            type: 'text',
            default: '001',
            hint: 'Etichetta del soggetto.',
        },
        {
            name: 'inputType',
            label: 'Tipo input',
            type: 'select',
            default: 'T1+FLAIR',
            hint: 'T1+FLAIR garantisce maggiore accuratezza della segmentazione.',
            options: [
                { value: 'T1+FLAIR', label: 'T1 + FLAIR (raccomandato)' },
                { value: 'T1 only',  label: 'Solo T1' },
            ],
        },
        {
            name: 'threshold',
            label: 'Soglia lesioni',
            type: 'number',
            default: 0.5,
            min: 0.1,
            max: 0.9,
            step: 0.05,
            hint: 'Valori bassi = più sensibile, valori alti = più specifico.',
        },
        {
            name: 'useGpu',
            label: 'Usa GPU (se disponibile)',
            type: 'checkbox',
            default: true,
            hint: "Accelera il processing. Disabilita se la GPU non è disponibile.",
        },
    ],
};

export default LstaiTool;
