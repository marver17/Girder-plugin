/**
 * Estensione della Item View di Girder
 * ──────────────────────────────────────────────────────────────────────────
 * Aggiunge un bottone "Run Plugin Template" nella vista dell'item.
 * Viene chiamato da main.js tramite wrap() sul metodo render di ItemView.
 * ──────────────────────────────────────────────────────────────────────────
 */

import $ from 'jquery';
import { restRequest } from '@girder/core/rest';

const ItemViewExtension = {
    /**
     * Aggiunge il bottone "Run Plugin Template" alla item view.
     *
     * @param {ItemView} view - L'istanza della ItemView Girder
     */
    addRunButton(view) {
        const item = view.model;
        if (!item) return;

        // Trova il container dei bottoni nella item view
        // (il selettore dipende dalla versione di Girder — adattalo se necessario)
        const $actionsEl = view.$('.g-item-actions, .g-item-header-actions').first();
        if (!$actionsEl.length) return;

        const $btn = $(`
            <button class="btn btn-sm btn-default g-plugin-template-run-btn"
                    title="Run Plugin Template">
                <i class="icon-cog"></i> Plugin Template
            </button>
        `);

        $btn.on('click', async () => {
            $btn.prop('disabled', true).html('<i class="icon-spin3 animate-spin"></i> In coda...');

            try {
                const result = await restRequest({
                    method: 'POST',
                    url: `plugin_template/${item.id}/run`,
                });
                $btn.html('<i class="icon-ok"></i> In coda')
                    .removeClass('btn-default')
                    .addClass('btn-success');
                console.log('[plugin_template] Task avviato:', result);
            } catch (err) {
                $btn.prop('disabled', false)
                    .html('<i class="icon-attention"></i> Errore')
                    .removeClass('btn-default')
                    .addClass('btn-danger');
                console.error('[plugin_template] Errore avvio task:', err);
            }
        });

        $actionsEl.append($btn);
    },
};

export default ItemViewExtension;
