/**
 * BatchLaunchDialog.js – Modale di lancio job DIADEMA (wizard a 2 step).
 *
 * Step 1  Selezione dei target (sessioni BIDS) con checkbox, shift-click per
 *         range, filtro e "seleziona tutto".
 * Step 2  Parametri comuni applicati a tutti i target selezionati + riepilogo.
 *
 * È l'unico punto di lancio dell'interfaccia: la stessa modale serve il batch
 * (N target, si parte dallo step 1) e la singola sessione (un target fissato,
 * si parte dallo step 2). Un solo componente = una sola resa dei parametri e
 * un solo posto in cui aggiungere un tool.
 *
 * Il lancio è una sola POST su `batch/run/:toolId` con l'array dei target nel
 * payload: nessun fan-out lato client.
 */

import $ from 'jquery';
import View from '@girder/core/views/View';
import events from '@girder/core/events';
import { restRequest } from '@girder/core/rest';

import { renderParamForm, collectParamValues, diffFromDefaults } from './paramForm';
import { badgeHtml, isPending } from './status';

const BatchLaunchDialog = View.extend({

    events: {
        'click .g-batch-next':      '_onNext',
        'click .g-batch-back':      '_onBack',
        'click .g-batch-launch':    '_onLaunch',
        'click .g-batch-check':     '_onCheck',
        'click .g-batch-check-all': '_onCheckAll',
        'input .g-batch-filter':    '_onFilter',
        'change .g-batch-hide-done': '_onFilter',
    },

    /**
     * @param {Object} settings
     * @param {Object} settings.tool          descrittore da views/tools/
     * @param {String} settings.rootFolderId  cartella radice (dataset o sub-XX)
     * @param {Array}  [settings.targets]     target già noti; se assenti si
     *                                        caricano da batch/targets
     * @param {Boolean} [settings.singleTarget] modalità sessione singola
     * @param {Object} [settings.presetParams]  valori iniziali del form
     */
    initialize(settings = {}) {
        this.tool = settings.tool;
        this.rootFolderId = settings.rootFolderId;
        this.singleTarget = !!settings.singleTarget;
        this.presetParams = settings.presetParams || {};
        this.targets = settings.targets || [];
        this.selected = new Set();
        // Indice dell'ultima checkbox toccata: ancora per lo shift-click.
        this._lastCheckedIndex = null;
        this.step = this.singleTarget ? 2 : 1;

        if (this.singleTarget) {
            this.targets.forEach(t => this.selected.add(t.folder_id));
        }
    },

    render() {
        this.$el.html(this._templateShell()).girderModal(this);
        if (this.step === 1 && !this.targets.length) {
            this._loadTargets();
        } else {
            this._renderStep();
        }
        return this;
    },

    // ── Caricamento target ────────────────────────────────────────────────────

    _loadTargets() {
        this.$('.g-batch-body').html(
            '<p class="text-muted" style="padding:20px;">Ricerca sessioni BIDS…</p>'
        );
        restRequest({
            method: 'GET',
            url: 'diadema_pipeline/batch/targets',
            data: { folderId: this.rootFolderId, toolId: this.tool.id },
        }).done((resp) => {
            this.targets = resp.targets || [];
            this.maxTargets = resp.max_targets;
            // Preselezione: tutto ciò che non ha già un job in volo. È il caso
            // d'uso normale (lanciare su tutto il dataset) e resta modificabile.
            this.targets.forEach(t => {
                if (!isPending(t.status)) this.selected.add(t.folder_id);
            });
            this._renderStep();
        }).fail((err) => {
            const msg = err?.responseJSON?.message || 'Errore nel caricamento delle sessioni';
            this.$('.g-batch-body').html(
                `<div class="alert alert-danger" style="margin:15px;">${msg}</div>`
            );
        });
    },

    // ── Rendering ─────────────────────────────────────────────────────────────

    _templateShell() {
        const title = this.singleTarget
            ? `Lancia ${this.tool.label}`
            : `Lancia ${this.tool.label} in batch`;
        return `
            <div class="modal-dialog modal-lg">
              <div class="modal-content">
                <div class="modal-header">
                  <button class="close" data-dismiss="modal" type="button">&times;</button>
                  <h4 class="modal-title">${title}</h4>
                  <div class="g-batch-steps text-muted" style="font-size:12px;margin-top:4px;"></div>
                </div>
                <div class="modal-body g-batch-body" style="max-height:60vh;overflow-y:auto;"></div>
                <div class="modal-footer g-batch-footer"></div>
              </div>
            </div>`;
    },

    _renderStep() {
        this.$('.g-batch-steps').html(
            this.singleTarget
                ? ''
                : `<b${this.step === 1 ? '' : ' class="text-muted"'}>1. Sessioni</b> ›
                   <b${this.step === 2 ? '' : ' class="text-muted"'}>2. Parametri</b>`
        );
        if (this.step === 1) {
            this.$('.g-batch-body').html(this._templateTargets());
            this.$('.g-batch-footer').html(`
                <span class="g-batch-count text-muted pull-left" style="line-height:32px;"></span>
                <button class="btn btn-default" data-dismiss="modal">Annulla</button>
                <button class="btn btn-primary g-batch-next">Avanti ›</button>`);
            this._syncSelectionUI();
        } else {
            this.$('.g-batch-body').html(this._templateParams());
            this.$('.g-batch-footer').html(`
                ${this.singleTarget ? '' : '<button class="btn btn-default g-batch-back pull-left">‹ Indietro</button>'}
                <button class="btn btn-default" data-dismiss="modal">Annulla</button>
                <button class="btn btn-success g-batch-launch">
                    <i class="icon-play"></i> Lancia${this.singleTarget ? '' : ` (${this.selected.size})`}
                </button>`);
        }
    },

    _templateTargets() {
        if (!this.targets.length) {
            return `<div class="alert alert-warning" style="margin:15px;">
                Nessuna sessione BIDS con file NIfTI trovata sotto questa cartella.
            </div>`;
        }
        const rows = this.targets.map((t, i) => {
            const pending = isPending(t.status);
            return `
                <tr class="g-batch-row" data-index="${i}"
                    data-search="${((t.subject_label || '') + ' ' + (t.session_label || '')).toLowerCase()}"
                    data-status="${t.status || ''}">
                  <td style="width:32px;">
                    <input type="checkbox" class="g-batch-check"
                           data-index="${i}" data-folder-id="${t.folder_id}"
                           ${this.selected.has(t.folder_id) ? 'checked' : ''}
                           ${pending ? 'disabled' : ''}>
                  </td>
                  <td>${t.subject_label || '<span class="text-muted">—</span>'}</td>
                  <td>${t.session_label || ''}</td>
                  <td class="text-muted">${t.nifti_count} file</td>
                  <td>${badgeHtml(t.status) || '<span class="text-muted">—</span>'}</td>
                </tr>`;
        }).join('');

        return `
            <div style="margin-bottom:10px;display:flex;gap:10px;align-items:center;">
              <input type="text" class="form-control input-sm g-batch-filter"
                     placeholder="Filtra per soggetto o sessione…" style="max-width:280px;">
              <label class="text-muted" style="font-weight:normal;margin:0;font-size:12px;">
                <input type="checkbox" class="g-batch-hide-done"> nascondi già completate
              </label>
            </div>
            <p class="text-muted" style="font-size:11px;">
              Suggerimento: tieni premuto <kbd>Shift</kbd> mentre selezioni per
              agire su un intervallo di righe.
            </p>
            <table class="table table-condensed table-hover" style="margin-bottom:0;">
              <thead>
                <tr>
                  <th style="width:32px;"><input type="checkbox" class="g-batch-check-all"></th>
                  <th>Soggetto</th><th>Sessione</th><th>Dati</th><th>Stato</th>
                </tr>
              </thead>
              <tbody>${rows}</tbody>
            </table>`;
    },

    _templateParams() {
        // In batch gli override per-file sono esclusi: un fileId non ha
        // significato applicato a N sessioni diverse (risoluzione BIDS lato task).
        const fields = renderParamForm(this.tool, {
            values: this.presetParams,
            excludePerSession: !this.singleTarget,
            idPrefix: 'g-batch-param',
        });

        const selectedList = this.targets
            .filter(t => this.selected.has(t.folder_id))
            .map(t => `<li>${t.path || t.session_label}</li>`)
            .join('');

        return `
            <form class="form-horizontal g-batch-params" onsubmit="return false;">
              ${fields}
              ${this.singleTarget ? '' : `
              <hr>
              <div class="form-group" style="margin-bottom:4px;">
                <div class="col-sm-4"></div>
                <div class="col-sm-8">
                  <div class="checkbox" style="margin:0;">
                    <label><input type="checkbox" class="g-batch-skip-completed" checked>
                      Salta le sessioni già completate</label>
                  </div>
                  <div class="checkbox" style="margin:0;">
                    <label><input type="checkbox" class="g-batch-force">
                      Forza la riesecuzione (ignora i job già presenti)</label>
                  </div>
                </div>
              </div>`}
            </form>
            <div class="well well-sm" style="margin-top:12px;font-size:12px;">
              <b>Riepilogo:</b> ${this.selected.size} session${this.selected.size === 1 ? 'e' : 'i'}
              · tool <b>${this.tool.label}</b>
              <ul style="max-height:110px;overflow-y:auto;margin:6px 0 0;padding-left:18px;">
                ${selectedList}
              </ul>
            </div>`;
    },

    // ── Selezione ─────────────────────────────────────────────────────────────

    _onCheck(e) {
        const $cb = $(e.currentTarget);
        const index = parseInt($cb.data('index'), 10);
        const checked = $cb.is(':checked');

        if (e.shiftKey && this._lastCheckedIndex !== null) {
            // Applica lo stato della checkbox cliccata all'intervallo, ma solo
            // sulle righe effettivamente visibili: con un filtro attivo un
            // range "logico" includerebbe righe che l'utente non sta vedendo.
            const [from, to] = [this._lastCheckedIndex, index].sort((a, b) => a - b);
            this.$('.g-batch-row:visible').each((_, row) => {
                const i = parseInt($(row).data('index'), 10);
                if (i < from || i > to) return;
                const $rowCb = $(row).find('.g-batch-check');
                if ($rowCb.is(':disabled')) return;
                $rowCb.prop('checked', checked);
                this._setSelected($rowCb.data('folder-id'), checked);
            });
        } else {
            this._setSelected($cb.data('folder-id'), checked);
        }

        this._lastCheckedIndex = index;
        this._syncSelectionUI();
    },

    _onCheckAll(e) {
        const checked = $(e.currentTarget).is(':checked');
        this.$('.g-batch-row:visible .g-batch-check:not(:disabled)').each((_, cb) => {
            const $cb = $(cb);
            $cb.prop('checked', checked);
            this._setSelected($cb.data('folder-id'), checked);
        });
        this._lastCheckedIndex = null;
        this._syncSelectionUI();
    },

    _setSelected(folderId, checked) {
        if (checked) this.selected.add(folderId);
        else this.selected.delete(folderId);
    },

    _onFilter() {
        const needle = (this.$('.g-batch-filter').val() || '').toLowerCase().trim();
        const hideDone = this.$('.g-batch-hide-done').is(':checked');
        this.$('.g-batch-row').each((_, row) => {
            const $row = $(row);
            const matches = !needle || ($row.data('search') || '').includes(needle);
            const done = $row.data('status') === 'completed';
            $row.toggle(matches && !(hideDone && done));
        });
        this._syncSelectionUI();
    },

    /** Contatore, stato del bottone Avanti e tri-state del "seleziona tutto". */
    _syncSelectionUI() {
        const n = this.selected.size;
        this.$('.g-batch-count').text(
            n ? `${n} session${n === 1 ? 'e selezionata' : 'i selezionate'}` : 'Nessuna sessione selezionata'
        );
        this.$('.g-batch-next').prop('disabled', n === 0);

        const $visible = this.$('.g-batch-row:visible .g-batch-check:not(:disabled)');
        const checkedCount = $visible.filter(':checked').length;
        const $all = this.$('.g-batch-check-all');
        $all.prop('checked', $visible.length > 0 && checkedCount === $visible.length);
        $all.prop('indeterminate', checkedCount > 0 && checkedCount < $visible.length);
    },

    // ── Navigazione wizard ────────────────────────────────────────────────────

    _onNext() {
        if (!this.selected.size) return;
        this.step = 2;
        this._renderStep();
    },

    _onBack() {
        this.step = 1;
        this._renderStep();
    },

    // ── Lancio ────────────────────────────────────────────────────────────────

    _onLaunch() {
        const params = collectParamValues(this.$('.g-batch-params'));
        const payload = {
            rootFolderId: this.rootFolderId,
            targets: this.targets
                .filter(t => this.selected.has(t.folder_id))
                .map(t => ({
                    folderId: t.folder_id,
                    subjectLabel: t.subject_label,
                    sessionLabel: t.session_label,
                    path: t.path,
                })),
            params,
            force: this.$('.g-batch-force').is(':checked'),
            skipCompleted: this.singleTarget
                ? false
                : this.$('.g-batch-skip-completed').is(':checked'),
        };

        const $btn = this.$('.g-batch-launch').prop('disabled', true).text('Invio in corso…');

        restRequest({
            method: 'POST',
            url: `diadema_pipeline/batch/run/${this.tool.id}`,
            contentType: 'application/json',
            data: JSON.stringify(payload),
            error: null,
        }).done((resp) => {
            this.trigger('g:batchLaunched', resp);
            if (resp.skipped || resp.failed) {
                // Non far sparire l'informazione in un alert a scomparsa: se
                // qualcosa non è partito l'utente deve poter leggere perché.
                this._renderDispatchReport(resp);
            } else {
                this.$el.modal('hide');
                events.trigger('g:alert', {
                    icon: 'ok', type: 'success', timeout: 4000,
                    text: `${resp.queued} job accodati per ${this.tool.label}`,
                });
            }
        }).fail((err) => {
            $btn.prop('disabled', false).html('<i class="icon-play"></i> Lancia');
            events.trigger('g:alert', {
                icon: 'cancel', type: 'danger', timeout: 6000,
                text: err?.responseJSON?.message || 'Errore nel lancio del batch',
            });
        });
    },

    /** Esito del dispatch quando non tutti i target sono partiti. */
    _renderDispatchReport(resp) {
        const rows = (resp.targets || [])
            .filter(t => t.dispatch !== 'queued')
            .map(t => `<tr>
                <td>${t.path || t.sessionLabel || t.folderId}</td>
                <td>${badgeHtml(t.dispatch)}</td>
                <td class="text-muted">${t.message || ''}</td>
            </tr>`).join('');

        this.$('.g-batch-body').html(`
            <div class="alert alert-info">
              <b>${resp.queued}</b> job accodati.
              ${resp.skipped ? `<b>${resp.skipped}</b> saltati. ` : ''}
              ${resp.failed ? `<b>${resp.failed}</b> falliti.` : ''}
            </div>
            <table class="table table-condensed">
              <thead><tr><th>Sessione</th><th>Esito</th><th>Motivo</th></tr></thead>
              <tbody>${rows}</tbody>
            </table>`);
        this.$('.g-batch-footer').html(
            '<button class="btn btn-primary" data-dismiss="modal">Chiudi</button>'
        );
    },
});

export default BatchLaunchDialog;
