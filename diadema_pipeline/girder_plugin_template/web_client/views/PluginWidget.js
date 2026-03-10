/**
 * Widget per il viewer NIfTI – Plugin Template
 * ──────────────────────────────────────────────────────────────────────────
 * Viene registrato con nifti_viewer tramite main.js.
 * Riceve i dati da widget_provider.py via item metadata.
 *
 * Il viewer chiama render(item, container) quando deve mostrare il widget.
 * ──────────────────────────────────────────────────────────────────────────
 */

import $ from 'jquery';

const PluginWidget = {
    /**
     * Crea e monta il widget nel container fornito dal viewer.
     *
     * @param {Backbone.Model} item      - Item Girder (Backbone model)
     * @param {jQuery}         $container - Container DOM in cui montare il widget
     */
    render(item, $container) {
        const results = item.get('plugin_template_results') || {};
        const status  = item.get('plugin_template_status')  || 'unknown';

        // ── Stato badge ───────────────────────────────────────────────────────
        const badgeClass = {
            completed: 'badge-success',
            error:     'badge-danger',
            running:   'badge-warning',
        }[status] || 'badge-secondary';

        // ── Render ────────────────────────────────────────────────────────────
        $container.html(`
            <div class="plugin-template-widget">
                <div class="g-widget-header">
                    <span class="badge ${badgeClass}">${status}</span>
                </div>

                <table class="table table-condensed table-striped g-metadata-table">
                    <thead>
                        <tr><th>Metrica</th><th>Valore</th></tr>
                    </thead>
                    <tbody>
                        ${_renderRows(results)}
                    </tbody>
                </table>

                ${!Object.keys(results).length ? '<p class="text-muted">Nessun risultato disponibile.</p>' : ''}
            </div>
        `);
    },
};

/**
 * Genera le righe della tabella dai risultati.
 * Personalizza questo helper per formattare i valori del tuo dominio.
 *
 * @param {Object} results
 * @returns {string} HTML delle righe <tr>
 */
function _renderRows(results) {
    return Object.entries(results)
        .map(([key, value]) => {
            const displayValue = typeof value === 'number'
                ? value.toFixed(4)
                : String(value);
            return `<tr><td>${key}</td><td>${_escape(displayValue)}</td></tr>`;
        })
        .join('');
}

/** Escape HTML per prevenire XSS */
function _escape(str) {
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

export default PluginWidget;
