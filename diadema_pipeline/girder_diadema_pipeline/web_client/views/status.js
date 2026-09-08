/**
 * status.js – Vocabolario condiviso degli stati DIADEMA.
 *
 * Gli stessi stati vengono resi in tre punti (pannello item/sessione, widget
 * risultati, monitor batch): tenerne una sola definizione evita che una nuova
 * transizione venga aggiunta in un posto e dimenticata negli altri.
 *
 * I valori rispecchiano `_ACTIVE_STATUSES` e gli stati scritti in
 * `folder.diadema.<tool>.status` lato server (rest.py).
 */

// Stati con un job ancora in volo: il polling continua e il Run resta bloccato.
export const ACTIVE_STATUSES = ['queued', 'running', 'processing', 'uploading'];

// Attivi + la fase di annullamento (il job non è ancora terminato).
export const PENDING_STATUSES = [...ACTIVE_STATUSES, 'cancelling'];

// Badge compatto (pannello inline): solo un simbolo.
export const STATUS_CLASSES = {
    completed:  { cls: 'success', text: '✓' },
    uploading:  { cls: 'info',    text: '↑' },
    processing: { cls: 'warning', text: '…' },
    running:    { cls: 'warning', text: '…' },
    queued:     { cls: 'info',    text: '⏳' },
    cancelling: { cls: 'default', text: '⏹' },
    cancelled:  { cls: 'default', text: '⏹' },
    error:      { cls: 'danger',  text: '✗' },
};

// Badge esteso (widget risultati, monitor batch): stato per esteso.
export const STATUS_LABELS = {
    completed:  { cls: 'success', text: 'Completata' },
    uploading:  { cls: 'info',    text: 'Upload' },
    processing: { cls: 'warning', text: 'Elaborazione' },
    running:    { cls: 'warning', text: 'In corso' },
    queued:     { cls: 'info',    text: 'In coda' },
    cancelling: { cls: 'default', text: 'Annullamento' },
    cancelled:  { cls: 'default', text: 'Annullata' },
    error:      { cls: 'danger',  text: 'Errore' },
    // Esiti di dispatch batch, non stati di esecuzione
    skipped:    { cls: 'default', text: 'Saltata' },
    failed:     { cls: 'danger',  text: 'Dispatch fallito' },
    not_implemented: { cls: 'muted', text: 'Non disponibile' },
};

export function isActive(status) {
    return ACTIVE_STATUSES.includes(status);
}

export function isPending(status) {
    return PENDING_STATUSES.includes(status);
}

/** HTML di un badge Bootstrap per uno stato, o stringa vuota se sconosciuto. */
export function badgeHtml(status, { extended = true } = {}) {
    const map = extended ? STATUS_LABELS : STATUS_CLASSES;
    const info = map[status];
    if (!info) return '';
    return `<span class="label label-${info.cls}">${info.text}</span>`;
}
