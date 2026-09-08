/**
 * BatchMonitor.js – Avanzamento di una coda batch DIADEMA.
 *
 * Mostra una barra globale e una riga per soggetto, alimentate da un unico
 * polling su `batch/:id/status` (una GET per ciclo invece di N).
 *
 * Il polling qui è deliberatamente più difensivo di quello storico di
 * DiademaPanel._pollForResults, i cui limiti noti sono:
 *   - nessun handler d'errore: un 502 transitorio interrompeva il loop e la UI
 *     restava ferma senza dirlo;
 *   - timer mai cancellato: la view veniva rimossa ma il timer continuava;
 *   - nessun registro: più mount dello stesso pannello accumulavano loop.
 * Qui: backoff sugli errori, timer cancellato in destroy(), registro globale.
 */

import View from '@girder/core/views/View';
import events from '@girder/core/events';
import { restRequest } from '@girder/core/rest';

import { badgeHtml, isPending } from './status';

const POLL_INTERVAL_MS = 6000;
const POLL_BACKOFF_MAX_MS = 30000;

// Un solo loop di polling per batch, indipendentemente da quante volte il
// pannello viene montato durante la navigazione.
const _activePolls = {};

const BatchMonitor = View.extend({

    className: 'g-diadema-batch-monitor',

    events: {
        'click .g-batch-cancel-all': '_onCancelAll',
        'click .g-batch-refresh':    '_poll',
    },

    /**
     * @param {String} settings.batchId
     * @param {Function} [settings.onDone] callback a batch concluso
     */
    initialize(settings = {}) {
        this.batchId = settings.batchId;
        this.onDone = settings.onDone;
        this.data = null;
        this._timer = null;
        this._interval = POLL_INTERVAL_MS;
    },

    render() {
        this.$el.html(this.data
            ? this._template()
            : '<p class="text-muted">Caricamento stato batch…</p>');
        return this;
    },

    start() {
        if (_activePolls[this.batchId]) {
            // Un altro monitor sta già seguendo questo batch: non raddoppiare
            // le richieste, il refresh manuale resta disponibile.
            this._poll();
            return this;
        }
        _activePolls[this.batchId] = true;
        this._poll();
        return this;
    },

    /** Backbone chiama destroy()/remove() allo smontaggio: fermiamo il timer. */
    destroy() {
        this._stopPolling();
        return View.prototype.destroy.apply(this, arguments);
    },

    remove() {
        this._stopPolling();
        return View.prototype.remove.apply(this, arguments);
    },

    _stopPolling() {
        if (this._timer) {
            clearTimeout(this._timer);
            this._timer = null;
        }
        delete _activePolls[this.batchId];
    },

    _schedule() {
        this._timer = setTimeout(() => this._poll(), this._interval);
    },

    _poll() {
        restRequest({
            method: 'GET',
            url: `diadema_pipeline/batch/${this.batchId}/status`,
            error: null,
        }).done((resp) => {
            this._interval = POLL_INTERVAL_MS;   // reset del backoff
            this.data = resp;
            this.render();
            if (resp.done) {
                this._stopPolling();
                if (this.onDone) this.onDone(resp);
            } else {
                this._schedule();
            }
        }).fail((err) => {
            if (err && err.status === 404) {
                // Batch cancellato: non ha senso continuare a chiedere.
                this._stopPolling();
                return;
            }
            // Errore transitorio: rallenta ma non interrompere il monitoraggio.
            this._interval = Math.min(this._interval * 2, POLL_BACKOFF_MAX_MS);
            this.$('.g-batch-poll-warning').remove();
            this.$el.prepend(
                '<div class="g-batch-poll-warning text-muted" style="font-size:11px;">'
                + 'Stato non raggiungibile, nuovo tentativo…</div>'
            );
            this._schedule();
        });
    },

    // ── Rendering ─────────────────────────────────────────────────────────────

    _template() {
        const d = this.data;
        const s = d.summary || {};
        const total = s.total || 0;
        const finished = (s.completed || 0) + (s.error || 0)
            + (s.cancelled || 0) + (s.skipped || 0) + (s.failed || 0);
        const pct = total ? Math.round((finished / total) * 100) : 0;
        const hasActive = (d.targets || []).some(t => isPending(t.status));

        return `
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">
              <b style="font-size:13px;">Batch ${d.tool}</b>
              <span class="text-muted" style="font-size:12px;">
                ${finished}/${total} completati
              </span>
              <span style="margin-left:auto;">
                <button class="btn btn-xs btn-default g-batch-refresh" title="Aggiorna">
                  <i class="icon-arrows-cw"></i>
                </button>
                ${hasActive ? `<button class="btn btn-xs btn-danger g-batch-cancel-all">
                  Annulla batch</button>` : ''}
              </span>
            </div>

            <div class="progress" style="height:14px;margin-bottom:8px;">
              <div class="progress-bar ${s.error ? 'progress-bar-warning' : 'progress-bar-success'}"
                   style="width:${pct}%;" role="progressbar">${pct}%</div>
            </div>

            <div style="font-size:11px;margin-bottom:8px;">
              ${this._summaryChips(s)}
            </div>

            <table class="table table-condensed" style="font-size:12px;margin-bottom:0;">
              <thead><tr>
                <th>Soggetto</th><th>Sessione</th><th>Stato</th><th>Avanzamento</th>
              </tr></thead>
              <tbody>${(d.targets || []).map(t => this._rowTemplate(t)).join('')}</tbody>
            </table>`;
    },

    _summaryChips(summary) {
        return Object.keys(summary)
            .filter(k => k !== 'total' && summary[k])
            .map(k => `${badgeHtml(k) || k} ${summary[k]}`)
            .join(' &nbsp; ');
    },

    _rowTemplate(t) {
        let progress = '<span class="text-muted">—</span>';
        if (t.progress && t.progress.total) {
            const pct = Math.round((t.progress.current / t.progress.total) * 100);
            progress = `<div style="min-width:120px;">
                <div class="progress" style="height:8px;margin:0 0 2px;">
                  <div class="progress-bar" style="width:${pct}%;"></div>
                </div>
                <small class="text-muted">${t.progress.message || ''}</small>
              </div>`;
        } else if (t.message) {
            progress = `<small class="text-muted">${t.message}</small>`;
        }

        const label = t.sessionLabel || t.folderId;
        return `<tr>
            <td>${t.subjectLabel || '<span class="text-muted">—</span>'}</td>
            <td><a href="#folder/${t.folderId}">${label}</a></td>
            <td>${badgeHtml(t.status) || t.status || ''}</td>
            <td>${progress}</td>
          </tr>`;
    },

    // ── Azioni ────────────────────────────────────────────────────────────────

    _onCancelAll() {
        if (!window.confirm(
            'Annullare tutti i job ancora attivi di questo batch?'
        )) return;

        restRequest({
            method: 'POST',
            url: `diadema_pipeline/batch/${this.batchId}/cancel`,
            error: null,
        }).done((resp) => {
            events.trigger('g:alert', {
                icon: 'ok', type: 'info', timeout: 4000,
                text: `${resp.cancelled} job annullati (${resp.skipped} non attivi)`,
            });
            this._poll();
        }).fail((err) => {
            events.trigger('g:alert', {
                icon: 'cancel', type: 'danger', timeout: 5000,
                text: err?.responseJSON?.message || 'Errore nell\'annullamento',
            });
        });
    },
});

export default BatchMonitor;
