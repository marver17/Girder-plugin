/**
 * paramForm.js – Generazione form parametri guidata dallo schema del tool.
 *
 * Estratto da DiademaPanel per essere condiviso con la modale di lancio batch:
 * aggiungere un tool deve continuare a richiedere il solo file in views/tools/,
 * senza toccare due generatori di form paralleli.
 *
 * Lo schema è quello dichiarato in views/tools/*.js:
 *   { name, label, type: 'text'|'number'|'select'|'checkbox',
 *     default, options, min, max, step, hint }
 */

import $ from 'jquery';

// Parametri intrinsecamente per-sessione: identificano un singolo file e non
// hanno significato applicati a N sessioni diverse. In batch la risoluzione
// resta l'auto-detect BIDS lato task.
export const PER_SESSION_PARAMS = [
    't1wFileId', 't2wFileId', 'flairFileId', 'selectedFileIds', 'fileId',
];

/** Escape minimale per i valori interpolati negli attributi HTML. */
function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, (c) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
}

/**
 * Rende un singolo campo del form.
 * @param {Object} param - descrittore dallo schema del tool
 * @param {*} currentValue - valore corrente (o default)
 * @param {String} idPrefix - prefisso degli id, per non collidere quando il
 *        form inline e la modale sono nel DOM nello stesso momento
 */
export function buildParamFieldHTML(param, currentValue, idPrefix = 'g-diadema-param') {
    const id = `${idPrefix}-${param.name}`;
    let inputHtml = '';

    if (param.type === 'select') {
        const opts = (param.options || []).map(opt =>
            `<option value="${esc(opt.value)}" ${opt.value === currentValue ? 'selected' : ''}>${esc(opt.label)}</option>`
        ).join('');
        inputHtml = `<select class="form-control input-sm" id="${id}" data-param="${param.name}">${opts}</select>`;

    } else if (param.type === 'checkbox') {
        // I checkbox portano la label dentro al controllo: saltiamo il wrapper
        // standard a due colonne.
        return `
            <div class="form-group" style="margin-bottom: 8px;">
                <div class="col-sm-4"></div>
                <div class="col-sm-8">
                    <div class="checkbox" style="margin: 0;">
                        <label>
                            <input type="checkbox" id="${id}" data-param="${param.name}"
                                   ${currentValue ? 'checked' : ''}>
                            ${esc(param.label)}
                        </label>
                    </div>
                    ${param.hint ? `<small class="text-muted">${esc(param.hint)}</small>` : ''}
                </div>
            </div>`;

    } else {
        // text o number
        const extras = param.type === 'number'
            ? `min="${esc(param.min ?? '')}" max="${esc(param.max ?? '')}" step="${esc(param.step ?? 1)}"`
            : '';
        inputHtml = `<input type="${param.type}" class="form-control input-sm"
                            id="${id}" data-param="${param.name}"
                            value="${esc(currentValue)}" ${extras}>`;
    }

    return `
        <div class="form-group" style="margin-bottom: 8px;">
            <label class="col-sm-4 control-label" for="${id}"
                   style="font-weight: normal; padding-top: 4px; font-size: 12px;">
                ${esc(param.label)}
            </label>
            <div class="col-sm-8">
                ${inputHtml}
                ${param.hint ? `<small class="text-muted" style="font-size: 11px;">${esc(param.hint)}</small>` : ''}
            </div>
        </div>`;
}

/**
 * Rende il form completo di un tool.
 * @param {Object} tool - descrittore da views/tools/
 * @param {Object} [opts]
 * @param {Object} [opts.values] - valori iniziali (default dello schema se assenti)
 * @param {Boolean} [opts.excludePerSession] - esclude gli override per-file
 *        (obbligatorio in batch: N sessioni non condividono un fileId)
 * @param {String} [opts.idPrefix]
 */
export function renderParamForm(tool, opts = {}) {
    const { values = {}, excludePerSession = false, idPrefix } = opts;
    return (tool.params || [])
        .filter(p => !(excludePerSession && PER_SESSION_PARAMS.includes(p.name)))
        .map(p => buildParamFieldHTML(
            p,
            values[p.name] !== undefined ? values[p.name] : p.default,
            idPrefix,
        ))
        .join('');
}

/**
 * Legge i valori da un contenitore che ospita un form generato qui.
 * @param {jQuery} $container
 */
export function collectParamValues($container) {
    const values = {};
    $container.find('[data-param]').each(function () {
        const $el = $(this);
        const name = $el.data('param');
        values[name] = $el.attr('type') === 'checkbox' ? $el.is(':checked') : $el.val();
    });
    return values;
}

/**
 * Sottoinsieme dei valori che si discosta dai default dello schema.
 * Usato per il riepilogo pre-lancio: mostrare 25 parametri tutti al default
 * non aiuta a decidere se lanciare.
 */
export function diffFromDefaults(tool, values) {
    const diff = {};
    (tool.params || []).forEach(p => {
        const current = values[p.name];
        if (current === undefined) return;
        // Confronto lasco: i valori dai <input> sono sempre stringhe.
        if (String(current) !== String(p.default)) {
            diff[p.name] = { label: p.label, value: current };
        }
    });
    return diff;
}
