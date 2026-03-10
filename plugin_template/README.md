# Plugin Template per Girder

Template per la creazione di nuovi plugin Girder v5 con supporto a:

- REST API (Girder Resource)
- Task Celery asincroni via Girder Worker
- Web client (Backbone + Vite)
- Widget per il viewer NIfTI
- Worker Docker dedicato

## Struttura

```
plugin_template/
├── pyproject.toml                        # Metadati e entry points
├── setup.py                              # Compatibilità pip install -e
├── README.md
├── plugin_tests/
│   ├── __init__.py
│   └── test_basic.py                     # Test di base (pytest-girder)
└── girder_plugin_template/
    ├── __init__.py                       # Classe GirderPlugin
    ├── rest.py                           # Endpoint REST
    ├── tasks.py                          # Task Celery
    ├── worker_entry.py                   # Entry point stevedore worker
    ├── widget_provider.py                # Widget per nifti_viewer
    └── web_client/
        ├── main.js                       # Entry point JS
        ├── package.json
        ├── vite.config.js
        └── views/
            ├── ItemView.js               # Estensione Item View Girder
            └── PluginWidget.js           # Widget custom
```

## Come usare questo template

1. Copia la directory `plugin_template/` con il nome del tuo plugin
2. Trova e sostituisci globalmente:
   - `plugin_template` → `nome_tuo_plugin`
   - `PluginTemplate` → `NomeTuoPlugin`
   - `girder-plugin-template` → `girder-nome-tuo-plugin`
   - `Plugin Template` → `Nome Tuo Plugin` (display name)
3. Aggiorna le dipendenze in `pyproject.toml`
4. Implementa la logica nel task Celery (`tasks.py`)
5. Adatta il worker Dockerfile se il tuo tool richiede un'immagine base diversa

## Avvio sviluppo

```bash
# Installa il plugin in modalità editable nel container Girder
docker compose exec girder pip install -e /path/to/my_plugin

# Builda il web client
cd girder_plugin_template/web_client
npm install
npm run build

# Avvia il worker
docker compose up -d plugin-template-worker
```

## Patterns chiave

### jobInfoSpec come header Celery (non kwargs)
Passare `jobInfoSpec` come header previene la creazione di job duplicati
da parte di `girder_before_task_publish`.

### --include nel comando celery worker
Oltre a `task_imports()` in `worker_entry.py`, aggiungere sempre
`--include=girder_plugin_template.tasks` al CMD del Dockerfile del worker
come fallback robusto.

### broker_heartbeat=0
Obbligatorio per task lunghi (> 60 s) con `--pool=solo`. Senza di esso
RabbitMQ chiude la connessione durante l'esecuzione e il task viene
ri-consegnato all'infinito.

### Idempotenza (acks_late)
Il task controlla lo stato del job all'inizio. Se è già in stato terminale
(SUCCESS/ERROR/CANCELLED) esce subito, evitando esecuzioni duplicate su
re-delivery.
