/**
 * BatchPanel.js – Pannello DIADEMA a livello dataset / soggetto.
 *
 * Si monta sulla radice di un dataset BIDS o su una cartella sub-XX, dove il
 * pannello di sessione non compare. Resta volutamente compatto: intestazione,
 * conteggio sessioni, riepilogo stato per tool e un bottone per tool che apre
 * la modale di lancio (BatchLaunchDialog). La tabella dei target vive nella
 * modale, non qui: su un dataset da 80 sessioni schiaccerebbe la pagina.
 *
 * Quando un batch è attivo il pannello ospita il BatchMonitor.
 */

import $ from 'jquery';
import View from '@girder/core/views/View';
import { restRequest } from '@girder/core/rest';

import MriqcTool      from './tools/mriqc';
import FreesurferTool from './tools/freesurfer';
import LstaiTool      from './tools/lstai';

import BatchLaunchDialog from './BatchLaunchDialog';
import BatchMonitor from './BatchMonitor';
import { isPending } from './status';

const TOOLS = [MriqcTool, FreesurferTool, LstaiTool];

// Chiave localStorage con cui riagganciare il monitor dopo un reload: è
// l'equivalente batch di DiademaPanel._resumeActiveJobs.
const lastBatchKey = (rootFolderId) => `diadema.batch.${rootFolderId}`;

const BatchPanel = View.extend({

    className: 'g-diadema-panel g-diadema-batch-panel panel panel-default',

    events: {
        'click .g-batch-launch-tool': '_onLaunchTool',
    },

    initialize(settings = {}) {
        this.rootFolderId = settings.rootFolderId;
        this.rootFolderName = settings.rootFolderName || '';
        this.targetsByTool = {};   // toolId → array target (cache per la modale)
        this.monitor = null;
        this.$el.attr('data-diadema-mode', 'batch');
        this.$el.data('diadema-id', this.rootFolderId);
    },

    render() {
        this.$el.html(`
            <div class="panel-heading" style="font-weight:600;">
              DIADEMA – analisi batch
              <small class="text-muted" style="font-weight:normal;">
                ${this.rootFolderName}
              </small>
            </div>
            <div class="panel-body">
              <div class="g-batch-summary text-muted">Ricerca sessioni BIDS…</div>
              <div class="g-batch-monitor-slot" style="margin-top:12px;"></div>
            </div>`);
        this._loadSummary();
        this._resumeLastBatch();
        return this;
    },

    remove() {
        if (this.monitor) this.monitor.remove();
        return View.prototype.remove.apply(this, arguments);
    },

    // ── Riepilogo ─────────────────────────────────────────────────────────────

    /**
     * Carica i target una volta per tool. La stessa risposta alimenta sia il
     * riepilogo sia la modale, così aprire il wizard non rifà la scansione.
     */
    _loadSummary() {
        const requests = TOOLS.map(tool =>
            restRequest({
                method: 'GET',
                url: 'diadema_pipeline/batch/targets',
                data: { folderId: this.rootFolderId, toolId: tool.id },
                error: null,
            }).then((resp) => {
                this.targetsByTool[tool.id] = resp.targets || [];
                return resp;
            }).catch(() => {
                this.targetsByTool[tool.id] = [];
                return null;
            })
        );

        $.when(...requests).always(() => this._renderSummary());
    },

    _renderSummary() {
        const anyTargets = TOOLS.some(t => (this.targetsByTool[t.id] || []).length);
        if (!anyTargets) {
            this.$('.g-batch-summary').html(
                '<span class="text-muted">Nessuna sessione BIDS con file NIfTI sotto questa cartella.</span>'
            );
            return;
        }

        const rows = TOOLS.map(tool => {
            const targets = this.targetsByTool[tool.id] || [];
            const done = targets.filter(t => t.status === 'completed').length;
            const active = targets.filter(t => isPending(t.status)).length;
            const todo = targets.length - done - active;

            return `
                <tr>
                  <td style="font-weight:600;">${tool.label}</td>
                  <td class="text-muted">
                    ${done} completate · ${active} in corso · ${todo} da fare
                    <span class="text-muted">(su ${targets.length})</span>
                  </td>
                  <td style="text-align:right;">
                    <button class="btn btn-sm btn-primary g-batch-launch-tool"
                            data-tool-id="${tool.id}"
                            ${targets.length ? '' : 'disabled'}>
                      Lancia in batch…
                    </button>
                  </td>
                </tr>`;
        }).join('');

        this.$('.g-batch-summary').html(
            `<table class="table table-condensed" style="margin-bottom:0;"><tbody>${rows}</tbody></table>`
        );
    },

    // ── Lancio ────────────────────────────────────────────────────────────────

    _onLaunchTool(e) {
        const toolId = $(e.currentTarget).data('tool-id');
        const tool = TOOLS.find(t => t.id === toolId);
        if (!tool) return;

        const dialog = new BatchLaunchDialog({
            el: $('#g-dialog-container'),
            parentView: this,
            tool,
            rootFolderId: this.rootFolderId,
            targets: this.targetsByTool[toolId] || [],
        });
        dialog.on('g:batchLaunched', (resp) => {
            this._rememberBatch(resp.batch_id);
            this._mountMonitor(resp.batch_id);
        });
        dialog.render();
    },

    // ── Monitor ───────────────────────────────────────────────────────────────

    _mountMonitor(batchId) {
        if (this.monitor) this.monitor.remove();
        // Il monitor vive in un div creato ogni volta: passargli direttamente
        // lo slot significherebbe che il suo remove() cancella l'ancora, e il
        // mount successivo non troverebbe più dove attaccarsi.
        const $host = $('<div>').appendTo(this.$('.g-batch-monitor-slot').empty());
        this.monitor = new BatchMonitor({
            el: $host,
            parentView: this,
            batchId,
            // A batch concluso i conteggi del riepilogo sono obsoleti.
            onDone: () => this._loadSummary(),
        });
        this.monitor.render().start();
    },

    _rememberBatch(batchId) {
        try {
            window.localStorage.setItem(lastBatchKey(this.rootFolderId), batchId);
        } catch (err) {
            // localStorage può essere disabilitato: la persistenza è un extra,
            // non deve impedire il monitoraggio nella sessione corrente.
        }
    },

    /** Riaggancia il monitor dell'ultimo batch lanciato su questa cartella. */
    _resumeLastBatch() {
        let batchId = null;
        try {
            batchId = window.localStorage.getItem(lastBatchKey(this.rootFolderId));
        } catch (err) {
            return;
        }
        if (batchId) this._mountMonitor(batchId);
    },
});

export default BatchPanel;
