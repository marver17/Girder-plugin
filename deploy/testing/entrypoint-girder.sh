#!/bin/bash
# Entrypoint per il container Girder in modalità deploy (simil-produzione).
# Installa i plugin dal codice sorgente montato (senza editable mode),
# poi avvia il processo specificato come argomento.
#
# Uso:
#   entrypoint-girder.sh serve   → uvicorn girder.asgi:app
#   entrypoint-girder.sh worker  → celery worker (coda 'celery')

set -e

WORKSPACE=/workspace

# pip >= 25 ha rimosso --no-use-pep517; abilitalo solo se disponibile.
PIP_NO_PEP517_FLAG=""
if pip install --help 2>/dev/null | grep -q -- "--no-use-pep517"; then
    PIP_NO_PEP517_FLAG="--no-use-pep517"
fi

install_plugins() {
    echo "──── Installazione plugin Girder ────────────────────────────────"
    for plugin in \
        "$WORKSPACE/oauth2" \
        "$WORKSPACE/nifti_viewer" \
        "$WORKSPACE/diadema_pipeline"; do
        if [ -f "$plugin/pyproject.toml" ] || [ -f "$plugin/setup.py" ]; then
            # Evita conflitti setuptools su riavvii ripetuti (workspace montato).
            # Non fatale: un egg-info root-owned (creato da un worker) non deve
            # impedire l'avvio del container.
            rm -rf "$plugin/build" "$plugin"/*.egg-info 2>/dev/null || true
            echo "  pip install $plugin"
            pip install -q --no-build-isolation $PIP_NO_PEP517_FLAG \
                "$plugin"
        fi
    done
    echo "──── Plugin installati ──────────────────────────────────────────"
}

# Dopo la reinstallazione da /workspace il dist in site-packages è quello stale
# del repo. Ripristina il dist pre-compilato dal Dockerfile (in /plugins/)
# copiandolo su site-packages — scrivibile nel container senza problemi di permessi.
restore_built_frontends() {
    echo "──── Ripristino frontend pre-compilati ──────────────────────────"
    for plugin_name in nifti_viewer diadema_pipeline; do
        local pkg_mod="girder_${plugin_name}"
        local site_dir
        site_dir=$(python3 -c "import ${pkg_mod}; import os; print(os.path.dirname(${pkg_mod}.__file__))" 2>/dev/null)
        if [ -z "$site_dir" ]; then
            echo "  ⚠  ${plugin_name}: modulo non trovato, skip"
            continue
        fi

        local src_dist
        src_dist=$(find "/plugins/${plugin_name}" -path "*/web_client/dist" -type d 2>/dev/null | head -1)
        if [ -z "$src_dist" ]; then
            echo "  ⚠  ${plugin_name}: dist pre-compilato non trovato in /plugins, skip"
            continue
        fi

        echo "  ✓ ${plugin_name}: ripristino dist da /plugins"
        rm -rf "${site_dir}/web_client/dist"
        cp -r "$src_dist" "${site_dir}/web_client/dist"
    done
    echo "──── Frontend ripristinati ──────────────────────────────────────"
}

install_plugins
restore_built_frontends

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
        echo "=== Avvio Girder server (uvicorn / ASGI) ==="
        # Girder 5 espone l'app ASGI in girder.asgi:app e legge la connessione
        # MongoDB dalla variabile d'ambiente GIRDER_MONGO_URI (vedi compose).
        exec uvicorn girder.asgi:app --host 0.0.0.0 --port "${GIRDER_PORT:-8080}"
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
