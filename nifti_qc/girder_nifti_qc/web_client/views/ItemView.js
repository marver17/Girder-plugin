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
     * Infer BIDS parameters from item metadata.
     * Returns { participantLabel, modality, confident }
     * confident=true means both sub-label and modality extracted from BIDS filename → skip dialog
     */
    _inferMRIQCParams(itemView) {
        const item = itemView.model.toJSON();
        const nifti = item.nifti || item.meta?.nifti || {};
        const niftiMeta = nifti.meta || {};
        const jsonMeta = niftiMeta.json_metadata || {};
        const files = nifti.files || [];
        const fileName = files[0]?.name || item.name || '';

        // Participant label — always inferred automatically, never shown to user
        let participantLabel = '001';
        const subMatch = fileName.match(/sub-([a-zA-Z0-9]+)/i);
        if (subMatch) participantLabel = subMatch[1];
        const prevQC = item.nifti_qc_results || item.meta?.nifti_qc_results;
        if (prevQC?.participant_label) participantLabel = prevQC.participant_label;

        // Modality inference
        let modality = null;
        let confident = false;

        // 1. BIDS filename (most authoritative)
        const modalityMatch = fileName.match(/[_.]?(T1w|T2w|bold|dwi|FLAIR|T2star)[._]/i);
        if (modalityMatch) { modality = modalityMatch[1]; confident = true; }

        // 2. Previous QC result
        if (!modality && prevQC?.modality) modality = prevQC.modality;

        // 3. JSON sidecar metadata (ProtocolName / SeriesDescription)
        if (!modality) {
            const desc = (jsonMeta.ProtocolName || jsonMeta.SeriesDescription || '').toLowerCase();
            if (desc.match(/diff|dwi|dti/)) modality = 'dwi';
            else if (desc.match(/bold|fmri|func/)) modality = 'bold';
            else if (desc.match(/\bt2\b/)) modality = 'T2w';
            else if (desc.match(/\bt1\b/)) modality = 'T1w';
        }

        // 4. 4D + RepetitionTime heuristic → bold/fMRI
        if (!modality) {
            const dims = niftiMeta.dimensions || [];
            if (dims.length === 4 && dims[3] > 1 && jsonMeta.RepetitionTime) modality = 'bold';
        }

        if (!modality) modality = 'T1w';

        return { participantLabel, modality, confident };
    },

    /**
     * Run MRIQC: infer params from BIDS metadata.
     * If filename is BIDS-complete → run directly (no dialog).
     * Otherwise → show minimal modality selector pre-filled with inferred value.
     */
    runMRIQC(itemView, itemId) {
        const { participantLabel, modality, confident } = ItemViewExtension._inferMRIQCParams(itemView);
        const timeout = 1800;

        if (confident) {
            // BIDS filename complete — run directly without dialog
            events.trigger('g:alert', {
                icon: 'chart-bar',
                text: `Starting MRIQC (${modality})...`,
                type: 'info',
                timeout: 3000
            });
            ItemViewExtension.executeMRIQC(itemView, itemId, participantLabel, modality, timeout);
            return;
        }

        // Modality not certain — show minimal dialog with only modality selector
        const $j = window.jQuery;
        if (!$j) {
            // window.jQuery unavailable: run with inferred defaults
            ItemViewExtension.executeMRIQC(itemView, itemId, participantLabel, modality, timeout);
            return;
        }

        $j('#g-mriqc-dialog').remove();

        const $dialog = $j(`
            <div class="modal fade" tabindex="-1" id="g-mriqc-dialog">
                <div class="modal-dialog">
                    <div class="modal-content">
                        <div class="modal-header">
                            <button type="button" class="close" data-dismiss="modal">&times;</button>
                            <h4 class="modal-title">
                                <i class="icon-chart-bar"></i> MRIQC Quality Control
                            </h4>
                        </div>
                        <div class="modal-body">
                            <p>Select the MRI modality for this file:</p>
                            <div class="form-group">
                                <label>Modality</label>
                                <select class="form-control" id="g-mriqc-modality">
                                    <option value="T1w">T1-weighted (T1w)</option>
                                    <option value="T2w">T2-weighted (T2w)</option>
                                    <option value="bold">BOLD fMRI</option>
                                    <option value="dwi">Diffusion (DWI)</option>
                                </select>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-default" data-dismiss="modal">Cancel</button>
                            <button type="button" class="btn btn-primary" id="g-mriqc-run-btn">
                                <i class="icon-ok"></i> Run MRIQC
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `);

        // Pre-select inferred modality
        $dialog.find('#g-mriqc-modality').val(modality);

        $dialog.find('#g-mriqc-run-btn').on('click', () => {
            const mod = $dialog.find('#g-mriqc-modality').val();
            $dialog.modal('hide');
            ItemViewExtension.executeMRIQC(itemView, itemId, participantLabel, mod, timeout);
        });

        $j('body').append($dialog);
        $dialog.on('hidden.bs.modal', () => $dialog.remove());
        $dialog.modal('show');
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

        // Ripristina entrambi i bottoni al loro stato iniziale
        const resetButtons = () => {
            itemView.$('.g-nifti-qc-quick')
                .prop('disabled', false)
                .html('<i class="icon-flash"></i> Quick Check');
            itemView.$('.g-nifti-qc-mriqc')
                .prop('disabled', false)
                .html('<i class="icon-chart-bar"></i> Run MRIQC Quality Control');
            itemView.$('.g-qc-processing-badge').remove();
        };

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
                    resetButtons();
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
                    resetButtons();
                    events.trigger('g:alert', {
                        icon: 'cancel',
                        text: 'QC processing failed. Check item metadata for details.',
                        type: 'danger',
                        timeout: 5000
                    });
                } else if (pollCount < maxPolls) {
                    // Continue polling: status is 'processing', undefined, or unknown
                    setTimeout(checkResults, interval);
                } else {
                    // Timeout: max polls reached
                    resetButtons();
                    events.trigger('g:alert', {
                        icon: 'attention',
                        text: 'QC polling timeout. The job may still be running — check the Jobs panel.',
                        type: 'warning',
                        timeout: 8000
                    });
                }
            });
        };

        setTimeout(checkResults, interval);
    },
    
};

export default ItemViewExtension;
