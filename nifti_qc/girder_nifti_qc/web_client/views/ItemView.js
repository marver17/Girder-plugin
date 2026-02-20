import { restRequest } from '@girder/core/rest';
import events from '@girder/core/events';
import $ from 'jquery';

const ItemViewExtension = {
    /**
     * Add QC control buttons to item view
     */
    addQCButton(itemView) {
        const itemId = itemView.model.id;

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
            dialog.on('hidden.bs.modal', () => dialog.remove());

            ItemViewExtension.executeMRIQC(itemView, itemId, participantLabel, modality, timeout);
        });

        $('body').append(dialog);
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
     * Poll item for QC results.
     * When complete, updates the model and triggers a targeted UI update
     * without destroying the NIfTI viewer (no full itemView.render()).
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
                // Girder exposes metadata fields as top-level via exposeFields.
                // Fallback to item.meta if the server hasn't restarted yet.
                const status = item.nifti_qc_status || item.meta?.nifti_qc_status;
                const qcResults = item.nifti_qc_results || item.meta?.nifti_qc_results;
                console.log('[QC Poll] status:', status, '| nifti_qc_results:', qcResults, '| raw meta:', item.meta);

                if (status === 'completed' || status === 'quick_check_completed') {
                    // Update model with new fields (triggers Backbone change events)
                    // This triggers listenTo in NiftiView which calls _renderExtensionWidgets()
                    itemView.model.set({
                        nifti_qc_results: qcResults,
                        nifti_qc_status: status
                    });

                    events.trigger('g:alert', {
                        icon: 'ok',
                        text: 'Quality control completed!',
                        type: 'success',
                        timeout: 4000
                    });
                } else if (status === 'error') {
                    events.trigger('g:alert', {
                        icon: 'cancel',
                        text: 'QC processing failed. Check item metadata for details.',
                        type: 'danger',
                        timeout: 5000
                    });
                } else if (pollCount < maxPolls) {
                    // Continue polling: status is 'processing', undefined, or unknown
                    setTimeout(checkResults, interval);
                }
            });
        };

        setTimeout(checkResults, interval);
    },
    
};

export default ItemViewExtension;
