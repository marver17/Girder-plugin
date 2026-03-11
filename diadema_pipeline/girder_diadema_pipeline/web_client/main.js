/**
 * main.js – Entry point web client DIADEMA Pipeline
 *
 * 1. Estende la Item View di Girder con il pannello DIADEMA
 * 2. Registra il ResultsWidget con il viewer NIfTI
 * 3. Registra la route di configurazione admin
 */

import events from '@girder/core/events';
import { wrap } from '@girder/core/utilities/PluginUtils';
import ItemView from '@girder/core/views/body/ItemView';

import './routes';

import DiademaPanel      from './views/DiademaPanel';
import DiademaResultsWidget from './views/ResultsWidget';

// ── 1. Inietta il pannello nella Item View ─────────────────────────────────────
wrap(ItemView, 'render', function (render) {
    this.once('g:rendered', () => {
        if (this.model && this.model.get('_modelType') === 'item') {
            DiademaPanel.addPanel(this);
        }
    });
    return render.call(this);
});

// ── 2. Registra il widget con nifti_viewer ─────────────────────────────────────

function _registerWidget(registry) {
    registry.register({
        id: 'diadema_results',
        title: 'DIADEMA Pipeline',
        component: DiademaResultsWidget,
        priority: 15,
        shouldRender: (item) => {
            const meta = item.get('meta') || {};
            return (
                meta.diadema_mriqc_results     !== undefined ||
                meta.diadema_freesurfer_results !== undefined ||
                meta.diadema_lstai_results      !== undefined
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
