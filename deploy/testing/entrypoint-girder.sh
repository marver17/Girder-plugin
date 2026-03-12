#!/bin/bash
# Entrypoint per il container Girder in modalità deploy (simil-produzione).
# Installa i plugin dal codice sorgente montato (senza editable mode),
# poi avvia il processo specificato come argomento.
#
# Uso:
#   entrypoint-girder.sh serve   → girder serve
#   entrypoint-girder.sh worker  → celery worker (coda 'celery')

set -e

WORKSPACE=/workspace

install_plugins() {
    echo "──── Rimozione plugin non desiderati ───────────────────────────"
    pip uninstall --break-system-packages -q -y girder-nifti-qc 2>/dev/null || true
    echo "──── Installazione plugin Girder ────────────────────────────────"
    for plugin in \
        "$WORKSPACE/oauth2" \
        "$WORKSPACE/nifti_viewer" \
        "$WORKSPACE/diadema_pipeline"; do
        if [ -f "$plugin/pyproject.toml" ] || [ -f "$plugin/setup.py" ]; then
            echo "  pip install $plugin"
            pip install --break-system-packages -q --no-build-isolation \
                "$plugin"
        fi
    done
    echo "──── Plugin installati ──────────────────────────────────────────"
}

install_plugins

run_bootstrap() {
    echo "──── Bootstrap Girder (settings / users / assetstore) ──────────"
    python3 /workspace/deploy/testing/bootstrap_girder.py
    local rc=$?
    if [ $rc -ne 0 ]; then
        echo "Bootstrap Girder fallito (exit $rc) – abort" >&2
        exit $rc
    fi
    echo "──── Bootstrap completato ──────────────────────────────────────"
}

case "${1:-serve}" in
    serve)
        run_bootstrap
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
