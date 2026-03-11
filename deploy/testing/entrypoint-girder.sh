#!/bin/bash
# Entrypoint per il container Girder in modalità testing/produzione.
# Installa i plugin in editable mode dal codice sorgente montato,
# poi avvia il processo specificato come argomento.
#
# Uso:
#   entrypoint-girder.sh serve   → girder serve
#   entrypoint-girder.sh worker  → celery worker (coda 'celery')

set -e

WORKSPACE=/workspace

install_plugins() {
    echo "──── Installazione plugin Girder ────────────────────────────────"
    for plugin in \
        "$WORKSPACE/oauth2" \
        "$WORKSPACE/nifti_viewer" \
        "$WORKSPACE/nifti_qc" \
        "$WORKSPACE/diadema_pipeline"; do
        if [ -f "$plugin/pyproject.toml" ] || [ -f "$plugin/setup.py" ]; then
            echo "  pip install -e $plugin"
            pip install --break-system-packages -q --no-build-isolation \
                --no-deps -e "$plugin"
        fi
    done
    echo "──── Plugin installati ──────────────────────────────────────────"
}

install_plugins

case "${1:-serve}" in
    serve)
        echo "=== Avvio Girder server ==="
        exec girder serve --host 0.0.0.0 --database "$GIRDER_MONGO_URI"
        ;;
    worker)
        echo "=== Avvio Celery worker (coda: celery) ==="
        exec celery -A girder_worker.app worker \
            --loglevel=info \
            --pool=solo \
            --queues=celery \
            --concurrency=1 \
            --heartbeat-interval=0
        ;;
    *)
        exec "$@"
        ;;
esac
