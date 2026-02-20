/**
 * QC Metrics Widget for NIfTI Viewer
 * 
 * Displays quality control metrics from quick_check or MRIQC analysis
 */

import View from '@girder/core/views/View';

const QCMetricsWidget = View.extend({
    className: 'g-qc-metrics-widget',
    
    initialize: function (settings) {
        this.item = settings.item;
        this.parentView = settings.parentView;
        this.widgetConfig = settings.widgetConfig;
        this._data = null;
    },
    
    /**
     * Fetch QC data from item metadata
     */
    fetchData: function () {
        const qcResults = this.item.get('nifti_qc_results');
        const qcStatus = this.item.get('nifti_qc_status');
        
        if (!qcResults) {
            return Promise.reject(new Error('No QC results available'));
        }
        
        return Promise.resolve({
            results: qcResults,
            status: qcStatus || 'unknown'
        });
    },
    
    /**
     * Main render method
     */
    render: function () {
        this.$el.html('<div class="g-widget-loading"><i class="icon-spin4 animate-spin"></i> Loading QC data...</div>');
        
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
     * Render QC metrics content
     */
    renderContent: function () {
        const data = this._data;
        const results = data.results;
        
        let html = `
            <div class="g-qc-metrics-content">
                <h4>
                    <i class="icon-ok-circled"></i> 
                    ${this.widgetConfig.title}
                </h4>
        `;
        
        // Status badge
        html += this._renderStatusBadge(data.status);
        
        // Quick check results
        if (results.quick_check) {
            html += this._renderQuickCheck(results.quick_check);
        }
        
        // MRIQC results
        if (results.metrics) {
            html += this._renderMRIQC(results);
        }
        
        // Timestamp
        if (results.timestamp) {
            const date = new Date(results.timestamp);
            html += `
                <div class="g-qc-footer">
                    <small><i class="icon-clock"></i> ${date.toLocaleString()}</small>
                </div>
            `;
        }
        
        html += '</div>';
        
        this.$el.html(html);
    },
    
    /**
     * Render status badge
     */
    _renderStatusBadge: function (status) {
        const statusMap = {
            'quick_check_completed': { label: 'Quick Check', class: 'info' },
            'completed': { label: 'MRIQC Complete', class: 'success' },
            'processing': { label: 'Processing', class: 'warning' },
            'error': { label: 'Error', class: 'danger' },
            'unknown': { label: 'Unknown', class: 'default' }
        };
        
        const statusInfo = statusMap[status] || statusMap.unknown;
        
        return `
            <div class="g-qc-status">
                <span class="label label-${statusInfo.class}">${statusInfo.label}</span>
            </div>
        `;
    },
    
    /**
     * Render quick check section
     */
    _renderQuickCheck: function (qc) {
        let html = '<div class="g-qc-section"><h5>Quick Check Results</h5>';
        
        html += '<table class="table table-condensed table-striped">';
        
        if (qc.shape) {
            html += `<tr><td><strong>Shape</strong></td><td>${qc.shape.join(' × ')}</td></tr>`;
        }
        
        if (qc.voxel_size_mm || qc.voxel_size) {
            const voxelArr = qc.voxel_size_mm || qc.voxel_size;
            const voxels = voxelArr.map(v => v.toFixed(2)).join(' × ');
            html += `<tr><td><strong>Voxel Size</strong></td><td>${voxels} mm</td></tr>`;
        }

        if (qc.orientation) {
            const orientStr = Array.isArray(qc.orientation)
                ? qc.orientation.join('')
                : qc.orientation;
            html += `<tr><td><strong>Orientation</strong></td><td>${orientStr}</td></tr>`;
        }
        
        if (qc.data_range) {
            const dr = qc.data_range;
            html += `
                <tr><td><strong>Min / Max</strong></td><td>${dr.min.toFixed(2)} / ${dr.max.toFixed(2)}</td></tr>
                <tr><td><strong>Mean ± Std</strong></td><td>${dr.mean.toFixed(2)} ± ${dr.std.toFixed(2)}</td></tr>
            `;
        }
        
        html += '</table></div>';
        
        return html;
    },
    
    /**
     * Render MRIQC section
     */
    _renderMRIQC: function (results) {
        const metrics = results.metrics;
        
        let html = `
            <div class="g-qc-section">
                <h5>MRIQC Analysis</h5>
                <p><strong>Modality:</strong> ${results.modality || 'N/A'}</p>
        `;
        
        html += '<table class="table table-condensed table-striped">';
        
        // Key metrics
        const keyMetrics = [
            { key: 'snr_total', label: 'SNR (Total)', decimals: 2 },
            { key: 'cnr', label: 'CNR', decimals: 2 },
            { key: 'fwhm_avg', label: 'FWHM Average', unit: 'mm', decimals: 2 },
            { key: 'efc', label: 'EFC (Entropy)', decimals: 3 },
            { key: 'fber', label: 'FBER', decimals: 2 },
            { key: 'qi_1', label: 'Quality Index 1', decimals: 3 },
            { key: 'qi_2', label: 'Quality Index 2', decimals: 3 }
        ];
        
        keyMetrics.forEach(metric => {
            if (metrics[metric.key] !== undefined) {
                const value = metrics[metric.key].toFixed(metric.decimals);
                const unit = metric.unit ? ` ${metric.unit}` : '';
                html += `<tr><td><strong>${metric.label}</strong></td><td>${value}${unit}</td></tr>`;
            }
        });
        
        html += '</table>';
        
        // MRIQC version
        if (results.mriqc_version) {
            html += `<p><small>MRIQC Version: ${results.mriqc_version}</small></p>`;
        }
        
        html += '</div>';
        
        return html;
    },
    
    /**
     * Render error message
     */
    renderError: function (error) {
        this.$el.html(`
            <div class="alert alert-warning">
                <i class="icon-attention"></i>
                <strong>${this.widgetConfig.title}</strong>
                <p>${error.message}</p>
            </div>
        `);
    }
});

export default QCMetricsWidget;
