import events from '@girder/core/events';
import { wrap } from '@girder/core/utilities/PluginUtils';
import ItemView from '@girder/core/views/body/ItemView';

import ItemViewExtension from './views/ItemView';
import QCMetricsWidget from './views/QCMetricsWidget';

// Extend Item view to add QC button for all items
wrap(ItemView, 'render', function (render) {
    this.once('g:rendered', () => {
        // Always show QC buttons for testing
        if (this.model && this.model.get('_modelType') === 'item') {
            ItemViewExtension.addQCButton(this);
            ItemViewExtension.showQCResults(this);
        }
    });
    
    return render.call(this);
});

// Register QC metrics widget with NIfTI viewer registry
function _registerQCWidget(registry) {
    registry.register({
        id: 'nifti_qc_metrics',
        title: 'Quality Control Metrics',
        component: QCMetricsWidget,
        priority: 10, // High priority - show first
        shouldRender: (item) => {
            // Only render if item has QC results
            return item.get('nifti_qc_results') !== undefined;
        }
    });

    console.log('✅ NIfTI QC widget registered with viewer');
}

// Handle both load orders:
// Case A: nifti_viewer loaded first → registry already ready, register immediately
// Case B: nifti_viewer loads after us → wait for the event
const _existingRegistry = window.GirderPlugins?.NiftiWidgetRegistry;
if (window.GirderPlugins?._niftiWidgetRegistryReady && _existingRegistry) {
    _registerQCWidget(_existingRegistry);
} else {
    events.on('nifti_viewer:widgets:register', ({ registry }) => {
        _registerQCWidget(registry);
    });
}

console.log('✅ NIfTI QC web client loaded');
