#!/bin/bash
# Build del frontend per tutti i plugin con web_client.
# Da eseguire UNA VOLTA prima di docker compose up (o dopo modifiche ai file JS).
#
# Uso: bash build-frontend.sh
#      bash build-frontend.sh diadema_pipeline   (solo un plugin)

set -e

WORKSPACE="$(cd "$(dirname "$0")/../.." && pwd)"

PLUGINS=(
    "nifti_viewer"
    "nifti_qc"
    "diadema_pipeline"
)

build_plugin() {
    local plugin="$1"
    local web_dir="$WORKSPACE/$plugin/girder_$(echo "$plugin" | tr '-' '_')/web_client"

    # Cerca la web_client anche con nomi leggermente diversi
    if [ ! -d "$web_dir" ]; then
        web_dir=$(find "$WORKSPACE/$plugin" -maxdepth 2 -name "web_client" -type d | head -1)
    fi

    if [ -z "$web_dir" ] || [ ! -f "$web_dir/package.json" ]; then
        echo "  ⚠  $plugin: nessuna web_client trovata, skip"
        return
    fi

    echo "──── Build $plugin ──────────────────────────────────────────────"
    echo "     $web_dir"
    cd "$web_dir"
    npm install --silent
    npm run build
    echo "  ✓  $plugin OK"
}

if [ -n "$1" ]; then
    build_plugin "$1"
else
    for plugin in "${PLUGINS[@]}"; do
        build_plugin "$plugin"
    done
fi

echo ""
echo "✓ Build frontend completata."
