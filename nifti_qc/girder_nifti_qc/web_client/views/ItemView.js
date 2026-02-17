import { restRequest } from '@girder/core/rest';
import events from '@girder/core/events';
import $ from 'jquery';

const ItemViewExtension = {
    /**
     * Add QC control buttons to item view
     */
    addQCButton(itemView) {
        const itemId = itemView.model.id;
        const status = itemView.model.get('nifti_qc_status');
        
        // Create button container
        const buttonContainer = $(`
            <div class="g-nifti-qc-controls" style="margin: 15px 0;">
                <h4><i class="icon-ok-circled"></i> NIfTI Quality Control</h4>
            </div>
        `);
        
        // Quick Check button
        const quickCheckBtn = $(`
            <button class="btn btn-sm btn-default g-nifti-qc-quick">
                <i class="icon-flash"></i>
                Quick Check
            </button>
        `);
        
        quickCheckBtn.on('click', () => {
            ItemViewExtension.runQuickCheck(itemView, itemId);
        });
        
        // MRIQC button
        const mriqcBtn = $(`
            <button class="btn btn-sm btn-primary g-nifti-qc-mriqc">
                <i class="icon-chart-bar"></i>
                Run MRIQC Quality Control
            </button>
        `);
        
        mriqcBtn.on('click', () => {
            ItemViewExtension.runMRIQC(itemView, itemId);
        });
        
        // Show status if processing
        if (status === 'processing') {
            const statusBadge = $(`
                <span class="label label-warning" style="margin-left: 10px;">
                    <i class="icon-spin4 animate-spin"></i> Processing...
                </span>
            `);
            buttonContainer.append(statusBadge);
        }
        
        buttonContainer.append(quickCheckBtn, ' ', mriqcBtn);
        
        // Add to item view
        itemView.$('.g-item-info').after(buttonContainer);
    },
    
    /**
     * Run quick check task
     */
    runQuickCheck(itemView, itemId) {
        const btn = itemView.$('.g-nifti-qc-quick');
        btn.prop('disabled', true).html('<i class="icon-spin4 animate-spin"></i> Running...');
        
        restRequest({
            url: `nifti_qc/${itemId}/quick_check`,
            method: 'POST'
        }).done((response) => {
            events.trigger('g:alert', {
                icon: 'ok',
                text: `Quick check started! Job ID: ${response.job_id}`,
                type: 'success',
                timeout: 4000
            });
            
            // Poll for results
            ItemViewExtension.pollForResults(itemView, itemId, 5000);
            
        }).fail((err) => {
            events.trigger('g:alert', {
                icon: 'cancel',
                text: 'Error: ' + (err.responseJSON?.message || 'Unknown error'),
                type: 'danger',
                timeout: 5000
            });
            btn.prop('disabled', false).html('<i class="icon-flash"></i> Quick Check');
        });
    },
    
    /**
     * Run MRIQC with parameters
     */
    runMRIQC(itemView, itemId) {
        // Show dialog for parameters
        const dialog = $(`
            <div class="modal fade" tabindex="-1">
                <div class="modal-dialog">
                    <div class="modal-content">
                        <div class="modal-header">
                            <button type="button" class="close" data-dismiss="modal">&times;</button>
                            <h4 class="modal-title">
                                <i class="icon-chart-bar"></i> MRIQC Quality Control
                            </h4>
                        </div>
                        <div class="modal-body">
                            <p>This will run MRIQC quality control on your NIfTI file.</p>
                            <p><strong>Note:</strong> Processing may take 5-30 minutes depending on file size.</p>
                            
                            <div class="form-group">
                                <label>Participant Label</label>
                                <input type="text" class="form-control" id="participant-label" value="001" placeholder="001">
                                <small class="help-block">BIDS participant identifier (e.g., 001, sub001)</small>
                            </div>
                            
                            <div class="form-group">
                                <label>Modality</label>
                                <select class="form-control" id="modality">
                                    <option value="T1w">T1-weighted (T1w)</option>
                                    <option value="T2w">T2-weighted (T2w)</option>
                                    <option value="bold">BOLD fMRI</option>
                                    <option value="dwi">Diffusion (DWI)</option>
                                </select>
                            </div>
                            
                            <div class="form-group">
                                <label>Timeout (seconds)</label>
                                <input type="number" class="form-control" id="timeout" value="1800" min="300" max="7200">
                                <small class="help-block">Maximum processing time (default: 1800s = 30min)</small>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-default" data-dismiss="modal">Cancel</button>
                            <button type="button" class="btn btn-primary" id="run-mriqc-btn">
                                <i class="icon-ok"></i> Run MRIQC
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `);
        
        dialog.find('#run-mriqc-btn').on('click', () => {
            const participantLabel = dialog.find('#participant-label').val();
            const modality = dialog.find('#modality').val();
            const timeout = parseInt(dialog.find('#timeout').val());
            
            dialog.modal('hide');
            
            ItemViewExtension.executeMRIQC(itemView, itemId, participantLabel, modality, timeout);
        });
        
        dialog.modal('show');
    },
    
    /**
     * Execute MRIQC API call
     */
    executeMRIQC(itemView, itemId, participantLabel, modality, timeout) {
        const btn = itemView.$('.g-nifti-qc-mriqc');
        btn.prop('disabled', true).html('<i class="icon-spin4 animate-spin"></i> Submitting...');
        
        restRequest({
            url: `nifti_qc/${itemId}/run_mriqc`,
            method: 'POST',
            data: {
                participantLabel: participantLabel,
                modality: modality,
                timeout: timeout
            }
        }).done((response) => {
            events.trigger('g:alert', {
                icon: 'ok',
                text: `MRIQC job submitted! Job ID: ${response.job_id}<br>This may take 5-30 minutes.`,
                type: 'success',
                timeout: 6000
            });
            
            // Show processing indicator
            itemView.$('.g-nifti-qc-controls h4').after(`
                <span class="label label-warning g-qc-processing-badge">
                    <i class="icon-spin4 animate-spin"></i> MRIQC Processing...
                </span>
            `);
            
            // Poll for results
            ItemViewExtension.pollForResults(itemView, itemId, 15000);
            
        }).fail((err) => {
            events.trigger('g:alert', {
                icon: 'cancel',
                text: 'Error: ' + (err.responseJSON?.message || 'Unknown error'),
                type: 'danger',
                timeout: 5000
            });
            btn.prop('disabled', false).html('<i class="icon-chart-bar"></i> Run MRIQC Quality Control');
        });
    },
    
    /**
     * Poll item for QC results
     */
    pollForResults(itemView, itemId, interval) {
        let pollCount = 0;
        const maxPolls = 120; // 30 minutes with 15s intervals
        
        const checkResults = () => {
            pollCount++;
            
            restRequest({
                url: `item/${itemId}`,
                method: 'GET'
            }).done((item) => {
                const status = item.nifti_qc_status;
                
                if (status === 'completed' || status === 'quick_check_completed') {
                    // Results ready!
                    itemView.model.set(item);
                    itemView.render();
                    
                    events.trigger('g:alert', {
                        icon: 'ok',
                        text: 'Quality control completed!',
                        type: 'success',
                        timeout: 4000
                    });
                } else if (status === 'error') {
                    itemView.$('.g-qc-processing-badge').remove();
                    
                    events.trigger('g:alert', {
                        icon: 'cancel',
                        text: 'QC processing failed. Check item metadata for details.',
                        type: 'danger',
                        timeout: 5000
                    });
                } else if (pollCount < maxPolls && (status === 'processing' || !status)) {
                    // Keep polling
                    setTimeout(checkResults, interval);
                }
            });
        };
        
        setTimeout(checkResults, interval);
    },
    
    /**
     * Display QC results if available
     */
    showQCResults(itemView) {
        const results = itemView.model.get('nifti_qc_results');
        const status = itemView.model.get('nifti_qc_status');
        
        if (!results) return;
        
        const resultsDiv = $(`
            <div class="g-nifti-qc-results" style="margin: 15px 0; padding: 15px; background: #f8f9fa; border-radius: 4px; border-left: 4px solid #28a745;">
                <h4><i class="icon-ok-circled" style="color: #28a745;"></i> QC Results Available</h4>
            </div>
        `);
        
        // Quick check results
        if (results.type === 'quick_check' && results.quick_check) {
            const qc = results.quick_check;
            resultsDiv.append(`
                <table class="table table-condensed table-striped" style="background: white;">
                    <tr><th>Shape:</th><td>${qc.shape.join(' × ')}</td></tr>
                    <tr><th>Voxel Size:</th><td>${qc.voxel_size_mm.map(v => v.toFixed(2)).join(' × ')} mm</td></tr>
                    <tr><th>Orientation:</th><td>${qc.orientation.join(', ')}</td></tr>
                    <tr><th>Data Range:</th><td>${qc.data_range.min.toFixed(2)} to ${qc.data_range.max.toFixed(2)}</td></tr>
                    <tr><th>Mean:</th><td>${qc.data_range.mean.toFixed(2)} ± ${qc.data_range.std.toFixed(2)}</td></tr>
                </table>
                <small class="text-muted"><i class="icon-clock"></i> ${new Date(results.timestamp).toLocaleString()}</small>
            `);
        }
        
        // MRIQC results
        if (results.metrics && Object.keys(results.metrics).length > 0) {
            const metrics = results.metrics;
            const keyMetrics = ['snr_total', 'cnr', 'fber', 'efc', 'fwhm_avg'];
            
            let metricsHtml = '<h5>Key Quality Metrics:</h5><table class="table table-condensed table-striped" style="background: white;">';
            
            keyMetrics.forEach(key => {
                if (metrics[key] !== undefined) {
                    const label = key.toUpperCase().replace('_', ' ');
                    const value = typeof metrics[key] === 'number' ? metrics[key].toFixed(3) : metrics[key];
                    metricsHtml += `<tr><th>${label}:</th><td>${value}</td></tr>`;
                }
            });
            
            metricsHtml += '</table>';
            resultsDiv.append(metricsHtml);
            
            if (results.file_name) {
                resultsDiv.append(`
                    <p><strong>Analyzed File:</strong> ${results.file_name}</p>
                    <p><strong>Modality:</strong> ${results.modality || 'N/A'}</p>
                `);
            }
            
            resultsDiv.append(`
                <small class="text-muted">
                    <i class="icon-clock"></i> ${new Date(results.timestamp).toLocaleString()}
                    | MRIQC version: ${results.mriqc_version || 'unknown'}
                </small>
            `);
        }
        
        itemView.$('.g-item-info').after(resultsDiv);
    }
};

export default ItemViewExtension;
