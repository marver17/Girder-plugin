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
     * Restituisce true se l'item contiene (o è) un file NIfTI.
     * Controllo sincrono su nome + diadema; se ambiguo risolve async via files API.
     * @returns {boolean|Promise<boolean>}
     */
    _isNiftiItem(item) {
        const name = (item.get('name') || '').toLowerCase();
        if (name.endsWith('.nii') || name.endsWith('.nii.gz')) return true;

        // Già processato da DIADEMA → mostra comunque
        const diadema = item.get('diadema') || {};
        if (Object.keys(diadema).length > 0) return true;

        // Controllo asincrono sulle files dell'item
        return restRequest({
            method: 'GET',
            url: `item/${item.id}/files`,
            data: { limit: 20 },
            error: null,
        }).then((files) => {
            return (files || []).some(f => {
                const n = (f.name || '').toLowerCase();
                return n.endsWith('.nii') || n.endsWith('.nii.gz');
            });
        }).catch(() => false);
    },

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

        const result = DiademaPanel._isNiftiItem(item);
        if (result && typeof result === 'object' && typeof result.then === 'function') {
            // Risposta asincrona (controllo files)
            result.then(isNifti => {
                if (isNifti) DiademaPanel._mountPanel(itemView);
            });
        } else if (result) {
            DiademaPanel._mountPanel(itemView);
        }
    },

    _mountPanel(itemView) {
        if (itemView.$('.g-diadema-panel').length) {
            DiademaPanel._refreshBadges(itemView);
            return;
        }

        const $panel = DiademaPanel._buildPanel(itemView);
        $panel.data('diadema-mode', 'item');
        $panel.data('diadema-id', itemView.model.id);

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

    _getToolMeta(model, tool) {
        const mode = '$panel' in this ? 'unknown' : 'item';
        return DiademaPanel._getToolMetaFromModel(model, tool, mode);
    },

    // ── Riprende il polling per i job attivi al (ri)caricamento della pagina ──

    _resumeActiveJobs(view, $panel) {
        const mode  = $panel.data('diadema-mode') || 'item';
        const id    = $panel.data('diadema-id') || DiademaPanel._getViewModel(view)?.id;
        const model = DiademaPanel._getViewModel(view);
        const ACTIVE = ['running', 'queued', 'processing'];
        TOOLS.forEach(tool => {
            const { status } = DiademaPanel._getToolMetaFromModel(model, tool, mode);
            if (ACTIVE.includes(status)) {
                DiademaPanel._pollForResults(view, $panel, id, tool.id, 8000, mode);
            }
        });
        DiademaPanel._updateRunButtonState(view, $panel);
    },

    // ── Aggiorna il bottone Run in base allo stato del tool selezionato ───────

    _updateRunButtonState(view, $panel) {
        const mode  = $panel.data('diadema-mode') || 'item';
        const model = DiademaPanel._getViewModel(view);
        const ACTIVE = ['running', 'queued', 'processing', 'uploading', 'cancelling'];
        const CANCELLABLE = ['running', 'queued', 'processing', 'uploading'];
        const tool = DiademaPanel._getSelectedTool($panel);
        const { status } = DiademaPanel._getToolMetaFromModel(model, tool, mode);
        const $btn = $panel.find('.g-diadema-run-btn');
        const $cancelBtn = $panel.find('.g-diadema-cancel-btn');
        const $resetBtn = $panel.find('.g-diadema-reset-btn');
        if (ACTIVE.includes(status)) {
            $btn.prop('disabled', true).html('<i class="icon-spin3 animate-spin"></i> In corso…');
            if (status === 'cancelling') {
                $cancelBtn.hide();
                $resetBtn.show().prop('disabled', false);
            } else {
                $cancelBtn.show().prop('disabled', CANCELLABLE.includes(status) ? false : true)
                    .html('<i class="icon-cancel"></i> Cancel');
                $resetBtn.hide();
            }
        } else {
            $btn.prop('disabled', false).html('<i class="icon-play"></i> Run');
            $cancelBtn.hide();
            $resetBtn.hide();
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
                    <button class="btn btn-sm btn-danger g-diadema-cancel-btn" style="min-width: 80px; display: none;">
                        <i class="icon-cancel"></i> Cancel
                    </button>
                    <button class="btn btn-sm btn-warning g-diadema-reset-btn" style="min-width: 80px; display: none;" title="Forza reset (sblocca job cancelling stuck)">
                        <i class="icon-cw"></i> Force reset
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

        // Cancel
        $panel.find('.g-diadema-cancel-btn').on('click', () => {
            DiademaPanel._onCancel(itemView, $panel);
        });

        // Force reset (stuck cancelling)
        $panel.find('.g-diadema-reset-btn').on('click', () => {
            DiademaPanel._onForceReset(itemView, $panel);
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

        // Banner preview participant label (tutti i tool che hanno il campo)
        const hasParticipantLabel = tool.params.some(p => p.name === 'participantLabel');
        const participantPreview = hasParticipantLabel ? `
            <div class="g-diadema-participant-preview" style="
                margin-top: 8px; padding: 8px 10px; border-radius: 4px;
                background: #f4faf0; border: 1px solid #b8dea8; font-size: 11px;">
                <div style="font-weight: 600; color: #3a7a2a; margin-bottom: 4px;">
                    <i class="icon-user"></i> Participant Label rilevato
                </div>
                <div class="g-participant-label-text" style="color: #555;">
                    <i class="icon-spin3 animate-spin"></i> Calcolo…
                </div>
            </div>` : '';

        const mode = $panel.data('diadema-mode') || 'item';
        const sessionFilesSection = mode === 'session' ? `
            <div class="g-diadema-session-files" style="
                margin-top: 12px; padding: 8px 10px; border-radius: 4px;
                background: #fdf8f0; border: 1px solid #e8d5a0; font-size: 12px;">
                <div style="font-weight: 600; color: #7a5a00; margin-bottom: 6px;">
                    <i class="icon-docs"></i> File nella sessione
                </div>
                <div class="g-session-files-content">
                    <i class="icon-spin3 animate-spin"></i> Caricamento file…
                </div>
            </div>` : '';

        $form.html(`
            <div style="padding-bottom: 4px; margin-bottom: 10px; border-bottom: 1px solid #eee;">
                <strong style="font-size: 13px; color: #555;">
                    <i class="${tool.icon}"></i> ${tool.label} – Parametri
                </strong>
                ${tool.workerNote ? `<br><small class="text-muted" style="font-size: 11px;">🐳 ${tool.workerNote}</small>` : ''}
            </div>
            ${sessionFilesSection}
            <div class="form-horizontal" style="font-size: 13px;">
                ${fields}
            </div>
            ${derivativesPreview}
            ${participantPreview}
        `);

        if (mode === 'session') {
            const folderId = $panel.data('diadema-id');
            DiademaPanel._loadSessionFiles(folderId, tool, $form);
        }

        // Preview iniziale e aggiornamento live su modifica del campo
        if (tool.id === 'mriqc') {
            DiademaPanel._refreshDerivativesPreview(itemView, $form, '');

            $form.on('input change', '[data-param="derivativesRootId"]', function () {
                DiademaPanel._refreshDerivativesPreview(itemView, $form, $(this).val().trim());
            });
        }

        if (hasParticipantLabel) {
            DiademaPanel._refreshParticipantLabelPreview(itemView, $form, '');
            $form.on('input change', '[data-param="participantLabel"]', function () {
                DiademaPanel._refreshParticipantLabelPreview(itemView, $form, $(this).val().trim());
            });
        }
    },

    // ── File selector per modalità sessione ───────────────────────────────────

    _loadSessionFiles(folderId, tool, $form) {
        const $content = $form.find('.g-session-files-content');
        restRequest({ method: 'GET', url: `diadema_pipeline/session/${folderId}/files`, error: null })
            .then(data => {
                const files = data.files || [];
                if (!files.length) {
                    $content.html('<span class="text-muted">Nessun file NIfTI trovato nella sessione.</span>');
                    return;
                }
                $content.html(DiademaPanel._buildSessionFilesHTML(tool.id, files));
            })
            .catch(() => {
                $content.html('<span class="text-danger">Errore nel caricamento dei file.</span>');
            });
    },

    _buildSessionFilesHTML(toolId, files) {
        if (toolId === 'mriqc') {
            // Checkbox per ogni file NIfTI
            const rows = files.map(f => `
                <label style="display:flex;align-items:center;gap:6px;margin-bottom:4px;font-weight:normal;cursor:pointer;">
                    <input type="checkbox" class="g-session-file-check"
                           data-file-id="${f.file_id || ''}"
                           data-modality="${f.modality || '?'}"
                           ${f.file_id ? 'checked' : 'disabled'}>
                    <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
                          title="${f.name}">${f.name}</span>
                    <span class="label label-default" style="font-size:10px;flex-shrink:0;">
                        ${f.modality || '?'}
                    </span>
                </label>`).join('');
            return `<div style="max-height:140px;overflow-y:auto;">${rows}</div>
                    <small class="text-muted">Deseleziona i file che non vuoi processare.</small>`;
        }

        // FreeSurfer / LST-AI: select per ogni modalità richiesta/opzionale
        const modalities = toolId === 'freesurfer'
            ? [{ key: 't1wFileId', label: 'T1w', required: true }, { key: 't2wFileId', label: 'T2w', required: false }]
            : [{ key: 't1wFileId', label: 'T1w', required: true }, { key: 'flairFileId', label: 'FLAIR', required: false }];

        return modalities.map(({ key, label, required }) => {
            const matching = files.filter(f => f.modality && f.modality.toLowerCase() === label.toLowerCase());
            const options = [
                required ? '' : '<option value="">— nessuno —</option>',
                ...files.map(f => {
                    const sel = matching.length > 0 && f.file_id === matching[0].file_id ? 'selected' : '';
                    return `<option value="${f.file_id || ''}" ${sel}>${f.name}</option>`;
                }),
            ].join('');
            return `
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
                    <span style="width:54px;font-weight:600;color:${required ? '#c0392b' : '#555'};">
                        ${label}${required ? ' *' : ''}
                    </span>
                    <select class="form-control" data-session-file="${key}" style="flex:1;height:28px;padding:2px 6px;font-size:12px;">
                        ${options}
                    </select>
                </div>`;
        }).join('');
    },

    _collectSessionFileOverrides($panel) {
        const $adv = $panel.find('.g-diadema-advanced-panel');
        const overrides = {};

        // MRIQC: checkbox
        const checked = [];
        $adv.find('.g-session-file-check:checked').each(function () {
            const fid = $(this).data('file-id');
            if (fid) checked.push(fid);
        });
        if (checked.length) overrides.selectedFileIds = checked.join(',');

        // FreeSurfer / LST-AI: select
        $adv.find('[data-session-file]').each(function () {
            const key = $(this).data('session-file');
            const val = $(this).val();
            if (val) overrides[key] = val;
        });

        return overrides;
    },

    _refreshParticipantLabelPreview(view, $form, hint) {
        const $panel = view.$('.g-diadema-panel');
        const mode = ($panel.length && $panel.data('diadema-mode')) || 'item';
        const itemId = ($panel.length && $panel.data('diadema-id')) || DiademaPanel._getViewModel(view)?.id;
        const $text = $form.find('.g-participant-label-text');
        if (!$text.length) return;

        $text.html('<i class="icon-spin3 animate-spin"></i> Calcolo…');

        const data = {};
        if (hint) data.hint = hint;

        const plUrl = mode === 'session'
            ? `diadema_pipeline/session/${itemId}/participant_label`
            : `diadema_pipeline/${itemId}/participant_label`;
        restRequest({
            method: 'GET',
            url: plUrl,
            data,
            error: null,
        }).then((resp) => {
            const sourceMap = {
                manual:   { color: '#2a5a99', icon: 'icon-pencil',    label: 'manuale' },
                filename: { color: '#2a7a2a', icon: 'icon-doc-text',  label: 'da filename' },
                folder:   { color: '#7a5a00', icon: 'icon-folder',    label: 'da cartella' },
                fallback: { color: '#999',    icon: 'icon-attention', label: 'fallback' },
            };

            // Se è il caricamento iniziale (campo vuoto o valore di fallback salvato)
            // e il valore è stato rilevato con certezza, pre-compila il campo
            const $input = $form.find('[data-param="participantLabel"]');
            const isInitialLoad = !hint;
            if (isInitialLoad && resp.source !== 'fallback') {
                $input.val(resp.label);
            }

            const s = sourceMap[resp.source] || sourceMap.fallback;
            $text.html(`
                <span style="color:${s.color}; font-weight:600;">
                    <i class="${s.icon}"></i>
                    sub-<strong>${resp.label}</strong>
                </span>
                <span style="color:#999; margin-left:6px;">(${s.label})</span>
            `);
        }).catch(() => {
            $text.html('<span style="color:#999;">Anteprima non disponibile</span>');
        });
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
            $adv.find('[data-param]').each(function () {
                const name = $(this).data('param');
                const type = $(this).attr('type');
                if (type === 'checkbox') {
                    params[name] = $(this).is(':checked');
                } else {
                    params[name] = $(this).val();
                }
            });
            // Aggiungi override file (solo session mode)
            if ($panel.data('diadema-mode') === 'session') {
                Object.assign(params, DiademaPanel._collectSessionFileOverrides($panel));
            }
        } else {
            const autoValues = tool.id === 'mriqc'
                ? DiademaPanel._inferMRIQCParams(
                    $panel.closest('.g-item-view, .g-item-info').data('view')?.model
                    ?? { toJSON: () => ({}) }
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

    _onForceReset(view, $panel) {
        const mode = $panel.data('diadema-mode') || 'item';
        const id   = $panel.data('diadema-id') || DiademaPanel._getViewModel(view)?.id;
        const tool = DiademaPanel._getSelectedTool($panel);

        // eslint-disable-next-line no-alert
        if (!window.confirm(`Forza il reset di ${tool.label}? Il job verrà marcato come cancellato.`)) return;

        const $resetBtn = $panel.find('.g-diadema-reset-btn');
        $resetBtn.prop('disabled', true).html('<i class="icon-spin3 animate-spin"></i>…');

        const resetUrl = mode === 'session'
            ? `diadema_pipeline/session/${id}/reset/${tool.id}`
            : `diadema_pipeline/${id}/reset/${tool.id}`;

        restRequest({ method: 'POST', url: resetUrl }).done(() => {
            events.trigger('g:alert', {
                icon: 'ok',
                text: `${tool.label}: job resettato.`,
                type: 'success',
                timeout: 4000,
            });
            const curDiadema = Object.assign({}, DiademaPanel._getViewModel(view).get('diadema') || {});
            curDiadema[tool.id] = Object.assign({}, curDiadema[tool.id] || {}, { status: 'cancelled' });
            DiademaPanel._getViewModel(view).set('diadema', curDiadema);
            DiademaPanel._setBadge($panel, tool.id, 'cancelled');
            DiademaPanel._updateRunButtonState(view, $panel);
        }).fail(err => {
            const msg = err.responseJSON?.message || 'Errore sconosciuto';
            events.trigger('g:alert', {
                icon: 'cancel',
                text: `Errore reset ${tool.label}: ${msg}`,
                type: 'danger',
                timeout: 5000,
            });
            $resetBtn.prop('disabled', false).html('<i class="icon-cw"></i> Force reset');
        });
    },

    // ── Handler bottone Cancel ────────────────────────────────────────────────

    _onCancel(view, $panel) {
        const mode = $panel.data('diadema-mode') || 'item';
        const id   = $panel.data('diadema-id') || DiademaPanel._getViewModel(view)?.id;
        const tool = DiademaPanel._getSelectedTool($panel);
        const $cancelBtn = $panel.find('.g-diadema-cancel-btn');

        // eslint-disable-next-line no-alert
        if (!window.confirm(`Vuoi annullare il job ${tool.label} in corso?`)) return;

        $cancelBtn.prop('disabled', true).html('<i class="icon-spin3 animate-spin"></i> Cancelling…');

        const cancelUrl = mode === 'session'
            ? `diadema_pipeline/session/${id}/cancel/${tool.id}`
            : `diadema_pipeline/${id}/cancel/${tool.id}`;

        restRequest({ method: 'POST', url: cancelUrl }).done(() => {
            events.trigger('g:alert', {
                icon: 'attention',
                text: `${tool.label}: richiesta di cancellazione inviata. Il job si fermerà a breve.`,
                type: 'warning',
                timeout: 5000,
            });
            const curDiadema = Object.assign({}, DiademaPanel._getViewModel(view).get('diadema') || {});
            curDiadema[tool.id] = Object.assign({}, curDiadema[tool.id] || {}, { status: 'cancelling' });
            DiademaPanel._getViewModel(view).set('diadema', curDiadema);
            DiademaPanel._setBadge($panel, tool.id, 'cancelling');
            DiademaPanel._updateRunButtonState(view, $panel);
        }).fail(err => {
            const msg = err.responseJSON?.message || 'Errore sconosciuto';
            events.trigger('g:alert', {
                icon: 'cancel',
                text: `Errore cancellazione ${tool.label}: ${msg}`,
                type: 'danger',
                timeout: 5000,
            });
            $cancelBtn.prop('disabled', false).html('<i class="icon-cancel"></i> Cancel');
        });
    },

    // ── Helper mode (item vs sessione BIDS) ──────────────────────────────────

    /**
     * Restituisce il modello Backbone corretto per la view.
     * FolderView usa this.folder (non this.model come ItemView).
     */
    _getViewModel(view) {
        return view.folder || view.model;
    },

    /** Controlla se una stringa nome corrisponde a una sessione BIDS (ses-XX o sub-XX). */
    _isSessionFolderName(name) {
        return /^(ses|sub)[-_][a-zA-Z0-9]+$/i.test((name || '').trim());
    },

    /** Controlla se un FolderModel corrisponde a una sessione BIDS. */
    _isSessionFolder(folderModel) {
        return DiademaPanel._isSessionFolderName((folderModel && folderModel.get('name')) || '');
    },

    /**
     * Monta il pannello DIADEMA conoscendo solo id e nome della cartella
     * (usato da g:hierarchy.route dove non abbiamo il FolderModel completo).
     */
    mountPanelByIdAndName(folderId, folderName) {
        const $panel = DiademaPanel._buildPanel({});
        $panel.data('diadema-mode', 'session');
        $panel.data('diadema-id', folderId);
        $panel.find('small.text-muted').first()
            .text(`Sessione BIDS (${folderName}) — seleziona un tool e premi Run`);

        const $anchor = $('.g-hierarchy-breadcrumb-bar').first();
        if ($anchor.length) {
            $anchor.before($panel);
        } else {
            $('#g-app-body-container').prepend($panel);
        }

        // Proxy minimo: il model viene letto da $panel.data() nei metodi mode-aware
        const proxy = {
            folder: { id: folderId, get: (k) => k === 'name' ? folderName : k === 'diadema' ? null : undefined, set: () => {}, get diadema() { return null; } },
            model: null,
            $: (sel) => $panel.parent().find(sel),
            $el: $panel.parent(),
        };

        DiademaPanel._bindEvents(proxy, $panel);
        DiademaPanel._resumeActiveJobs(proxy, $panel);
    },

    /** Legge diadema.{toolId} dal modello (item o folder in base al data-diadema-mode). */
    _getToolMetaFromModel(model, tool, mode) {
        if (!model) return { status: null, results: null };
        let diadema;
        if (mode === 'session') {
            diadema = model.get('diadema') || {};
        } else {
            const item = model.toJSON ? model.toJSON() : model;
            diadema = item.diadema || {};
        }
        const toolData = diadema[tool.id] || {};
        return { status: toolData.status || null, results: toolData.results || null };
    },

    /** URL base REST per eseguire il tool sul target corretto. */
    _runUrl(mode, id, toolId) {
        return mode === 'session'
            ? `diadema_pipeline/session/${id}/run/${toolId}`
            : `diadema_pipeline/${id}/run/${toolId}`;
    },

    /** URL REST per il polling dei risultati. */
    _pollUrl(mode, id) {
        return mode === 'session'
            ? `diadema_pipeline/session/${id}/results`
            : `item/${id}`;
    },

    /** Estrae diadema dal payload di risposta del polling. */
    _extractDiadema(response, mode) {
        return mode === 'session' ? (response.diadema || {}) : (response.diadema || {});
    },

    // ── Entry point FolderView ────────────────────────────────────────────────

    /**
     * Entry point chiamato da g:navigateTo (via main.js).
     * Lavora direttamente sul DOM e sul FolderModel — nessun riferimento
     * all'istanza FolderView (non disponibile come global in Girder 5).
     */
    mountPanelForFolder(folder) {
        if (!folder) return;
        const folderId   = folder.id || folder.get('_id');
        const folderName = folder.get('name') || '';

        const existing = $('.g-diadema-panel[data-diadema-mode="session"]');
        if (existing.data('diadema-id') === folderId) return;
        existing.remove();

        DiademaPanel.mountPanelByIdAndName(folderId, folderName);

        // Badge iniziali dal modello se già presenti
        const diadema = folder.get('diadema') || {};
        const $panel = $(`.g-diadema-panel[data-diadema-id="${folderId}"]`);
        TOOLS.forEach(tool => {
            DiademaPanel._setBadge($panel, tool.id, (diadema[tool.id] || {}).status || null);
        });
    },

    // Alias per backward-compat (chiamato da _resumeActiveJobs via proxy)
    addPanelToFolder(folderView) {
        const folder = DiademaPanel._getViewModel(folderView);
        if (!folder) return;
        if (!DiademaPanel._isSessionFolder(folder)) return;
        DiademaPanel.mountPanelForFolder(folder);
    },

    // ── Handler bottone Run ───────────────────────────────────────────────────

    _onRun(view, $panel) {
        const mode = $panel.data('diadema-mode') || 'item';
        const id   = $panel.data('diadema-id') || DiademaPanel._getViewModel(view)?.id;
        const tool = DiademaPanel._getSelectedTool($panel);
        const $runBtn = $panel.find('.g-diadema-run-btn');

        const ACTIVE = ['running', 'queued', 'processing'];
        const { status, results } = DiademaPanel._getToolMetaFromModel(DiademaPanel._getViewModel(view), tool, mode);

        if (ACTIVE.includes(status)) {
            events.trigger('g:alert', {
                icon: 'info-circled',
                text: `${tool.label} è già in corso (stato: ${status}). Attendi il completamento.`,
                type: 'info',
                timeout: 5000,
            });
            return;
        }

        const targetLabel = mode === 'session' ? 'questa sessione' : 'questo item';
        if (results) {
            // eslint-disable-next-line no-alert
            if (!window.confirm(
                `${tool.label} è già stato eseguito su ${targetLabel}.\n\nVuoi rieseguirlo sovrascrivendo i risultati esistenti?`
            )) return;
        }

        const params = DiademaPanel._collectParams(tool, $panel);
        if (results) params.force = true;

        $runBtn.prop('disabled', true).html('<i class="icon-spin3 animate-spin"></i> In coda…');

        restRequest({
            method: 'POST',
            url: DiademaPanel._runUrl(mode, id, tool.id),
            data: params,
        }).done(response => {
            events.trigger('g:alert', {
                icon: 'ok',
                text: `${tool.label} avviato (Job ID: ${response.job_id})`,
                type: 'success',
                timeout: 5000,
            });

            const curDiadema = Object.assign({}, DiademaPanel._getViewModel(view).get('diadema') || {});
            curDiadema[tool.id] = Object.assign({}, curDiadema[tool.id] || {}, { status: 'queued' });
            DiademaPanel._getViewModel(view).set('diadema', curDiadema);

            DiademaPanel._setBadge($panel, tool.id, 'queued');
            DiademaPanel._pollForResults(view, $panel, id, tool.id, 15000, mode);

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

    _pollForResults(view, $panel, id, toolId, intervalMs, mode) {
        const _mode = mode || $panel.data('diadema-mode') || 'item';
        const tool = TOOLS.find(t => t.id === toolId);

        let pollCount = 0;
        const maxPolls = 120;  // ~30 min a 15 s/poll

        const check = () => {
            pollCount++;

            restRequest({ method: 'GET', url: DiademaPanel._pollUrl(_mode, id) }).done(response => {
                const diadema = DiademaPanel._extractDiadema(response, _mode);
                const toolData = diadema[toolId] || {};
                const status  = toolData.status;
                const results = toolData.results;

                if (status) DiademaPanel._setBadge($panel, toolId, status);

                if (status === 'completed') {
                    const curDia = Object.assign({}, DiademaPanel._getViewModel(view).get('diadema') || {});
                    curDia[toolId] = Object.assign({}, curDia[toolId] || {}, { status, results });
                    DiademaPanel._getViewModel(view).set('diadema', curDia);
                    events.trigger('g:alert', {
                        icon: 'ok',
                        text: `${tool.label} completato!`,
                        type: 'success',
                        timeout: 4000,
                    });
                    DiademaPanel._updateRunButtonState(view, $panel);

                } else if (status === 'cancelled' || status === 'cancelling') {
                    events.trigger('g:alert', {
                        icon: 'attention',
                        text: `${tool.label} annullato.`,
                        type: 'warning',
                        timeout: 4000,
                    });
                    const curDia = Object.assign({}, DiademaPanel._getViewModel(view).get('diadema') || {});
                    curDia[toolId] = Object.assign({}, curDia[toolId] || {}, { status: 'cancelled' });
                    DiademaPanel._getViewModel(view).set('diadema', curDia);
                    DiademaPanel._updateRunButtonState(view, $panel);

                } else if (status === 'error') {
                    const errMsg = toolData.error?.message || '';
                    events.trigger('g:alert', {
                        icon: 'cancel',
                        text: `${tool.label} fallito${errMsg ? ': ' + errMsg : ''}`,
                        type: 'danger',
                        timeout: 6000,
                    });
                    const curDia = Object.assign({}, DiademaPanel._getViewModel(view).get('diadema') || {});
                    curDia[toolId] = Object.assign({}, curDia[toolId] || {}, { status: 'error' });
                    DiademaPanel._getViewModel(view).set('diadema', curDia);
                    DiademaPanel._updateRunButtonState(view, $panel);

                } else if (pollCount < maxPolls) {
                    setTimeout(check, intervalMs);

                } else {
                    events.trigger('g:alert', {
                        icon: 'attention',
                        text: `${tool.label}: timeout polling. Controlla il pannello Jobs.`,
                        type: 'warning',
                        timeout: 8000,
                    });
                    DiademaPanel._updateRunButtonState(view, $panel);
                }
            });
        };

        setTimeout(check, intervalMs);
    },

    // ── Badge di stato per ogni tool ──────────────────────────────────────────

    _refreshBadges(view) {
        const $panel = view.$('.g-diadema-panel');
        if (!$panel.length) return;
        const mode  = $panel.data('diadema-mode') || 'item';
        const model = DiademaPanel._getViewModel(view);
        TOOLS.forEach(tool => {
            const { status } = DiademaPanel._getToolMetaFromModel(model, tool, mode);
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
