/**
 * ConfigView.js – Pagina di configurazione admin DIADEMA Pipeline
 *
 * Accessibile da: Amministrazione → Plugin → DIADEMA Pipeline → Configure
 *
 * Sezioni:
 *   1. Storage – dove salvare i risultati (item Girder vs derivatives BIDS)
 *   2. Directory – percorsi per ogni worker
 *   3. Widget – visibilità per tool e campi da mostrare
 */

import $ from 'jquery';
import { restRequest } from '@girder/core/rest';
import events from '@girder/core/events';
import View from '@girder/core/views/View';
import PluginConfigBreadcrumbWidget from '@girder/core/views/widgets/PluginConfigBreadcrumbWidget';

// ── Catalogo completo dei campi disponibili ────────────────────────────────────

const MRIQC_FIELDS_ALL = [
    { key: 'snr_total',   label: 'SNR (total)' },
    { key: 'snr_wm',      label: 'SNR (white matter)' },
    { key: 'snr_gm',      label: 'SNR (gray matter)' },
    { key: 'cnr',         label: 'CNR' },
    { key: 'cjv',         label: 'CJV' },
    { key: 'fwhm_avg',    label: 'FWHM (avg)' },
    { key: 'efc',         label: 'EFC' },
    { key: 'fber',        label: 'FBER' },
    { key: 'wm2max',      label: 'WM2MAX' },
    { key: 'inu_range',   label: 'INU range' },
    { key: 'qi_1',        label: 'QI1' },
    { key: 'qi_2',        label: 'QI2' },
    { key: 'tsnr',        label: 'tSNR' },
    { key: 'fd_mean',     label: 'FD (mean)' },
    { key: 'fd_perc',     label: 'FD (%) >0.2mm' },
    { key: 'gsr_x',       label: 'GSR x' },
    { key: 'gsr_y',       label: 'GSR y' },
    { key: 'dvars_nstd',  label: 'DVARS (nstd)' },
    { key: 'aor',         label: 'AOR' },
];

const FS_FIELDS_ALL = [
    { key: 'Left-Hippocampus',                 label: 'Hippocampus (L)' },
    { key: 'Right-Hippocampus',                label: 'Hippocampus (R)' },
    { key: 'Left-Amygdala',                    label: 'Amygdala (L)' },
    { key: 'Right-Amygdala',                   label: 'Amygdala (R)' },
    { key: 'Left-Thalamus-Proper',             label: 'Thalamus (L)' },
    { key: 'Right-Thalamus-Proper',            label: 'Thalamus (R)' },
    { key: 'Left-Caudate',                     label: 'Caudate (L)' },
    { key: 'Right-Caudate',                    label: 'Caudate (R)' },
    { key: 'Left-Putamen',                     label: 'Putamen (L)' },
    { key: 'Right-Putamen',                    label: 'Putamen (R)' },
    { key: 'Left-Pallidum',                    label: 'Pallidum (L)' },
    { key: 'Right-Pallidum',                   label: 'Pallidum (R)' },
    { key: 'Left-Lateral-Ventricle',           label: 'Lateral Ventricle (L)' },
    { key: 'Right-Lateral-Ventricle',          label: 'Lateral Ventricle (R)' },
    { key: 'BrainSegVol',                      label: 'Brain Seg. Volume' },
    { key: 'EstimatedTotalIntraCranialVol',    label: 'eTIV' },
];

// ── Template HTML ──────────────────────────────────────────────────────────────

function _renderCheckboxList(items, selectedKeys, prefix) {
    return items.map(({ key, label }) => {
        const checked = selectedKeys.includes(key) ? 'checked' : '';
        return `
        <div class="checkbox">
          <label>
            <input type="checkbox" class="g-diadema-field-check"
                   data-prefix="${prefix}" value="${key}" ${checked}>
            ${label}
          </label>
        </div>`;
    }).join('');
}

