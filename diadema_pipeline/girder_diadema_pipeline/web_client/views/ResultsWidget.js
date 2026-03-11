/**
 * ResultsWidget.js – Widget nifti_viewer per DIADEMA Pipeline
 *
 * Mostra i risultati dei tool DIADEMA nel pannello del viewer NIfTI.
 * Registrato in main.js con nifti_viewer tramite doppio meccanismo
 * (immediato + event).
 *
 * Struttura dati attesa sull'item:
 *   diadema_mriqc_results     → { metrics: {...}, modality, mriqc_version, ... }
 *   diadema_mriqc_status      → 'completed' | 'error' | 'processing'
 *   diadema_freesurfer_results → { stats: { subcortical: {...}, global: {...}, cortical: {...} }, ... }
 *   diadema_lstai_results     → { lesion_count, total_volume_ml, ... }
 */

import { restRequest } from '@girder/core/rest';
import View from '@girder/core/views/View';

// ── Etichette per chiavi metriche ────────────────────────────────────────────
const MRIQC_LABELS = {
    snr_total: 'SNR (total)',    snr_wm: 'SNR (WM)',     snr_gm: 'SNR (GM)',
    cnr:       'CNR',           cjv:    'CJV',          fwhm_avg: 'FWHM avg',
    efc:       'EFC',           fber:   'FBER',         wm2max: 'WM2MAX',
    inu_range: 'INU range',     qi_1:   'QI-1',         qi_2: 'QI-2',
    tsnr:      'tSNR',          fd_mean: 'FD (mean)',   fd_perc: 'FD % >0.2mm',
    gsr_x:     'GSR x',         gsr_y:  'GSR y',        dvars_nstd: 'DVARS (nstd)',
    aor:       'AOR',
};
const FS_LABELS = {
    'Left-Hippocampus':                'Ippocampo (sx)',
    'Right-Hippocampus':               'Ippocampo (dx)',
    'Left-Amygdala':                   'Amigdala (sx)',
    'Right-Amygdala':                  'Amigdala (dx)',
    'Left-Thalamus-Proper':            'Talamo (sx)',
    'Right-Thalamus-Proper':           'Talamo (dx)',
    'Left-Caudate':                    'Caudato (sx)',
    'Right-Caudate':                   'Caudato (dx)',
    'Left-Putamen':                    'Putamen (sx)',
    'Right-Putamen':                   'Putamen (dx)',
    'Left-Pallidum':                   'Pallidum (sx)',
    'Right-Pallidum':                  'Pallidum (dx)',
    'Left-Lateral-Ventricle':          'Ventricolo lat. (sx)',
    'Right-Lateral-Ventricle':         'Ventricolo lat. (dx)',
    'BrainSegVol':                     'Vol. segm. cerebrale',
    'EstimatedTotalIntraCranialVol':   'eTIV',
};

// Badge status → classe Bootstrap
const STATUS_LABELS = {
    completed:  { cls: 'success', text: 'Completed' },
    uploading:  { cls: 'info',    text: 'Uploading' },
    processing: { cls: 'warning', text: 'Processing' },
    running:    { cls: 'warning', text: 'Running' },
    queued:     { cls: 'info',    text: 'Queued' },
    error:      { cls: 'danger',  text: 'Error' },
    cancelled:  { cls: 'default', text: 'Cancelled' },
    not_implemented: { cls: 'muted', text: 'Not available' },
};

