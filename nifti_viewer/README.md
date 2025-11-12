# NIfTI Viewer Plugin per Girder

Un plugin per la visualizzazione e l'analisi di file NIfTI (Neuroimaging Informatics Technology Initiative) in Girder.

## Caratteristiche

### Backend
- Parsing automatico dei file NIfTI (.nii, .nii.gz)
- Estrazione completa dei metadati: dimensioni, dimensione voxel, tipo di dato, orientamento
- Supporto per file JSON "sidecar" contenenti metadati DICOM
- API REST per il parsing e il recupero dei metadati
- Tracciamento automatico delle associazioni tra file

### Frontend
- Viewer 2D interattivo con rendering su canvas
- Visualizzazione multi-planare: assiale, coronale, sagittale
- Controlli avanzati di windowing: livello (window level) e larghezza (window width)
- Navigazione delle slice in tempo reale tramite slider
- Visualizzazione ordinata dei metadati
- Interfaccia responsiva e moderna

## Requisiti

- Girder 5.0.0+
- Python 3.8+
- nibabel >= 4.0.0
- numpy >= 1.20.0

## Installazione (3 passaggi)

1) Installare il backend

```bash
cd /percorso/del/progetto/nifti_viewer
pip install -e .

# Se serve il supporto a Keycloak (opzionale):
pip install python-keycloak
```

2) Costruire il frontend

```bash
cd girder_nifti_viewer/web_client
npm install
npm run build
```

3) Riavviare Girder

```bash
girder serve
```


## Note e TODO

- Migliorare la resa grafica del viewer e la correzione dell'orientamento basata sui metadati.
- Raffinare la gestione dei metadati (formattazione, campi aggiuntivi, unificazione dei nomi).
- Avvicinare l'aspetto del frontend a quello di altri viewer (es. dicom-viewer) se necessario.
- Verificare la sincronizzazione tra file NIfTI e sidecar JSON: attualmente il parsing parte all'upload del file NIfTI; se il JSON viene caricato successivamente alcune informazioni potrebbero andare perse. Valutare una logica che scansiona e associa sidecar successivi.