function buildTemplate(settings) {
    const storage = settings['diadema.output_storage'] || 'item';
    const mriqcDir = settings['diadema.mriqc_output_dir'] || '';
    const subjectsDir = settings['diadema.subjects_dir'] || '';
    const lstaiDir = settings['diadema.lstai_output_dir'] || '';
    const widgetEnabled = settings['diadema.widget_enabled'] || {};
    const fieldsMriqc = settings['diadema.widget_fields_mriqc'] || [];
    const fieldsFs = settings['diadema.widget_fields_freesurfer'] || [];

    const mriqcChecked = widgetEnabled.mriqc !== false ? 'checked' : '';
    const fsChecked = widgetEnabled.freesurfer !== false ? 'checked' : '';
    const lstaiChecked = widgetEnabled.lstai ? 'checked' : '';

    return `
<div class="g-config-breadcrumb-container"></div>

<div class="g-diadema-config-body">

  <h4>DIADEMA Pipeline — Configurazione</h4>
  <p class="text-muted">
    Queste impostazioni sono globali per tutti gli utenti dell'istanza.
  </p>

  <!-- ── 1. Storage ──────────────────────────────────────────────────── -->
  <div class="panel panel-default">
    <div class="panel-heading"><strong>Storage risultati</strong></div>
    <div class="panel-body">
      <p class="text-muted">
        Scegli dove vengono salvati i risultati di ogni analisi.
      </p>

      <div class="radio">
        <label>
          <input type="radio" name="g-diadema-storage" value="item"
                 ${storage === 'item' ? 'checked' : ''}>
          <strong>Item Girder</strong> — metadati e file allegati direttamente all'item
          <small class="text-muted">(default, compatibile con versioni precedenti)</small>
        </label>
      </div>
      <div class="radio">
        <label>
          <input type="radio" name="g-diadema-storage" value="derivatives"
                 ${storage === 'derivatives' ? 'checked' : ''}>
          <strong>Derivatives BIDS</strong> — cartella <code>derivatives/</code>
          sul filesystem del worker
        </label>
      </div>
    </div>
  </div>

  <!-- ── 2. Directory worker ─────────────────────────────────────────── -->
  <div class="panel panel-default">
    <div class="panel-heading"><strong>Directory worker</strong></div>
    <div class="panel-body">
      <p class="text-muted">
        Lascia vuoto per usare la variabile d'ambiente del container
        (<code>DIADEMA_MRIQC_OUTPUT_DIR</code>, <code>DIADEMA_SUBJECTS_DIR</code>, ecc.)
        o il percorso di default.
      </p>

      <div class="form-group">
        <label>MRIQC output directory</label>
        <input id="g-diadema-mriqc-dir" type="text"
               class="form-control input-sm" placeholder="/data/diadema/mriqc"
               value="${_escAttr(mriqcDir)}">
        <small class="text-muted">
          Corrisponde all'env var <code>DIADEMA_MRIQC_OUTPUT_DIR</code> nel container worker.
        </small>
      </div>

      <div class="form-group">
        <label>FreeSurfer subjects directory</label>
        <input id="g-diadema-subjects-dir" type="text"
               class="form-control input-sm" placeholder="/data/diadema/subjects"
               value="${_escAttr(subjectsDir)}">
        <small class="text-muted">
          Corrisponde all'env var <code>DIADEMA_SUBJECTS_DIR</code> nel container worker.
        </small>
      </div>

      <div class="form-group">
        <label>LST-AI output directory</label>
        <input id="g-diadema-lstai-dir" type="text"
               class="form-control input-sm" placeholder="/data/diadema/lstai"
               value="${_escAttr(lstaiDir)}">
      </div>
    </div>
  </div>

  <!-- ── 3. Widget ───────────────────────────────────────────────────── -->
  <div class="panel panel-default">
    <div class="panel-heading"><strong>Widget risultati</strong></div>
    <div class="panel-body">

      <p class="text-muted">
        Controlla quali tool vengono mostrati nel widget del viewer NIfTI
        e quali parametri vengono visualizzati.
      </p>

      <!-- MRI QC -->
      <div class="panel panel-default">
        <div class="panel-heading" data-toggle="collapse" data-target="#g-diadema-mriqc-section"
             style="cursor:pointer">
          <strong>
            <input type="checkbox" class="g-diadema-tool-check"
                   id="g-diadema-mriqc-enabled" data-tool="mriqc" ${mriqcChecked}>
            &nbsp;MRI QC (MRIQC)
          </strong>
          <small class="text-muted pull-right">▾ campi</small>
        </div>
        <div id="g-diadema-mriqc-section" class="collapse in panel-body">
          <p class="text-muted small">
            Seleziona i parametri IQM da mostrare nel widget.
          </p>
          <div class="row">
            <div class="col-sm-6">
              ${_renderCheckboxList(MRIQC_FIELDS_ALL.slice(0, Math.ceil(MRIQC_FIELDS_ALL.length / 2)), fieldsMriqc, 'mriqc')}
            </div>
            <div class="col-sm-6">
              ${_renderCheckboxList(MRIQC_FIELDS_ALL.slice(Math.ceil(MRIQC_FIELDS_ALL.length / 2)), fieldsMriqc, 'mriqc')}
            </div>
          </div>
        </div>
      </div>

      <!-- FreeSurfer -->
      <div class="panel panel-default">
        <div class="panel-heading" data-toggle="collapse" data-target="#g-diadema-fs-section"
             style="cursor:pointer">
          <strong>
            <input type="checkbox" class="g-diadema-tool-check"
                   id="g-diadema-fs-enabled" data-tool="freesurfer" ${fsChecked}>
            &nbsp;FreeSurfer (recon-all)
          </strong>
          <small class="text-muted pull-right">▾ strutture</small>
        </div>
        <div id="g-diadema-fs-section" class="collapse in panel-body">
          <p class="text-muted small">
            Seleziona le strutture anatomiche da mostrare nel widget.
          </p>
          <div class="row">
            <div class="col-sm-6">
              ${_renderCheckboxList(FS_FIELDS_ALL.slice(0, Math.ceil(FS_FIELDS_ALL.length / 2)), fieldsFs, 'freesurfer')}
            </div>
            <div class="col-sm-6">
              ${_renderCheckboxList(FS_FIELDS_ALL.slice(Math.ceil(FS_FIELDS_ALL.length / 2)), fieldsFs, 'freesurfer')}
            </div>
          </div>
        </div>
      </div>

      <!-- LST-AI -->
      <div class="panel panel-default">
        <div class="panel-heading">
          <strong>
            <input type="checkbox" class="g-diadema-tool-check"
                   id="g-diadema-lstai-enabled" data-tool="lstai" ${lstaiChecked}>
            &nbsp;LST-AI
          </strong>
          <span class="label label-warning" style="margin-left:8px">Non disponibile</span>
        </div>
      </div>

    </div>
  </div>

  <!-- ── Azioni ───────────────────────────────────────────────────────── -->
  <div class="g-diadema-config-actions">
    <button class="btn btn-primary" id="g-diadema-save">
      <i class="icon-ok"></i> Salva configurazione
    </button>
    <span id="g-diadema-save-msg" style="margin-left:12px"></span>
  </div>

</div>
`;
}

