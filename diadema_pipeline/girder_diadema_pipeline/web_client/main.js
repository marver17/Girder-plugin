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

// Caso A: navigazione diretta via URL
events.on('g:navigateTo', function (viewClass, settings) {
    if (settings && settings.folder) {
        const folder = settings.folder;
        const name = folder.get('name') || '';
        console.log('[diadema] g:navigateTo folder:', name);
        if (DiademaPanel._isSessionFolderName(name)) {
            setTimeout(() => DiademaPanel.mountPanelForFolder(folder), 150);
        } else {
            $('.g-diadema-panel[data-diadema-mode="session"]').remove();
        }
    } else {
        $('.g-diadema-panel[data-diadema-mode="session"]').remove();
    }
});

// Caso B: navigazione in-place nel HierarchyWidget
// Route format: "collection/{id}/folder/{folderId}" o "folder/{id}/folder/{folderId}"
events.on('g:hierarchy.route', function ({ route }) {
    const match = (route || '').match(/folder\/([a-f0-9]{24})$/);
    if (!match) {
        $('.g-diadema-panel[data-diadema-mode="session"]').remove();
        return;
    }
    const folderId = match[1];

    // Risale la gerarchia (max 2 livelli) finché non trova una cartella ses-XX / sub-XX.
    // Copre il caso in cui l'utente è dentro anat/, func/, dwi/ che sono figlie di una sessione.
    _findSessionAncestor(folderId)
        .then(({ sessionId, sessionName }) => {
            const existing = $('.g-diadema-panel[data-diadema-mode="session"]');
            if (sessionId) {
                if (existing.data('diadema-id') === sessionId) return;
                existing.remove();
                DiademaPanel.mountPanelByIdAndName(sessionId, sessionName);
            } else {
                existing.remove();
            }
        });
});

/**
 * Cerca la cartella ses-XX / sub-XX più vicina risalendo la gerarchia.
 * Controlla la cartella corrente e poi i suoi parent (max `levels` volte).
 * Ritorna Promise<{ sessionId, sessionName }> o Promise<{ sessionId: null }>.
 */
function _findSessionAncestor(folderId, levels = 2) {
    function checkFolder(id, remaining) {
        return restRequest({ method: 'GET', url: `folder/${id}` })
            .then(function (folder) {
                const name = folder.name || '';
                if (DiademaPanel._isSessionFolderName(name)) {
                    return { sessionId: folder._id, sessionName: name };
                }
                if (remaining <= 0 || folder.parentCollection !== 'folder' || !folder.parentId) {
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
