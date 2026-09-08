/**
 * main.js – Entry point web client DIADEMA Pipeline
 *
 * 1. Estende la Item View di Girder con il pannello DIADEMA
 * 2. Registra il ResultsWidget con il viewer NIfTI
 * 3. Registra la route di configurazione admin
 */

import $ from 'jquery';
import events from '@girder/core/events';
import { restRequest } from '@girder/core/rest';
import { wrap } from '@girder/core/utilities/PluginUtils';
import ItemView from '@girder/core/views/body/ItemView';

import './routes';

import DiademaPanel      from './views/DiademaPanel';
import DiademaResultsWidget from './views/ResultsWidget';
import BatchPanel        from './views/BatchPanel';

// ── 1a. Inietta il pannello nella Item View (item singolo) ─────────────────────
wrap(ItemView, 'render', function (render) {
    this.once('g:rendered', () => {
        if (this.model && this.model.get('_modelType') === 'item') {
            DiademaPanel.addPanel(this);
        }
    });
    return render.call(this);
});

// ── 1b. Inietta il pannello sulla Folder View (sessione BIDS) ──────────────────
//
// Girder ha due percorsi di navigazione verso una folder:
//
// A) URL diretta (#folder/ID): router → FolderView.fetchAndInit → g:navigateTo
//    con settings.folder disponibile.
//
// B) Click sottocartella in HierarchyWidget: router.navigate senza trigger →
//    g:navigateTo NON viene emesso. L'unico evento è g:hierarchy.route con
//    il route string (es. "collection/ID/folder/ID2").
//
// Gestiamo entrambi i casi.

// Gestione navigazione folder: unico listener su g:hierarchy.route.
// g:navigateTo non viene usato per le folder perché causa duplicati in
// race condition con g:hierarchy.route (entrambi scattano per URL diretta).
//
// Route format: "collection/{id}/folder/{folderId}" o "folder/{id}/folder/{folderId}"
let _mountInFlight = false;

// Riferimento al pannello batch attualmente montato (serve a smontarlo
// correttamente: è una View Backbone, non solo del DOM da rimuovere).
let _batchPanel = null;

function _removeSessionPanel() {
    $('.g-diadema-panel[data-diadema-mode="session"]').remove();
}

function _removeBatchPanel() {
    if (_batchPanel) {
        _batchPanel.remove();     // ferma anche il polling del monitor
        _batchPanel = null;
    }
    $('.g-diadema-panel[data-diadema-mode="batch"]').remove();
}

events.on('g:hierarchy.route', function ({ route }) {
    const match = (route || '').match(/folder\/([a-f0-9]{24})$/);
    if (!match) {
        _mountInFlight = false;
        _removeSessionPanel();
        _removeBatchPanel();
        return;
    }
    const folderId = match[1];

    // Evita chiamate REST parallele (l'evento scatta a volte due volte di fila)
    if (_mountInFlight) return;
    _mountInFlight = true;

    // Risale la gerarchia (max 2 livelli) finché non trova ses-XX / sub-XX,
    // poi verifica che la sessione contenga davvero almeno un item NIfTI
    // (il nome cartella da solo non basta: una ses-XX vuota o senza dati
    // BIDS non deve mostrare il pannello, altrimenti "Run" appare senza
    // nulla su cui girare).
    _findSessionAncestor(folderId)
        .then(({ sessionId, sessionName }) => {
            if (!sessionId) {
                // Non siamo in una sessione: può essere una radice batch
                // (dataset root o sub-XX). I due pannelli sono mutuamente
                // esclusivi.
                _removeSessionPanel();
                return _tryMountBatchPanel(folderId);
            }
            _removeBatchPanel();
            return DiademaPanel._folderHasNiftiItems(sessionId)
                .then(hasNifti => {
                    const existing = $('.g-diadema-panel[data-diadema-mode="session"]');
                    if (hasNifti) {
                        if (existing.data('diadema-id') === sessionId) return;
                        existing.remove();
                        DiademaPanel.mountPanelByIdAndName(sessionId, sessionName);
                    } else {
                        existing.remove();
                    }
                });
        })
        .then(() => { _mountInFlight = false; })
        .catch(() => { _mountInFlight = false; });
});

