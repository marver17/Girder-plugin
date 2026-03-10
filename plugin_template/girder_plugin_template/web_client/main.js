/**
 * Web client entry point per Plugin Template
 * ──────────────────────────────────────────────────────────────────────────
 * Questo file viene compilato da Vite in un bundle UMD/ESM e caricato
 * automaticamente da Girder nell'app SPA (registrato in __init__.py
 * tramite registerPluginStaticContent).
 *
 * PATTERN:
 *   - wrap() estende viste Girder esistenti senza sovrascriverle
 *   - Doppio meccanismo di registrazione widget (immediato + event)
 * ──────────────────────────────────────────────────────────────────────────
 */

import events from '@girder/core/events';
import { wrap } from '@girder/core/utilities/PluginUtils';
import ItemView from '@girder/core/views/body/ItemView';

import ItemViewExtension from './views/ItemView';
import PluginWidget from './views/PluginWidget';

// ── Estendi la Item View di Girder ──────────────────────────────────────────
// wrap() inietta codice prima/dopo il metodo `render` originale.
// this.once('g:rendered', ...) aspetta che il DOM sia pronto prima di
// aggiungere bottoni o pannelli.
wrap(ItemView, 'render', function (render) {
    this.once('g:rendered', () => {
        if (this.model && this.model.get('_modelType') === 'item') {
            // Aggiunge un bottone "Run Plugin Template" nella item view
            ItemViewExtension.addRunButton(this);
        }
    });
    return render.call(this);
});

// ── Registra widget con nifti_viewer ────────────────────────────────────────
// RIMUOVI questo blocco se non ti integri con nifti_viewer.

function _registerWidget(registry) {
    registry.register({
        id: 'plugin_template_widget',       // deve corrispondere a widget_provider.py
        title: 'Plugin Template',
        component: PluginWidget,
        priority: 20,
        shouldRender: (item) => {
            // Mostra il widget solo se l'item ha risultati
            return item.get('plugin_template_results') !== undefined;
        },
    });
    console.log('[plugin_template] Widget registrato con nifti_viewer');
}

// Caso A: nifti_viewer già caricato (window.GirderPlugins.NiftiWidgetRegistry esiste)
const _existingRegistry = window.GirderPlugins?.NiftiWidgetRegistry;
if (window.GirderPlugins?._niftiWidgetRegistryReady && _existingRegistry) {
    _registerWidget(_existingRegistry);
} else {
    // Caso B: nifti_viewer caricato dopo questo plugin → aspetta l'evento
    events.on('nifti_viewer:widgets:register', ({ registry }) => {
        _registerWidget(registry);
    });
}

console.log('[plugin_template] Web client caricato');
