# NIfTI Viewer Plugin per Girder

Plugin completo per la visualizzazione e analisi di file NIfTI (Neuroimaging Informatics Technology Initiative) in Girder.

## Caratteristiche

### Backend
- Parsing automatico di file NIfTI (.nii, .nii.gz)
- Estrazione completa dei metadati: dimensioni, voxel size, tipo dati, orientamento
- Supporto per file JSON sidecar con metadati DICOM
- API REST per parsing e recupero metadati
- Tracciamento automatico delle associazioni file

### Frontend
- Viewer 2D interattivo con rendering canvas
- Visualizzazione multi-planare: assiale, coronale, sagittale
- Controlli avanzati windowing: livello e larghezza finestra
- Navigazione slice con slider in tempo reale
- Display metadati organizzato
- Design responsivo e moderno

## Requisiti

- Girder 5.0.0+
- Python 3.8+
- nibabel >= 4.0.0
- numpy >= 1.20.0

## Installazione

1. Copia il plugin in `girder/plugins/`
2. Installa: `pip install -e .`
3. Installare frontend usando npm build e poi npm install all'interno del folder ../web_client
3. Abilita il plugin nell'admin panel
4. Carica file NIfTI per testare

## Utilizzo

Carica file NIfTI in Girder. Il plugin estrarrà automaticamente i metadati e fornirà l'interfaccia di visualizzazione interattiva.