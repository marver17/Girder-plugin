/**
 * DiademaPanel.js – Pannello principale DIADEMA Pipeline
 *
 * Aggiunge nell'item view di Girder:
 *   - Radio list verticale con i 3 tool (MRI QC / FreeSurfer / LST-AI)
 *   - Bottoni condivisi "Run" e "Advanced ⚙"
 *   - Sezione accordion collassabile con il form parametri del tool selezionato
 *   - Badge di stato inline per ogni tool con risultati
 *   - Polling automatico dopo il submit
 */

import $ from 'jquery';
import { restRequest } from '@girder/core/rest';
import events from '@girder/core/events';

import MriqcTool     from './tools/mriqc';
import FreesurferTool from './tools/freesurfer';
import LstaiTool     from './tools/lstai';

const TOOLS = [MriqcTool, FreesurferTool, LstaiTool];

// ── Mappa id → status text e classe Bootstrap ─────────────────────────────────
const STATUS_CLASSES = {
    completed:  { cls: 'success', text: '✓' },
    processing: { cls: 'warning', text: '…' },
    running:    { cls: 'warning', text: '…' },
    queued:     { cls: 'info',    text: '⏳' },
    error:      { cls: 'danger',  text: '✗' },
};

// ─────────────────────────────────────────────────────────────────────────────