const DiademaResultsWidget = View.extend({
    className: 'g-diadema-results-widget',

    initialize(settings) {
        this.item         = settings.item;
        this.parentView   = settings.parentView;
        this.widgetConfig = settings.widgetConfig;
    },

    fetchData() {
        // Legge le settings admin per sapere quali campi mostrare,
        // poi combina con i dati in item.meta.
        const meta = this.item.get('meta') || {};

        return restRequest({
            method: 'GET',
            url: 'diadema_pipeline/settings',
            error: null,
        }).then((settings) => {
            const enabled     = settings['diadema.widget_enabled']          || {};
            const fieldsMriqc = settings['diadema.widget_fields_mriqc']     || [];
            const fieldsFs    = settings['diadema.widget_fields_freesurfer'] || [];

            // ── MRIQC ──────────────────────────────────────────────────────
            let mriqcResults = meta.diadema_mriqc_results || null;
            if (mriqcResults && fieldsMriqc.length && mriqcResults.metrics) {
                const filtered = {};
                fieldsMriqc.forEach(k => {
                    if (mriqcResults.metrics[k] !== undefined) filtered[k] = mriqcResults.metrics[k];
                });
                mriqcResults = { ...mriqcResults, metrics: filtered };
            }

            // ── FreeSurfer ─────────────────────────────────────────────────
            let fsResults = meta.diadema_freesurfer_results || null;
            if (fsResults && fieldsFs.length && fsResults.stats) {
                const s = fsResults.stats;
                const filtSub  = {};
                const filtGlob = {};
                fieldsFs.forEach(k => {
                    if (s.subcortical?.[k] !== undefined) filtSub[k]  = s.subcortical[k];
                    if (s.global?.[k]      !== undefined) filtGlob[k] = s.global[k];
                });
                fsResults = { ...fsResults, stats: { ...s, subcortical: filtSub, global: filtGlob } };
            }

            return {
                enabled,
                mriqcResults:  enabled.mriqc      !== false ? mriqcResults : null,
                mriqcStatus:   meta.diadema_mriqc_status,
                fsResults:     enabled.freesurfer  !== false ? fsResults    : null,
                fsStatus:      meta.diadema_freesurfer_status,
                lstaiResults:  enabled.lstai       ? meta.diadema_lstai_results  : null,
                lstaiStatus:   meta.diadema_lstai_status,
            };
        }).catch(() => {
            // Settings non accessibili (utente non admin): mostra tutto senza filtro
            return {
                mriqcResults:  meta.diadema_mriqc_results,
                mriqcStatus:   meta.diadema_mriqc_status,
                fsResults:     meta.diadema_freesurfer_results,
                fsStatus:      meta.diadema_freesurfer_status,
                lstaiResults:  meta.diadema_lstai_results,
                lstaiStatus:   meta.diadema_lstai_status,
            };
        });
    },

    render() {
        this.$el.html('<div class="g-widget-loading"><i class="icon-spin4 animate-spin"></i> Caricamento…</div>');
        this.fetchData()
            .then(data => this._renderContent(data))
            .catch(err => this._renderEmpty(err));
        return this;
    },

    _renderContent(data) {
        let html = '<div class="g-diadema-results">';

        if (data.mriqcResults) {
            html += this._renderMriqcSection(data.mriqcResults, data.mriqcStatus);
        }
        if (data.fsResults) {
            html += this._renderFreesurferSection(data.fsResults, data.fsStatus);
        }
        if (data.lstaiResults) {
            html += this._renderLstaiSection(data.lstaiResults, data.lstaiStatus);
        }

        html += '</div>';
        this.$el.html(html);
    },

    // ── MRI QC ────────────────────────────────────────────────────────────────

    _renderMriqcSection(results, status) {
        const badge = this._statusBadge(status);
        const metrics = results.metrics || {};

        // Le metriche sono già filtrate dal server (widget_provider.py).
        // MRIQC_LABELS fornisce etichette leggibili; per chiavi sconosciute
        // si usa la chiave originale come fallback.
        const rows = Object.entries(metrics)
            .map(([key, val]) => {
                const label = MRIQC_LABELS[key] || key;
                const display = typeof val === 'number' ? val.toFixed(4).replace(/\.?0+$/, '') : val;
                return `<tr><td>${label}</td><td>${display}</td></tr>`;
            })
            .join('');

        const quickCheck = results.quick_check;
        const qcRows = quickCheck ? this._quickCheckRows(quickCheck) : '';;

        return `
            <div class="g-diadema-section" style="margin-bottom: 14px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <strong><i class="icon-chart-bar"></i> MRI QC</strong>
                    ${badge}
                </div>
                ${results.modality ? `<p style="margin: 0 0 6px; font-size: 12px; color: #666;">Modalità: <strong>${results.modality}</strong></p>` : ''}

                ${qcRows ? `
                    <table class="table table-condensed table-striped" style="font-size: 12px; margin-bottom: 6px;">
                        <thead><tr><th>Check</th><th>Valore</th></tr></thead>
                        <tbody>${qcRows}</tbody>
                    </table>` : ''}

                ${rows ? `
                    <details style="margin-top: 4px;">
                        <summary style="cursor: pointer; font-size: 12px; color: #555;">
                            Metriche MRIQC (${Object.keys(metrics).length})
                        </summary>
                        <table class="table table-condensed table-striped" style="font-size: 12px; margin-top: 6px;">
                            <thead><tr><th>Metrica</th><th>Valore</th></tr></thead>
                            <tbody>${rows}</tbody>
                        </table>
                    </details>` : ''}

                ${results.mriqc_version
                    ? `<small class="text-muted" style="font-size: 11px;">MRIQC ${results.mriqc_version}</small>`
                    : ''}
                ${results.timestamp ? `<br><small class="text-muted" style="font-size: 11px;">${new Date(results.timestamp).toLocaleString()}</small>` : ''}
            </div>`;
    },

    _quickCheckRows(qc) {
        let rows = '';
        if (qc.shape)
            rows += `<tr><td>Shape</td><td>${qc.shape.join(' × ')}</td></tr>`;
        if (qc.voxel_size_mm || qc.voxel_size) {
            const v = (qc.voxel_size_mm || qc.voxel_size).map(x => x.toFixed(2)).join(' × ');
            rows += `<tr><td>Voxel size</td><td>${v} mm</td></tr>`;
        }
        if (qc.orientation) {
            const o = Array.isArray(qc.orientation) ? qc.orientation.join('') : qc.orientation;
            rows += `<tr><td>Orientamento</td><td>${o}</td></tr>`;
        }
        if (qc.data_range) {
            const dr = qc.data_range;
            rows += `<tr><td>Min / Max</td><td>${dr.min.toFixed(2)} / ${dr.max.toFixed(2)}</td></tr>`;
            rows += `<tr><td>Media ± Std</td><td>${dr.mean.toFixed(2)} ± ${dr.std.toFixed(2)}</td></tr>`;
        }
        return rows;
    },

    // ── FreeSurfer ────────────────────────────────────────────────────────────

    _renderFreesurferSection(results, status) {
        const badge = this._statusBadge(status);
        // Dati prodotti dal task: results.stats.subcortical + results.stats.global
        const stats = results.stats || {};
        const volumes = { ...(stats.subcortical || {}), ...(stats.global || {}) };

        // I volumi sono già filtrati dal server (widget_provider.py).
        // FS_LABELS fornisce etichette leggibili; fallback sulla chiave originale.
        const rows = Object.entries(volumes)
            .map(([key, vol]) => {
                const label = FS_LABELS[key] || key;
                return `<tr><td>${label}</td><td>${Number(vol).toFixed(0)} mm³</td></tr>`;
            })
            .join('');

        return `
            <div class="g-diadema-section" style="margin-bottom: 14px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <strong><i class="icon-cog"></i> FreeSurfer</strong>
                    ${badge}
                </div>
                ${results.directive ? `<p style="margin: 0 0 6px; font-size: 12px; color: #666;">Direttiva: <strong>${results.directive}</strong></p>` : ''}

                ${rows ? `
                    <table class="table table-condensed table-striped" style="font-size: 12px;">
                        <thead><tr><th>Struttura</th><th>Volume</th></tr></thead>
                        <tbody>${rows}</tbody>
                    </table>` : '<p class="text-muted" style="font-size:12px;">Volumi non disponibili.</p>'}

                ${results.freesurfer_version
                    ? `<small class="text-muted" style="font-size:11px;">FreeSurfer ${results.freesurfer_version}</small>`
                    : ''}
            </div>`;
    },

    // ── LST-AI ────────────────────────────────────────────────────────────────

    _renderLstaiSection(results, status) {
        const badge = this._statusBadge(status);

        const rows = [
            results.lesion_count    !== undefined ? `<tr><td>Numero lesioni</td><td>${results.lesion_count}</td></tr>` : '',
            results.total_volume_ml !== undefined ? `<tr><td>Volume totale</td><td>${Number(results.total_volume_ml).toFixed(2)} mL</td></tr>` : '',
            results.input_type      !== undefined ? `<tr><td>Input type</td><td>${results.input_type}</td></tr>` : '',
            results.threshold       !== undefined ? `<tr><td>Soglia</td><td>${results.threshold}</td></tr>` : '',
        ].filter(Boolean).join('');

        return `
            <div class="g-diadema-section" style="margin-bottom: 14px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <strong><i class="icon-search"></i> LST-AI</strong>
                    ${badge}
                </div>

                ${rows ? `
                    <table class="table table-condensed table-striped" style="font-size: 12px;">
                        <tbody>${rows}</tbody>
                    </table>` : '<p class="text-muted" style="font-size:12px;">Risultati non disponibili.</p>'}

                ${results.lst_version
                    ? `<small class="text-muted" style="font-size:11px;">LST-AI ${results.lst_version}</small>`
                    : ''}
            </div>`;
    },

    // ── Helpers ───────────────────────────────────────────────────────────────

    _statusBadge(status) {
        if (!status) return '';
        const info = STATUS_LABELS[status] || { cls: 'default', text: status };
        return `<span class="label label-${info.cls}" style="font-size:11px;">${info.text}</span>`;
    },

    _renderEmpty(err) {
        this.$el.html(`
            <div class="alert alert-info" style="font-size:13px; margin:0;">
                <i class="icon-info-circled"></i>
                ${err.message}
            </div>
        `);
    },
});

export default DiademaResultsWidget;