function _escAttr(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

// ── ConfigView ─────────────────────────────────────────────────────────────────

var ConfigView = View.extend({

    events: {
        'click #g-diadema-save': '_onSave',
        // Impedisce che il click sulla checkbox propaghi alla heading Bootstrap
        // (che ha data-toggle="collapse" e collasserebbe il panel)
        'click .g-diadema-tool-check': function (e) { e.stopPropagation(); },
    },

    initialize: function (settings) {
        this._settings = {};
        this._loadSettings();
    },

    _loadSettings: function () {
        restRequest({
            method: 'GET',
            url: 'diadema_pipeline/settings',
        }).done((resp) => {
            this._settings = resp;
            this.render();
        }).fail((err) => {
            events.trigger('g:alert', {
                icon: 'cancel',
                text: 'Impossibile caricare le impostazioni DIADEMA: ' +
                      (err.responseJSON?.message || err.statusText),
                type: 'danger',
                timeout: 6000,
            });
        });
    },

    render: function () {
        this.$el.html(buildTemplate(this._settings));

        new PluginConfigBreadcrumbWidget({
            pluginName: 'DIADEMA Pipeline',
            el: this.$('.g-config-breadcrumb-container'),
            parentView: this,
        }).render();

        return this;
    },

    _collectSettings: function () {
        const storage = this.$('input[name="g-diadema-storage"]:checked').val();

        const widgetEnabled = {
            mriqc:      this.$('#g-diadema-mriqc-enabled').is(':checked'),
            freesurfer: this.$('#g-diadema-fs-enabled').is(':checked'),
            lstai:      this.$('#g-diadema-lstai-enabled').is(':checked'),
        };

        const fieldsMriqc = [];
        const fieldsFs = [];
        this.$('.g-diadema-field-check').each(function () {
            if ($(this).is(':checked')) {
                const prefix = $(this).data('prefix');
                if (prefix === 'mriqc') fieldsMriqc.push($(this).val());
                else if (prefix === 'freesurfer') fieldsFs.push($(this).val());
            }
        });

        return {
            'diadema.output_storage':          storage,
            'diadema.mriqc_output_dir':        this.$('#g-diadema-mriqc-dir').val().trim(),
            'diadema.subjects_dir':            this.$('#g-diadema-subjects-dir').val().trim(),
            'diadema.lstai_output_dir':        this.$('#g-diadema-lstai-dir').val().trim(),
            'diadema.widget_enabled':          widgetEnabled,
            'diadema.widget_fields_mriqc':     fieldsMriqc,
            'diadema.widget_fields_freesurfer': fieldsFs,
        };
    },

    _onSave: function () {
        const $btn = this.$('#g-diadema-save');
        const $msg = this.$('#g-diadema-save-msg');
        $btn.prop('disabled', true);
        $msg.html('<span class="text-muted">Salvataggio...</span>');

        const payload = this._collectSettings();

        restRequest({
            method: 'PUT',
            url: 'diadema_pipeline/settings',
            contentType: 'application/json',
            data: JSON.stringify(payload),
        }).done(() => {
            $btn.prop('disabled', false);
            $msg.html(
                '<span class="text-success"><i class="icon-ok"></i> Salvato con successo</span>'
            );
            events.trigger('g:alert', {
                icon: 'ok',
                text: 'Configurazione DIADEMA salvata.',
                type: 'success',
                timeout: 3000,
            });
            this._settings = payload;
            setTimeout(() => $msg.html(''), 4000);
        }).fail((err) => {
            $btn.prop('disabled', false);
            const msg = err.responseJSON?.message || err.statusText || 'Errore sconosciuto';
            $msg.html(`<span class="text-danger"><i class="icon-cancel"></i> ${_escAttr(msg)}</span>`);
        });
    },
});

export default ConfigView;
