/**
 * main.js – Entry point web client DIADEMA Pipeline
 *
 * 1. Estende la Item View di Girder con il pannello DIADEMA
 * 2. Registra il ResultsWidget con il viewer NIfTI
 * 3. Registra la route di configurazione admin
 */

import $ from 'jquery';
import events from '@girder/core/events';
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
    console.log('[diadema] g:hierarchy.route:', route);
    const match = (route || '').match(/folder\/([a-f0-9]{24})$/);
    if (!match) {
        $('.g-diadema-panel[data-diadema-mode="session"]').remove();
        return;
    }
    const folderId = match[1];

    setTimeout(() => {
        const $bar = $('.g-hierarchy-breadcrumb-bar');
        const folderName = $bar.find('ol>li:last-child a').first().text().trim()
                        || $bar.find('ol>li:last-child').first().text().trim();
        console.log('[diadema] folder rilevata:', folderName, 'isSession:', DiademaPanel._isSessionFolderName(folderName));

        const existing = $('.g-diadema-panel[data-diadema-mode="session"]');
        if (DiademaPanel._isSessionFolderName(folderName)) {
            if (existing.data('diadema-id') === folderId) return;
            existing.remove();
            DiademaPanel.mountPanelByIdAndName(folderId, folderName);
        } else {
            existing.remove();
        }
    }, 200);
});

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
