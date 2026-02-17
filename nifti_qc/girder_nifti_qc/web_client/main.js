import { wrap } from '@girder/core/utilities/PluginUtils';
import ItemView from '@girder/core/views/body/ItemView';

import ItemViewExtension from './views/ItemView';

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

console.log('✅ NIfTI QC web client loaded');
