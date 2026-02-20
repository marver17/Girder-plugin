import { getCurrentUser } from '@girder/core/auth';
import { AccessType } from '@girder/core/constants';
import events from '@girder/core/events';
import { restRequest } from '@girder/core/rest';
import { wrap } from '@girder/core/utilities/PluginUtils';

import ItemView from '@girder/core/views/body/ItemView';
import SearchFieldWidget from '@girder/core/views/widgets/SearchFieldWidget';

import NiftiView from './views/NiftiView';
import ParseNiftiItemTemplate from './templates/parseNiftiItem.pug';

wrap(ItemView, 'render', function (render) {
    // Clean up existing NIfTI viewer before re-rendering
    if (this._niftiViewer) {
        this._niftiViewer.destroy();
        this._niftiViewer = null;
    }
    
    this.once('g:rendered', () => {
        // Add a button to force NIfTI extraction
        if (this.model.get('_accessLevel') >= AccessType.WRITE) {
            this.$('.g-item-actions-menu').prepend(ParseNiftiItemTemplate({
                item: this.model,
                currentUser: getCurrentUser()
            }));
        }

        // If the item has NIfTI data, render the viewer
        if (this.model.has('nifti')) {
            this._niftiViewer = new NiftiView({
                parentView: this,
                item: this.model
            });
            
            this._niftiViewer
                .render()
                .$el.insertAfter(this.$('.g-item-info'));
        }
    });
    return render.call(this);
});

ItemView.prototype.events['click .g-nifti-parse-item'] = function () {
    restRequest({
        method: 'POST',
        url: `item/${this.model.id}/parseNifti`,
        error: null
    })
        .done((resp) => {
            // Show success message
            events.trigger('g:alert', {
                icon: 'ok',
                text: 'NIfTI item parsed successfully.',
                type: 'success',
                timeout: 4000
            });
            
            // Reload the item to show the viewer
            this.model.fetch().done(() => {
                this.render();
            });
        })
        .fail((resp) => {
            // Show error message
            events.trigger('g:alert', {
                icon: 'cancel',
                text: resp.responseJSON.message || 'Failed to parse NIfTI item.',
                type: 'danger',
                timeout: 5000
            });
        });
};

SearchFieldWidget.addMode(
    'nifti',
    ['item'],
    'NIfTI metadata search',
    `You are searching for text in NIfTI metadata. Only Girder items which have been preprocessed to
        extract NIfTI metadata will be searched. The search performs case-insensitive substring matching across:
        - NIfTI header fields (orientation, datatype, dimensions, pixel spacing, units, etc.)
        - BIDS JSON metadata (ProtocolName, Manufacturer, SeriesDescription, etc.)
        - File names

        Example searches: "T1", "MPRAGE", "Siemens", "RAS", "256", "3.0"`
);

/**
 * Global Widget Registry for NIfTI Viewer Extensions
 * 
 * Allows plugins to register custom widgets that will be displayed
 * in the NIfTI viewer metadata panel.
 */
class NiftiWidgetRegistry {
    constructor() {
        this.widgets = new Map();
    }
    
    /**
     * Register a widget component
     * 
     * @param {Object} config - Widget configuration
     * @param {string} config.id - Unique widget identifier
     * @param {string} config.title - Display title
     * @param {Function} config.component - View class that renders the widget
     * @param {number} [config.priority=50] - Display order (lower = first)
     * @param {Function} [config.shouldRender] - Function(item) returning boolean
     * @param {Function} [config.fetchData] - Function(item) returning Promise<data>
     */
    register(config) {
        if (!config.id || !config.component) {
            throw new Error('Widget must have id and component');
        }
        
        this.widgets.set(config.id, {
            id: config.id,
            title: config.title || config.id,
            component: config.component,
            priority: config.priority !== undefined ? config.priority : 50,
            shouldRender: config.shouldRender || (() => true),
            fetchData: config.fetchData || null
        });
        
        console.log(`[NIfTI Viewer] Registered widget: ${config.id}`);
    }
    
    /**
     * Get all widgets that should render for given context
     * 
     * @param {Object} context - Girder Item model
     * @returns {Array} Sorted array of widget configs
     */
    getWidgets(context) {
        return Array.from(this.widgets.values())
            .filter(w => w.shouldRender(context))
            .sort((a, b) => a.priority - b.priority);
    }
    
    /**
     * Unregister a widget
     * 
     * @param {string} widgetId - Widget ID to remove
     */
    unregister(widgetId) {
        this.widgets.delete(widgetId);
    }
    
    /**
     * Get count of registered widgets
     */
    count() {
        return this.widgets.size;
    }
}

// Create global registry instance
const widgetRegistry = new NiftiWidgetRegistry();

// Expose globally for other plugins
window.GirderPlugins = window.GirderPlugins || {};
window.GirderPlugins.NiftiWidgetRegistry = widgetRegistry;

// Trigger event to allow plugins to register their widgets
// Plugins should listen: events.on('nifti_viewer:widgets:register', ({ registry }) => {...})
events.trigger('nifti_viewer:widgets:register', { registry: widgetRegistry });

// Mark registry as ready so plugins that load after this can register immediately
// without relying on the event (which has already fired)
window.GirderPlugins._niftiWidgetRegistryReady = true;

console.log('[NIfTI Viewer] Widget registry initialized');

export { widgetRegistry };