const DiademaPanel = {

    /**
     * Entry point: chiamato da main.js dopo il render della ItemView.
     * @param {ItemView} itemView - Istanza della Girder ItemView
     */
    addPanel(itemView) {
        const item = itemView.model;
        if (!item) return;

        // Evita double-mount su re-render
        if (itemView.$('.g-diadema-panel').length) {
            DiademaPanel._refreshBadges(itemView);
            return;
        }

        const $panel = DiademaPanel._buildPanel(itemView);
        // Inserisci il pannello dopo .g-item-info (stessa posizione dei bottoni nifti_qc)
        const $anchor = itemView.$('.g-item-info');
        if ($anchor.length) {
            $anchor.after($panel);
        } else {
            itemView.$el.find('.g-item-header, .panel-body').first().append($panel);
        }

        DiademaPanel._bindEvents(itemView, $panel);
        DiademaPanel._refreshBadges(itemView);
        DiademaPanel._resumeActiveJobs(itemView, $panel);
    },

    // ── Helper: legge stato e risultati di un tool dall'item model ────────────

    _getToolMeta(itemModel, tool) {
        const item = itemModel.toJSON ? itemModel.toJSON() : itemModel;
        const toolData = (item.diadema || {})[tool.id] || {};
        return {
            status:  toolData.status  || null,
            results: toolData.results || null,
        };
    },

    // ── Riprende il polling per i job attivi al (ri)caricamento della pagina ──

    _resumeActiveJobs(itemView, $panel) {
        const ACTIVE = ['running', 'queued', 'processing'];
        TOOLS.forEach(tool => {
            const { status } = DiademaPanel._getToolMeta(itemView.model, tool);
            if (ACTIVE.includes(status)) {
                DiademaPanel._pollForResults(itemView, $panel, itemView.model.id, tool.id, 8000);
            }
        });
        // Aggiorna subito lo stato del bottone per il tool selezionato
        DiademaPanel._updateRunButtonState(itemView, $panel);
    },

    // ── Aggiorna il bottone Run in base allo stato del tool selezionato ───────

    _updateRunButtonState(itemView, $panel) {
        const ACTIVE = ['running', 'queued', 'processing'];
        const tool = DiademaPanel._getSelectedTool($panel);
        const { status } = DiademaPanel._getToolMeta(itemView.model, tool);
        const $btn = $panel.find('.g-diadema-run-btn');
        if (ACTIVE.includes(status)) {
            $btn.prop('disabled', true).html('<i class="icon-spin3 animate-spin"></i> In corso…');
        } else {
            $btn.prop('disabled', false).html('<i class="icon-play"></i> Run');
        }
    },

    // ── Costruisce il DOM del pannello ────────────────────────────────────────

    _buildPanel(itemView) {
        const $panel = $(`
            <div class="g-diadema-panel" style="margin: 15px 0; border: 1px solid #e0e0e0; border-radius: 4px; padding: 14px; background: #fafafa;">
                <div class="g-diadema-header" style="margin-bottom: 12px;">
                    <h4 style="margin: 0 0 4px 0; font-size: 14px; font-weight: 600; color: #333;">
                        <i class="icon-sitemap" style="margin-right: 6px; color: #5b9bd5;"></i>
                        DIADEMA Pipeline
                    </h4>
                    <small class="text-muted">Seleziona un tool e premi Run</small>
                </div>

                <div class="g-diadema-tool-list" style="margin-bottom: 12px;">
                    ${TOOLS.map((tool, i) => DiademaPanel._buildToolRadioHTML(tool, i === 0)).join('')}
                </div>

                <div class="g-diadema-actions" style="display: flex; gap: 8px; align-items: center;">
                    <button class="btn btn-sm btn-primary g-diadema-run-btn" style="min-width: 80px;">
                        <i class="icon-play"></i> Run
                    </button>
                    <button class="btn btn-sm btn-default g-diadema-advanced-btn" title="Mostra/nascondi parametri avanzati">
                        <i class="icon-cog"></i> Advanced <span class="g-diadema-chevron">▾</span>
                    </button>
                </div>

                <div class="g-diadema-advanced-panel" style="display: none; margin-top: 12px; padding: 12px; background: #fff; border: 1px solid #ddd; border-radius: 4px;">
                    <div class="g-diadema-params-form"></div>
                </div>
            </div>
        `);

        return $panel;
    },

    _buildToolRadioHTML(tool, checked) {
        return `
            <div class="g-diadema-tool-item" style="margin-bottom: 6px; padding: 8px; border-radius: 4px; cursor: pointer; transition: background 0.15s;"
                 data-tool-id="${tool.id}">
                <label style="display: flex; align-items: flex-start; gap: 10px; cursor: pointer; margin: 0; font-weight: normal;">
                    <input type="radio" name="diadema-tool" value="${tool.id}"
                           ${checked ? 'checked' : ''}
                           style="margin-top: 3px; flex-shrink: 0;">
                    <span style="font-size: 16px; color: #5b9bd5; flex-shrink: 0;">
                        <i class="${tool.icon}"></i>
                    </span>
                    <span style="flex: 1; min-width: 0;">
                        <span style="font-weight: 600; display: block; color: #333;">${tool.label}</span>
                        <small class="text-muted">${tool.description}</small>
                    </span>
                    <span class="g-diadema-tool-badge" data-tool="${tool.id}"
                          style="flex-shrink: 0; align-self: center;"></span>
                </label>
            </div>
        `;
    },

    // ── Binding eventi ────────────────────────────────────────────────────────

    _bindEvents(itemView, $panel) {
        const item = itemView.model;

        // Evidenzia la riga selezionata
        $panel.on('change', 'input[name="diadema-tool"]', function () {
            $panel.find('.g-diadema-tool-item').css('background', '');
            $panel.find(`.g-diadema-tool-item[data-tool-id="${this.value}"]`).css('background', '#eef4fb');

            // Se il pannello Advanced è aperto, aggiorna il form
            if ($panel.find('.g-diadema-advanced-panel').is(':visible')) {
                DiademaPanel._renderParamForm(itemView, $panel, DiademaPanel._getSelectedTool($panel));
            }

            // Aggiorna lo stato del bottone Run per il tool appena selezionato
            DiademaPanel._updateRunButtonState(itemView, $panel);
        });

        // Highlight iniziale del primo radio
        $panel.find('.g-diadema-tool-item[data-tool-id="mriqc"]').css('background', '#eef4fb');

        // Clic sulla riga intera → seleziona il radio
        $panel.on('click', '.g-diadema-tool-item', function (e) {
            if (!$(e.target).is('input')) {
                $(this).find('input[type="radio"]').prop('checked', true).trigger('change');
            }
        });

        // Toggle Advanced
        $panel.find('.g-diadema-advanced-btn').on('click', () => {
            const $adv = $panel.find('.g-diadema-advanced-panel');
            const isOpen = $adv.is(':visible');
            if (isOpen) {
                $adv.slideUp(150);
                $panel.find('.g-diadema-chevron').text('▾');
            } else {
                const tool = DiademaPanel._getSelectedTool($panel);
                DiademaPanel._renderParamForm(itemView, $panel, tool);
                $adv.slideDown(200);
                $panel.find('.g-diadema-chevron').text('▴');
            }
        });

        // Run
        $panel.find('.g-diadema-run-btn').on('click', () => {
            DiademaPanel._onRun(itemView, $panel);
        });
    },

    // ── Selezione tool corrente ────────────────────────────────────────────────

    _getSelectedTool($panel) {
        const toolId = $panel.find('input[name="diadema-tool"]:checked').val() || 'mriqc';
        return TOOLS.find(t => t.id === toolId) || TOOLS[0];
    },

    // ── Rendering form parametri (accordion) ──────────────────────────────────

    _renderParamForm(itemView, $panel, tool) {
        const $form = $panel.find('.g-diadema-params-form');
        const autoValues = tool.id === 'mriqc'
            ? DiademaPanel._inferMRIQCParams(itemView.model)
            : {};

        const fields = tool.params.map(param => {
            const value = autoValues[param.name] !== undefined ? autoValues[param.name] : param.default;
            return DiademaPanel._buildParamFieldHTML(param, value);
        }).join('');

        // Banner preview percorso derivatives (solo MRIQC)
        const derivativesPreview = (tool.id === 'mriqc') ? `
            <div class="g-diadema-derivatives-preview" style="
                margin-top: 12px; padding: 8px 10px; border-radius: 4px;
                background: #f0f4fa; border: 1px solid #c5d6ee; font-size: 11px;">
                <div style="font-weight: 600; color: #3a6ea5; margin-bottom: 4px;">
                    <i class="icon-folder"></i> Output derivatives BIDS
                </div>
                <div class="g-deriv-path-text" style="color: #555; word-break: break-all;">
                    <i class="icon-spin3 animate-spin"></i> Calcolo percorso…
                </div>
                <div class="g-deriv-warning" style="color: #a05000; margin-top: 4px; display: none;">
                    <i class="icon-warning"></i> <span></span>
                </div>
            </div>` : '';

        $form.html(`
            <div style="padding-bottom: 4px; margin-bottom: 10px; border-bottom: 1px solid #eee;">
                <strong style="font-size: 13px; color: #555;">
                    <i class="${tool.icon}"></i> ${tool.label} – Parametri
                </strong>
                ${tool.workerNote ? `<br><small class="text-muted" style="font-size: 11px;">🐳 ${tool.workerNote}</small>` : ''}
            </div>
            <div class="form-horizontal" style="font-size: 13px;">
                ${fields}
            </div>
            ${derivativesPreview}
        `);

        // Preview iniziale e aggiornamento live su modifica del campo
        if (tool.id === 'mriqc') {
            DiademaPanel._refreshDerivativesPreview(itemView, $form, '');

            $form.on('input change', '[data-param="derivativesRootId"]', function () {
                DiademaPanel._refreshDerivativesPreview(itemView, $form, $(this).val().trim());
            });
        }
    },

    _refreshDerivativesPreview(itemView, $form, overrideId) {
        const itemId = itemView.model.id;
        const $pathText = $form.find('.g-deriv-path-text');
        const $warning  = $form.find('.g-deriv-warning');

        $pathText.html('<i class="icon-spin3 animate-spin"></i> Calcolo percorso…');
        $warning.hide();

        const data = {};
        if (overrideId) data.overrideId = overrideId;

        restRequest({
            method: 'GET',
            url: `diadema_pipeline/${itemId}/derivatives_root`,
            data,
            error: null,
        }).then((resp) => {
            if (!resp.resolved) {
                $pathText.html(`<span style="color:#c00;"><i class="icon-cancel"></i> ${resp.error || 'Errore'}</span>`);
                return;
            }
            const sourceLabel = resp.source === 'override'
                ? '<span style="color:#2a7a2a;">[override]</span>'
                : resp.source === 'fallback_collection'
                    ? '<span style="color:#a05000;">[fallback collection]</span>'
                    : '<span style="color:#2a5a99;">[auto]</span>';
            $pathText.html(`
                ${sourceLabel}
                <code style="font-size: 11px; background: none; padding: 0; color: #2a5a99;">
                    ${resp.derivatives_path}
                </code>
            `);
            if (resp.warning) {
                $warning.find('span').text(resp.warning);
                $warning.show();
            } else {
                $warning.hide();
            }
        }).catch(() => {
            $pathText.html('<span style="color:#999;">Anteprima non disponibile</span>');
        });
    },

    _buildParamFieldHTML(param, currentValue) {
        const id = `g-diadema-param-${param.name}`;
        let inputHtml = '';

        if (param.type === 'select') {
            const opts = param.options.map(opt =>
                `<option value="${opt.value}" ${opt.value === currentValue ? 'selected' : ''}>${opt.label}</option>`
            ).join('');
            inputHtml = `<select class="form-control input-sm" id="${id}" data-param="${param.name}">${opts}</select>`;

        } else if (param.type === 'checkbox') {
            inputHtml = `
                <div class="checkbox" style="margin: 0;">
                    <label>
                        <input type="checkbox" id="${id}" data-param="${param.name}"
                               ${currentValue ? 'checked' : ''}>
                        ${param.label}
                    </label>
                </div>`;
            // Per checkbox saltiamo il wrapper standard
            return `
                <div class="form-group" style="margin-bottom: 8px;">
                    <div class="col-sm-4"></div>
                    <div class="col-sm-8">
                        ${inputHtml}
                        ${param.hint ? `<small class="text-muted">${param.hint}</small>` : ''}
                    </div>
                </div>`;

        } else {
            // text o number
            const extras = param.type === 'number'
                ? `min="${param.min ?? ''}" max="${param.max ?? ''}" step="${param.step ?? 1}"`
                : '';
            inputHtml = `<input type="${param.type}" class="form-control input-sm"
                                id="${id}" data-param="${param.name}"
                                value="${currentValue}" ${extras}>`;
        }

        return `
            <div class="form-group" style="margin-bottom: 8px;">
                <label class="col-sm-4 control-label" for="${id}"
                       style="font-weight: normal; padding-top: 4px; font-size: 12px;">
                    ${param.label}
                </label>
                <div class="col-sm-8">
                    ${inputHtml}
                    ${param.hint ? `<small class="text-muted" style="font-size: 11px;">${param.hint}</small>` : ''}
                </div>
            </div>`;
    },

    // ── Raccoglie i valori dal form (o defaults se chiuso) ────────────────────

    _collectParams(tool, $panel) {
        const $adv = $panel.find('.g-diadema-advanced-panel');
        const params = {};

        if ($adv.is(':visible')) {
            // Legge i valori dal form
            $adv.find('[data-param]').each(function () {
                const name = $(this).data('param');
                const type = $(this).attr('type');
                if (type === 'checkbox') {
                    params[name] = $(this).is(':checked');
                } else {
                    params[name] = $(this).val();
                }
            });
        } else {
            // Usa i default (con auto-detect per MRIQC)
            const autoValues = tool.id === 'mriqc'
                ? DiademaPanel._inferMRIQCParams(
                    $panel.closest('.g-item-view, .g-item-info').data('view')?.model
                    ?? { toJSON: () => ({}) }  // fallback
                  )
                : {};
            tool.params.forEach(p => {
                params[p.name] = autoValues[p.name] !== undefined ? autoValues[p.name] : p.default;
            });
        }

        return params;
    },

    // ── Auto-detect parametri MRIQC dal filename / metadata ───────────────────
    // Portato da nifti_qc/girder_nifti_qc/web_client/views/ItemView.js

    _inferMRIQCParams(itemModel) {
        const item = itemModel && typeof itemModel.toJSON === 'function' ? itemModel.toJSON() : {};
        const nifti = item.nifti || item.meta?.nifti || {};
        const niftiMeta = nifti.meta || {};
        const jsonMeta = niftiMeta.json_metadata || {};
        const files = nifti.files || [];
        const fileName = files[0]?.name || item.name || '';

        // Participant label: cerca pattern sub-XXX nel nome file
        let participantLabel = '001';
        const subMatch = fileName.match(/sub-([a-zA-Z0-9]+)/i);
        if (subMatch) participantLabel = subMatch[1];
        const prevQC = item.diadema?.mriqc?.results;
        if (prevQC?.participant_label) participantLabel = prevQC.participant_label;

        // Modality: dal nome file (BIDS), poi metadata, poi stima
        let modality = null;

        const modalityMatch = fileName.match(/[._](T1w|T2w|bold|dwi|FLAIR|T2star)[._]/i);
        if (modalityMatch) modality = modalityMatch[1];

        if (!modality && prevQC?.modality) modality = prevQC.modality;

        if (!modality) {
            const desc = (jsonMeta.ProtocolName || jsonMeta.SeriesDescription || '').toLowerCase();
            if (desc.match(/diff|dwi|dti/)) modality = 'dwi';
            else if (desc.match(/bold|fmri|func/)) modality = 'bold';
            else if (desc.match(/\bt2\b/)) modality = 'T2w';
            else if (desc.match(/\bt1\b/)) modality = 'T1w';
        }

        if (!modality) {
            const dims = niftiMeta.dimensions || [];
            if (dims.length === 4 && dims[3] > 1 && jsonMeta.RepetitionTime) modality = 'bold';
        }

        if (!modality) modality = 'T1w';

        return { participantLabel, modality };
    },

    // ── Handler bottone Run ───────────────────────────────────────────────────

    _onRun(itemView, $panel) {
        const tool = DiademaPanel._getSelectedTool($panel);
        const itemId = itemView.model.id;
        const $runBtn = $panel.find('.g-diadema-run-btn');

        const ACTIVE = ['running', 'queued', 'processing'];
        const { status, results } = DiademaPanel._getToolMeta(itemView.model, tool);

        // ── Blocca se il job è già attivo ─────────────────────────────────────
        if (ACTIVE.includes(status)) {
            events.trigger('g:alert', {
                icon: 'info-circled',
                text: `${tool.label} è già in corso (stato: ${status}). Attendi il completamento.`,
                type: 'info',
                timeout: 5000,
            });
            return;
        }

        // ── Chiede conferma se il tool è già stato eseguito ───────────────────
        if (results) {
            // eslint-disable-next-line no-alert
            if (!window.confirm(
                `${tool.label} è già stato eseguito su questo item.\n\nVuoi rieseguirlo sovrascrivendo i risultati esistenti?`
            )) return;
        }

        const params = DiademaPanel._collectParams(tool, $panel);
        // Passa force=true se l'utente ha confermato la riesecuzione
        if (results) params.force = true;

        $runBtn.prop('disabled', true)
               .html(`<i class="icon-spin3 animate-spin"></i> In coda…`);

        restRequest({
            method: 'POST',
            url: `diadema_pipeline/${itemId}/run/${tool.id}`,
            data: params,
        }).done(response => {
            events.trigger('g:alert', {
                icon: 'ok',
                text: `${tool.label} avviato (Job ID: ${response.job_id})`,
                type: 'success',
                timeout: 5000,
            });

            // Aggiorna subito il modello Backbone con lo stato 'queued'
            // così _updateRunButtonState lo mantiene disabilitato durante il polling
            const curDiadema = Object.assign({}, itemView.model.get('diadema') || {});
            curDiadema[tool.id] = Object.assign({}, curDiadema[tool.id] || {}, { status: 'queued' });
            itemView.model.set('diadema', curDiadema);

            DiademaPanel._setBadge($panel, tool.id, 'queued');

            DiademaPanel._pollForResults(itemView, $panel, itemId, tool.id, 15000);

        }).fail(err => {
            const msg = err.responseJSON?.message || 'Errore sconosciuto';
            events.trigger('g:alert', {
                icon: 'cancel',
                text: `Errore avvio ${tool.label}: ${msg}`,
                type: 'danger',
                timeout: 6000,
            });
            $runBtn.prop('disabled', false).html('<i class="icon-play"></i> Run');
        });
    },

    // ── Polling risultati ─────────────────────────────────────────────────────

    _pollForResults(itemView, $panel, itemId, toolId, intervalMs) {
        const tool = TOOLS.find(t => t.id === toolId);

        let pollCount = 0;
        const maxPolls = 120;  // ~30 min a 15 s/poll

        const check = () => {
            pollCount++;

            restRequest({ method: 'GET', url: `item/${itemId}` }).done(item => {
                const toolData = (item.diadema || {})[toolId] || {};
                const status  = toolData.status;
                const results = toolData.results;

                // Aggiorna il badge in tempo reale durante il polling
                if (status) DiademaPanel._setBadge($panel, toolId, status);

                if (status === 'completed') {
                    // Aggiorna il modello Backbone → triggera il widget nifti_viewer
                    const curDia = Object.assign({}, itemView.model.get('diadema') || {});
                    curDia[toolId] = Object.assign({}, curDia[toolId] || {}, { status, results });
                    itemView.model.set('diadema', curDia);
                    events.trigger('g:alert', {
                        icon: 'ok',
                        text: `${tool.label} completato!`,
                        type: 'success',
                        timeout: 4000,
                    });
                    DiademaPanel._updateRunButtonState(itemView, $panel);

                } else if (status === 'error') {
                    const errMsg = toolData.error?.message || '';
                    events.trigger('g:alert', {
                        icon: 'cancel',
                        text: `${tool.label} fallito${errMsg ? ': ' + errMsg : ''}`,
                        type: 'danger',
                        timeout: 6000,
                    });
                    // Aggiorna modello con lo stato di errore e ripristina Run
                    const curDia = Object.assign({}, itemView.model.get('diadema') || {});
                    curDia[toolId] = Object.assign({}, curDia[toolId] || {}, { status: 'error' });
                    itemView.model.set('diadema', curDia);
                    DiademaPanel._updateRunButtonState(itemView, $panel);

                } else if (pollCount < maxPolls) {
                    setTimeout(check, intervalMs);

                } else {
                    events.trigger('g:alert', {
                        icon: 'attention',
                        text: `${tool.label}: timeout polling. Controlla il pannello Jobs.`,
                        type: 'warning',
                        timeout: 8000,
                    });
                    DiademaPanel._updateRunButtonState(itemView, $panel);
                }
            });
        };

        setTimeout(check, intervalMs);
    },

    // ── Badge di stato per ogni tool ──────────────────────────────────────────

    _refreshBadges(itemView) {
        const $panel = itemView.$('.g-diadema-panel');
        if (!$panel.length) return;

        TOOLS.forEach(tool => {
            const { status } = DiademaPanel._getToolMeta(itemView.model, tool);
            DiademaPanel._setBadge($panel, tool.id, status || null);
        });
    },

    _setBadge($panel, toolId, status) {
        const $badge = $panel.find(`.g-diadema-tool-badge[data-tool="${toolId}"]`);
        if (!status) {
            $badge.html('');
            return;
        }
        const info = STATUS_CLASSES[status];
        if (info) {
            $badge.html(`<span class="label label-${info.cls}" style="font-size: 11px;">${info.text}</span>`);
        } else {
            $badge.html(`<span class="label label-default" style="font-size:11px;">${status}</span>`);
        }
    },
};

export default DiademaPanel;
