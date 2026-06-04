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

# pip >= 25 ha rimosso --no-use-pep517; abilitalo solo se disponibile.
PIP_NO_PEP517_FLAG=""
if pip install --help 2>/dev/null | grep -q -- "--no-use-pep517"; then
    PIP_NO_PEP517_FLAG="--no-use-pep517"
fi

install_plugins() {
    echo "──── Rimozione plugin non desiderati ───────────────────────────"
    pip uninstall --break-system-packages -q -y girder-nifti-qc 2>/dev/null || true
    echo "──── Installazione plugin Girder ────────────────────────────────"
    for plugin in \
        "$WORKSPACE/oauth2" \
        "$WORKSPACE/nifti_viewer" \
        "$WORKSPACE/diadema_pipeline"; do
        if [ -f "$plugin/pyproject.toml" ] || [ -f "$plugin/setup.py" ]; then
            # Evita conflitti setuptools su riavvii ripetuti (workspace montato)
            rm -rf "$plugin/build" "$plugin"/*.egg-info
            echo "  pip install $plugin"
            pip install --break-system-packages -q --no-build-isolation $PIP_NO_PEP517_FLAG \
                "$plugin"
        fi
    done
    echo "──── Plugin installati ──────────────────────────────────────────"
}

# Compila il frontend JS di un plugin se i sorgenti sono più recenti del bundle.
# Salta silenziosamente se il plugin non ha web_client o se npm non è disponibile.
build_frontend_if_needed() {
    local plugin_dir="$1"
    local web_dir

    # Cerca la web_client (schema: plugin/girder_plugin/web_client)
    web_dir=$(find "$plugin_dir" -maxdepth 2 -name "web_client" -type d 2>/dev/null | head -1)
    [ -z "$web_dir" ] || [ ! -f "$web_dir/package.json" ] && return 0

    local dist_file
    dist_file=$(find "$web_dir/dist" -name "*.umd.cjs" 2>/dev/null | head -1)

    # Rebuild se: dist non esiste, OPPURE qualche sorgente JS è più recente del bundle
    local needs_build=0
    if [ -z "$dist_file" ]; then
        needs_build=1
    elif find "$web_dir" \
            \( -name "*.js" -o -name "*.ts" -o -name "*.vue" \) \
            -newer "$dist_file" \
            -not -path "*/dist/*" \
            -not -path "*/node_modules/*" \
            2>/dev/null | grep -q .; then
        needs_build=1
    fi

    if [ "$needs_build" -eq 0 ]; then
        echo "  ✓ Frontend $(basename "$plugin_dir") già aggiornato, skip"
        return 0
    fi

    echo "  Building frontend $(basename "$plugin_dir")..."
    cd "$web_dir"
    npm install --silent 2>/dev/null
    npm run build 2>/dev/null
    echo "  ✓ Frontend $(basename "$plugin_dir") compilato"
}

build_frontends() {
    echo "──── Build frontend plugin ──────────────────────────────────────"
    for plugin in \
        "$WORKSPACE/nifti_viewer" \
        "$WORKSPACE/diadema_pipeline"; do
        build_frontend_if_needed "$plugin"
    done
    echo "──── Frontend aggiornati ────────────────────────────────────────"
}

install_plugins
build_frontends

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
