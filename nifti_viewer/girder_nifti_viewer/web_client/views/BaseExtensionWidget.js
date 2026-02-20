/**
 * Base class for NIfTI viewer extension widgets
 * 
 * Provides common functionality for widgets that display
 * metadata or analysis results in the NIfTI viewer.
 * 
 * Subclass this and implement renderContent() to create custom widgets.
 * 
 * Example:
 * 
 *   import BaseExtensionWidget from './BaseExtensionWidget';
 *   
 *   const MyWidget = BaseExtensionWidget.extend({
 *       renderContent: function() {
 *           const data = this._data;
 *           this.$el.html(`<div>My data: ${data.value}</div>`);
 *       }
 *   });
 */

import View from '@girder/core/views/View';
import { restRequest } from '@girder/core/rest';

const BaseExtensionWidget = View.extend({
    className: 'g-nifti-extension-widget-content',
    
    /**
     * Initialize widget
     * 
     * @param {Object} settings
     * @param {Object} settings.item - Girder Item model
     * @param {Object} settings.parentView - Parent NiftiView instance
     * @param {Object} settings.widgetConfig - Widget configuration from registry
     */
    initialize: function (settings) {
        this.item = settings.item;
        this.parentView = settings.parentView;
        this.widgetConfig = settings.widgetConfig;
        this._data = null;
    },
    
    /**
     * Fetch widget data
     * 
     * Override widgetConfig.fetchData for custom data fetching logic.
     * Default behavior retrieves from item metadata using widget ID as key.
     * 
     * @returns {Promise} Promise resolving to widget data
     */
    fetchData: function () {
        if (this.widgetConfig.fetchData) {
            // Use custom fetch function if provided
            return Promise.resolve(this.widgetConfig.fetchData(this.item));
        }
        
        // Default: retrieve from item metadata
        const dataKey = this.widgetConfig.id + '_data';
        const data = this.item.get(dataKey);
        
        if (data !== undefined) {
            return Promise.resolve(data);
        }
        
        // Fallback: try fetching from REST API
        return restRequest({
            url: `item/${this.item.id}/nifti_widgets`,
            data: { widget_id: this.widgetConfig.id }
        }).then((response) => {
            if (response.length > 0 && !response[0].error) {
                return response[0].data;
            }
            throw new Error('No data available');
        });
    },
    
    /**
     * Main render method with loading state
     */
    render: function () {
        // Show loading state
        this.$el.html('<div class="g-widget-loading"><i class="icon-spin4 animate-spin"></i> Loading...</div>');
        
        // Fetch and render data
        this.fetchData()
            .then((data) => {
                this._data = data;
                this.renderContent();
            })
            .catch((error) => {
                this.renderError(error);
            });
        
        return this;
    },
    
    /**
     * Render widget content
     * 
     * MUST BE IMPLEMENTED BY SUBCLASSES
     * Access widget data via this._data
     */
    renderContent: function () {
        throw new Error('renderContent() must be implemented by subclass');
    },
    
    /**
     * Render error state
     * 
     * @param {Error} error - Error object
     */
    renderError: function (error) {
        this.$el.html(`
            <div class="alert alert-warning">
                <i class="icon-attention"></i>
                <strong>${this.widgetConfig.title}</strong>
                <p>Failed to load data: ${error.message}</p>
            </div>
        `);
    },
    
    /**
     * Helper: Format number with fixed decimals
     * 
     * @param {number} value - Number to format
     * @param {number} [decimals=2] - Number of decimal places
     * @returns {string} Formatted number or 'N/A'
     */
    formatNumber: function (value, decimals = 2) {
        if (value === null || value === undefined || isNaN(value)) {
            return 'N/A';
        }
        return typeof value === 'number' ? value.toFixed(decimals) : String(value);
    },
    
    /**
     * Helper: Format date/time
     * 
     * @param {string|Date} timestamp - Timestamp to format
     * @returns {string} Formatted date string
     */
    formatTimestamp: function (timestamp) {
        if (!timestamp) return 'N/A';
        
        try {
            const date = timestamp instanceof Date ? timestamp : new Date(timestamp);
            return date.toLocaleString();
        } catch (e) {
            return String(timestamp);
        }
    },
    
    /**
     * Helper: Create a key-value table
     * 
     * @param {Object} data - Object with key-value pairs
     * @param {Function} [formatter] - Optional formatter function(key, value)
     * @returns {string} HTML table string
     */
    createTable: function (data, formatter) {
        let html = '<table class="table table-condensed table-striped">';
        
        for (const [key, value] of Object.entries(data)) {
            const displayKey = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
            let displayValue = value;
            
            if (formatter) {
                displayValue = formatter(key, value);
            } else if (typeof value === 'number') {
                displayValue = this.formatNumber(value);
            } else if (Array.isArray(value)) {
                displayValue = value.join(', ');
            }
            
            html += `<tr><td><strong>${displayKey}</strong></td><td>${displayValue}</td></tr>`;
        }
        
        html += '</table>';
        return html;
    }
});

export default BaseExtensionWidget;
