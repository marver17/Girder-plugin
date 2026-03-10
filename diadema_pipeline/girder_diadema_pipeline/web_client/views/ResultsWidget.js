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
 *   diadema_freesurfer_results → { volumes: {...}, ... }
 *   diadema_lstai_results     → { lesion_count, total_volume_ml, ... }
 */

import View from '@girder/core/views/View';

// Badge status → classe Bootstrap
const STATUS_LABELS = {
    completed:  { cls: 'success', text: 'Completed' },
    processing: { cls: 'warning', text: 'Processing' },
    running:    { cls: 'warning', text: 'Running' },
    queued:     { cls: 'info',    text: 'Queued' },
    error:      { cls: 'danger',  text: 'Error' },
};

const DiademaResultsWidget = View.extend({
    className: 'g-diadema-results-widget',

    initialize(settings) {
        this.item         = settings.item;
        this.parentView   = settings.parentView;
        this.widgetConfig = settings.widgetConfig;
    },

    fetchData() {
        const mriqcResults      = this.item.get('diadema_mriqc_results');
        const mriqcStatus       = this.item.get('diadema_mriqc_status');
        const fsResults         = this.item.get('diadema_freesurfer_results');
        const fsStatus          = this.item.get('diadema_freesurfer_status');
        const lstaiResults      = this.item.get('diadema_lstai_results');
        const lstaiStatus       = this.item.get('diadema_lstai_status');

        const hasData = mriqcResults || fsResults || lstaiResults;
        if (!hasData) {
            return Promise.reject(new Error('Nessun risultato DIADEMA disponibile'));
        }

        return Promise.resolve({ mriqcResults, mriqcStatus, fsResults, fsStatus, lstaiResults, lstaiStatus });
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

        // Metriche chiave MRIQC da mostrare in tabella
        const KEY_METRICS = [
            { key: 'snr_total', label: 'SNR',          decimals: 2 },
            { key: 'cnr',       label: 'CNR',          decimals: 2 },
            { key: 'fwhm_avg',  label: 'FWHM avg',     decimals: 2, unit: 'mm' },
            { key: 'efc',       label: 'EFC',          decimals: 3 },
            { key: 'fber',      label: 'FBER',         decimals: 2 },
            { key: 'qi_1',      label: 'QI-1',         decimals: 3 },
            { key: 'qi_2',      label: 'QI-2',         decimals: 3 },
            { key: 'inu_range', label: 'INU range',    decimals: 3 },
            { key: 'wm2max',    label: 'WM-to-max',    decimals: 3 },
        ];

        const rows = KEY_METRICS
            .filter(m => metrics[m.key] !== undefined)
            .map(m => {
                const val = typeof metrics[m.key] === 'number'
                    ? metrics[m.key].toFixed(m.decimals)
                    : metrics[m.key];
                const unit = m.unit ? ` <small>${m.unit}</small>` : '';
                return `<tr><td>${m.label}</td><td>${val}${unit}</td></tr>`;
            })
            .join('');

        const quickCheck = results.quick_check;
        const qcRows = quickCheck ? this._quickCheckRows(quickCheck) : '';

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
        const volumes = results.volumes || {};

        // Strutture principali da mostrare
        const KEY_STRUCTS = [
            { key: 'Left-Hippocampus',   label: 'Ippocampo (sx)' },
            { key: 'Right-Hippocampus',  label: 'Ippocampo (dx)' },
            { key: 'Left-Amygdala',      label: 'Amigdala (sx)' },
            { key: 'Right-Amygdala',     label: 'Amigdala (dx)' },
            { key: 'Left-Thalamus-Proper', label: 'Talamo (sx)' },
            { key: 'Right-Thalamus-Proper', label: 'Talamo (dx)' },
            { key: 'BrainSegVol',        label: 'Volume segm. totale' },
            { key: 'EstimatedTotalIntraCranialVol', label: 'eTIV' },
        ];

        const rows = KEY_STRUCTS
            .filter(s => volumes[s.key] !== undefined)
            .map(s => `<tr><td>${s.label}</td><td>${Number(volumes[s.key]).toFixed(0)} mm³</td></tr>`)
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