/**
 * Monta il pannello batch se la cartella è una radice valida:
 *   - una cartella sub-XX, oppure
 *   - la radice di un dataset BIDS (contiene dataset_description.json).
 * In caso contrario rimuove un eventuale pannello batch precedente.
 */
function _tryMountBatchPanel(folderId) {
    return restRequest({ method: 'GET', url: `folder/${folderId}` })
        .then(folder => {
            const name = folder.name || '';
            const isSubject = /^sub[-_][a-zA-Z0-9]+$/i.test(name);
            if (isSubject) return { folder, mount: true };

            // Radice dataset: la si riconosce da dataset_description.json.
            return restRequest({
                method: 'GET',
                url: 'item',
                data: { folderId, name: 'dataset_description.json', limit: 1 },
                error: null,
            }).then(items => ({ folder, mount: (items || []).length > 0 }))
              .catch(() => ({ folder, mount: false }));
        })
        .then(({ folder, mount }) => {
            const existing = $('.g-diadema-panel[data-diadema-mode="batch"]');
            if (!mount) {
                _removeBatchPanel();
                return;
            }
            // Già montato sulla stessa cartella: non rifare la scansione.
            if (_batchPanel && existing.data('diadema-id') === folder._id) return;
            _removeBatchPanel();
            _mountBatchPanel(folder);
        })
        .catch(() => { _removeBatchPanel(); });
}

function _mountBatchPanel(folder) {
    const $anchor = $('.g-hierarchy-widget').first();
    if (!$anchor.length) return;

    _batchPanel = new BatchPanel({
        parentView: null,
        rootFolderId: folder._id,
        rootFolderName: folder.name || '',
    });
    $anchor.before(_batchPanel.$el);
    _batchPanel.render();
}

/**
 * Cerca la cartella ses-XX più vicina risalendo la gerarchia BIDS.
 * Controlla la cartella corrente e poi i suoi parent (max `levels` volte).
 * Il pannello appare solo a partire dal livello ses-XX (non sub-XX).
 * Ritorna Promise<{ sessionId, sessionName }> o Promise<{ sessionId: null }>.
 */
function _findSessionAncestor(folderId, levels = 3) {
    function checkFolder(id, remaining) {
        return restRequest({ method: 'GET', url: `folder/${id}` })
            .then(function (folder) {
                const name = folder.name || '';
                if (DiademaPanel._isSessionFolderName(name)) {
                    return { sessionId: folder._id, sessionName: name };
                }
                // Fermati se raggiungiamo la radice o il livello sub-XX
                if (remaining <= 0
                    || folder.parentCollection !== 'folder'
                    || !folder.parentId
                    || /^sub[-_][a-zA-Z0-9]+$/i.test(name)) {
                    return { sessionId: null, sessionName: null };
                }
                return checkFolder(folder.parentId, remaining - 1);
            });
    }
    return checkFolder(folderId, levels).catch(() => ({ sessionId: null, sessionName: null }));
}

// ── 2. Registra il widget con nifti_viewer ─────────────────────────────────────

function _registerWidget(registry) {
    registry.register({
        id: 'diadema_results',
        title: 'DIADEMA Pipeline',
        component: DiademaResultsWidget,
        priority: 15,
        shouldRender: (item) => {
            const diadema = item.get('diadema') || {};
            return (
                diadema.mriqc?.results      !== undefined ||
                diadema.freesurfer?.results !== undefined ||
                diadema.lstai?.results      !== undefined
            );
        },
    });
    console.log('[diadema_pipeline] Widget registrato con nifti_viewer');
}

// Caso A: nifti_viewer già caricato
const _existingRegistry = window.GirderPlugins?.NiftiWidgetRegistry;
if (window.GirderPlugins?._niftiWidgetRegistryReady && _existingRegistry) {
    _registerWidget(_existingRegistry);
} else {
    // Caso B: nifti_viewer caricato dopo questo plugin
    events.on('nifti_viewer:widgets:register', ({ registry }) => {
        _registerWidget(registry);
    });
}

console.log('[diadema_pipeline] Web client caricato');
