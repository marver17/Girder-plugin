import View from '@girder/core/views/View';
import { restRequest } from '@girder/core/rest';
import * as nifti from 'nifti-reader-js';
import pako from 'pako';

import NiftiItemTemplate from '../templates/niftiItem.pug';
import '../stylesheets/niftiItem.styl';
import NiftiSliceMetadataTemplate from '../templates/niftiSliceMetadata.pug';
import '../stylesheets/niftiSliceMetadata.styl';

const NiftiSliceMetadataWidget = View.extend({
    className: 'g-nifti-metadata',

    initialize: function (settings) {
        this._niftiData = settings.niftiData || {};
    },

    setMetadata: function (metadata) {
        this._niftiData = metadata;
        return this;
    },

    render: function () {
        this.$el.html(NiftiSliceMetadataTemplate({
            metadata: this._niftiData
        }));
        return this;
    }
});

const NiftiView = View.extend({
    className: 'g-nifti-viewer',

    events: {
        'change .g-nifti-orientation-btn': '_changeOrientation',
        'click .g-nifti-orientation-btn': '_changeOrientation',
        'input .g-nifti-slice-slider': '_changeSlice',
        'input .g-nifti-window-level': '_changeWindowLevel',
        'input .g-nifti-window-width': '_changeWindowWidth',
        'click .g-nifti-reset-view': '_resetView',
        'click .g-nifti-auto-window': '_autoWindow'
    },

    initialize: function (settings) {
        this.item = settings.item;
        this.parentView = settings.parentView;
        this.niftiInfo = this.item.get('nifti');
        this.niftiData = null;
        this.niftiHeader = null;
        this.niftiImage = null;
        this.jsonMetadata = null;
        this.currentOrientation = 'axial';
        this.currentSlice = 0;
        this.canvas = null;
        this.ctx = null;
        this.windowLevel = 500;
        this.windowWidth = 2000;
        this.dataMin = 0;
        this.dataMax = 0;
    },

    render: function () {
        this.$el.html(NiftiItemTemplate({
            item: this.item,
            nifti: this.niftiInfo
        }));

        // Setup metadata widget
        this.metadataWidget = new NiftiSliceMetadataWidget({
            el: this.$('.g-nifti-metadata-container'),
            parentView: this,
            niftiData: this.niftiInfo.meta
        });
        this.metadataWidget.render();

        // Setup canvas for 2D slice visualization
        const viewerContainer = this.$('.g-nifti-viewer-container');
        viewerContainer.html('<canvas class="g-nifti-canvas"></canvas><div class="g-nifti-loading">Loading NIfTI file...</div>');
        
        this.canvas = viewerContainer.find('canvas')[0];
        this.ctx = this.canvas.getContext('2d');

        // Load NIfTI file and JSON metadata if available
        this._loadNiftiFile();
        this._loadJsonMetadata();

        return this;
    },

    _loadJsonMetadata: function () {
        // Check if there's a JSON file (second file in the list)
        if (this.niftiInfo.files && this.niftiInfo.files.length > 1) {
            const jsonFile = this.niftiInfo.files.find(f => f.name.endsWith('.json'));
            if (jsonFile) {
                restRequest({
                    url: `file/${jsonFile.id}/download`,
                    method: 'GET',
                    error: null
                }).done((data) => {
                    try {
                        this.jsonMetadata = typeof data === 'string' ? JSON.parse(data) : data;
                        this._displayJsonMetadata();
                    } catch (e) {
                        console.error('Failed to parse JSON metadata:', e);
                    }
                });
            }
        }
    },

    _displayJsonMetadata: function () {
        if (this.jsonMetadata) {
            // Extract DICOM fields
            const dicomFields = this._extractDicomFields(this.jsonMetadata);
            
            if (Object.keys(dicomFields).length > 0) {
                // Create sections based on field categories
                const patientFields = {};
                const studyFields = {};
                const acquisitionFields = {};
                const otherFields = {};
                
                Object.entries(dicomFields).forEach(([key, value]) => {
                    if (key.includes('Patient')) {
                        patientFields[key] = value;
                    } else if (key.includes('Study')) {
                        studyFields[key] = value;
                    } else if (key.includes('Acquisition') || key.includes('Slice') || key.includes('Pixel') || key.includes('Orientation')) {
                        acquisitionFields[key] = value;
                    } else {
                        otherFields[key] = value;
                    }
                });
                
                const jsonSection = `
                    <div class="g-nifti-dicom-metadata">
                        <h5 class="g-nifti-metadata-title">
                            <i class="icon-doc-text"></i> DICOM Metadata
                        </h5>
                        <div class="g-nifti-metadata-grid">
                            ${this._createMetadataSection('Patient Information', 'icon-user', patientFields)}
                            ${this._createMetadataSection('Study Information', 'icon-folder', studyFields)}
                            ${this._createMetadataSection('Acquisition Parameters', 'icon-cog', acquisitionFields)}
                            ${Object.keys(otherFields).length > 0 ? this._createMetadataSection('Other Information', 'icon-info-circled', otherFields) : ''}
                        </div>
                    </div>
                `;
                
                this.$('.g-nifti-metadata-container').append(jsonSection);
            }
        }
    },
    
    _createMetadataSection: function (title, icon, fields) {
        if (Object.keys(fields).length === 0) return '';
        
        const rows = Object.entries(fields)
            .map(([key, value]) => `
                <tr>
                    <td class="g-nifti-meta-label">${key}</td>
                    <td class="g-nifti-meta-value">${this._escapeHtml(value)}</td>
                </tr>
            `)
            .join('');
        
        return `
            <div class="g-nifti-metadata-section">
                <h6 class="g-nifti-section-title">
                    <i class="${icon}"></i> ${title}
                </h6>
                <table class="g-nifti-metadata-table">
                    <tbody>
                        ${rows}
                    </tbody>
                </table>
            </div>
        `;
    },
    
    _escapeHtml: function (text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    _extractDicomFields: function (json) {
        const fields = {};
        
        // Common DICOM tags to display
        const commonTags = {
            'PatientName': 'Patient Name',
            'PatientID': 'Patient ID',
            'PatientBirthDate': 'Birth Date',
            'PatientSex': 'Sex',
            'StudyDate': 'Study Date',
            'StudyDescription': 'Study Description',
            'SeriesDescription': 'Series Description',
            'Modality': 'Modality',
            'Manufacturer': 'Manufacturer',
            'ManufacturerModelName': 'Model',
            'SliceThickness': 'Slice Thickness',
            'PixelSpacing': 'Pixel Spacing',
            'ImageOrientationPatient': 'Orientation',
            'AcquisitionDate': 'Acquisition Date',
            'AcquisitionTime': 'Acquisition Time'
        };

        // Extract fields from JSON
        for (const [tag, label] of Object.entries(commonTags)) {
            if (json[tag] !== undefined) {
                let value = json[tag];
                // Format arrays
                if (Array.isArray(value)) {
                    value = value.join(', ');
                }
                fields[label] = value;
            }
        }

        return fields;
    },

    _loadNiftiFile: function () {
        // Get the first file (the NIfTI file)
        const fileId = this.niftiInfo.files[0].id;
        
        // Download the file as ArrayBuffer
        restRequest({
            url: `file/${fileId}/download`,
            method: 'GET',
            error: null
        }).done((data) => {
            this._parseNiftiData(data);
        }).fail(() => {
            this.$('.g-nifti-loading').html('<span class="text-danger">Failed to load NIfTI file</span>');
        });
    },

    _parseNiftiData: function (data) {
        try {
            // Convert response to ArrayBuffer if needed
            let arrayBuffer;
            if (data instanceof ArrayBuffer) {
                arrayBuffer = data;
            } else if (typeof data === 'string') {
                // If it's a string, we need to fetch it properly
                this._loadNiftiFileAsArrayBuffer();
                return;
            } else {
                arrayBuffer = data;
            }

            // Check if compressed
            let niftiBuffer = arrayBuffer;
            if (nifti.isCompressed(arrayBuffer)) {
                niftiBuffer = nifti.decompress(arrayBuffer);
            }

            // Parse header
            if (nifti.isNIFTI(niftiBuffer)) {
                this.niftiHeader = nifti.readHeader(niftiBuffer);
                this.niftiImage = nifti.readImage(this.niftiHeader, niftiBuffer);
                
                this.$('.g-nifti-loading').hide();
                this._setupSliceViewer();
                this._renderSlice();
            } else {
                this.$('.g-nifti-loading').html('<span class="text-danger">Invalid NIfTI file format</span>');
            }
        } catch (error) {
            console.error('Error parsing NIfTI:', error);
            this.$('.g-nifti-loading').html('<span class="text-danger">Error parsing NIfTI file: ' + error.message + '</span>');
        }
    },

    _loadNiftiFileAsArrayBuffer: function () {
        const fileId = this.niftiInfo.files[0].id;
        
        fetch(`/api/v1/file/${fileId}/download`)
            .then(response => response.arrayBuffer())
            .then(arrayBuffer => {
                this._parseNiftiData(arrayBuffer);
            })
            .catch(error => {
                console.error('Error loading NIfTI:', error);
                this.$('.g-nifti-loading').html('<span class="text-danger">Failed to load NIfTI file</span>');
            });
    },

    _setupSliceViewer: function () {
        const dims = [this.niftiHeader.dims[1], this.niftiHeader.dims[2], this.niftiHeader.dims[3]];
        
        // Setup slider based on orientation
        const maxSlice = this._getMaxSliceForOrientation();
        this.$('.g-nifti-slice-slider').attr('max', maxSlice - 1);
        this.currentSlice = Math.floor(maxSlice / 2);
        this.$('.g-nifti-slice-slider').val(this.currentSlice);
        this._updateSliceLabel();
    },

    _getMaxSliceForOrientation: function () {
        switch (this.currentOrientation) {
            case 'axial':
                return this.niftiHeader.dims[3]; // Z dimension
            case 'coronal':
                return this.niftiHeader.dims[2]; // Y dimension
            case 'sagittal':
                return this.niftiHeader.dims[1]; // X dimension
            default:
                return this.niftiHeader.dims[3];
        }
    },

    _renderSlice: function () {
        const dims = [this.niftiHeader.dims[1], this.niftiHeader.dims[2], this.niftiHeader.dims[3]];
        let width, height, sliceData;

        // Get slice data based on orientation
        switch (this.currentOrientation) {
            case 'axial':
                width = dims[0];
                height = dims[1];
                sliceData = this._extractAxialSlice(this.currentSlice);
                break;
            case 'coronal':
                width = dims[0];
                height = dims[2];
                sliceData = this._extractCoronalSlice(this.currentSlice);
                break;
            case 'sagittal':
                width = dims[1];
                height = dims[2];
                sliceData = this._extractSagittalSlice(this.currentSlice);
                break;
        }

        // Set canvas size
        this.canvas.width = width;
        this.canvas.height = height;

        // Convert slice data to ImageData
        const imageData = this._createImageData(sliceData, width, height);
        this.ctx.putImageData(imageData, 0, 0);
    },

    _extractAxialSlice: function (sliceIndex) {
        const dims = [this.niftiHeader.dims[1], this.niftiHeader.dims[2], this.niftiHeader.dims[3]];
        const sliceSize = dims[0] * dims[1];
        const offset = sliceIndex * sliceSize;
        
        const typedData = this._getTypedData();
        return typedData.slice(offset, offset + sliceSize);
    },

    _extractCoronalSlice: function (sliceIndex) {
        const dims = [this.niftiHeader.dims[1], this.niftiHeader.dims[2], this.niftiHeader.dims[3]];
        const sliceData = new Float32Array(dims[0] * dims[2]);
        const typedData = this._getTypedData();
        
        for (let z = 0; z < dims[2]; z++) {
            for (let x = 0; x < dims[0]; x++) {
                const srcIndex = x + sliceIndex * dims[0] + z * dims[0] * dims[1];
                const dstIndex = x + z * dims[0];
                sliceData[dstIndex] = typedData[srcIndex];
            }
        }
        
        return sliceData;
    },

    _extractSagittalSlice: function (sliceIndex) {
        const dims = [this.niftiHeader.dims[1], this.niftiHeader.dims[2], this.niftiHeader.dims[3]];
        const sliceData = new Float32Array(dims[1] * dims[2]);
        const typedData = this._getTypedData();
        
        for (let z = 0; z < dims[2]; z++) {
            for (let y = 0; y < dims[1]; y++) {
                const srcIndex = sliceIndex + y * dims[0] + z * dims[0] * dims[1];
                const dstIndex = y + z * dims[1];
                sliceData[dstIndex] = typedData[srcIndex];
            }
        }
        
        return sliceData;
    },

    _getTypedData: function () {
        // Convert image data to appropriate typed array based on datatype
        const datatype = this.niftiHeader.datatypeCode;
        
        switch (datatype) {
            case 2: // unsigned char
                return new Uint8Array(this.niftiImage);
            case 4: // signed short
                return new Int16Array(this.niftiImage);
            case 8: // signed int
                return new Int32Array(this.niftiImage);
            case 16: // float
                return new Float32Array(this.niftiImage);
            case 64: // double
                return new Float64Array(this.niftiImage);
            default:
                return new Int16Array(this.niftiImage);
        }
    },

    _createImageData: function (sliceData, width, height) {
        const imageData = this.ctx.createImageData(width, height);
        
        // Apply windowing (window level and window width)
        const minWindow = this.windowLevel - (this.windowWidth / 2);
        const maxWindow = this.windowLevel + (this.windowWidth / 2);
        const windowRange = this.windowWidth || 1;
        
        for (let i = 0; i < sliceData.length; i++) {
            let value = sliceData[i];
            
            // Apply window level/width
            if (value <= minWindow) {
                value = 0;
            } else if (value >= maxWindow) {
                value = 255;
            } else {
                value = ((value - minWindow) / windowRange) * 255;
            }
            
            const pixelIndex = i * 4;
            imageData.data[pixelIndex] = value;     // R
            imageData.data[pixelIndex + 1] = value; // G
            imageData.data[pixelIndex + 2] = value; // B
            imageData.data[pixelIndex + 3] = 255;   // A
        }
        
        return imageData;
    },

    _changeOrientation: function (e) {
        e.preventDefault();
        const $target = this.$(e.currentTarget);
        const newOrientation = $target.data('orientation');
        
        if (newOrientation !== this.currentOrientation) {
            this.currentOrientation = newOrientation;
            
            // Update button states
            this.$('.g-nifti-orientation-btn').removeClass('active');
            $target.addClass('active');
            
            // Reset to middle slice
            const maxSlice = this._getMaxSliceForOrientation();
            this.currentSlice = Math.floor(maxSlice / 2);
            this.$('.g-nifti-slice-slider').attr('max', maxSlice - 1).val(this.currentSlice);
            
            this._updateSliceLabel();
            this._renderSlice();
        }
    },

    _changeSlice: function (e) {
        this.currentSlice = parseInt(this.$(e.currentTarget).val());
        this._updateSliceLabel();
        this._renderSlice();
    },

    _updateSliceLabel: function () {
        const maxSlice = this._getMaxSliceForOrientation();
        this.$('.g-nifti-slice-label').text(`Slice: ${this.currentSlice + 1} / ${maxSlice}`);
    },

    _changeWindowLevel: function (e) {
        this.windowLevel = parseInt(this.$(e.currentTarget).val());
        this.$('.g-nifti-level-value').text(this.windowLevel);
        this._renderSlice();
    },

    _changeWindowWidth: function (e) {
        this.windowWidth = parseInt(this.$(e.currentTarget).val());
        this.$('.g-nifti-width-value').text(this.windowWidth);
        this._renderSlice();
    },

    _autoWindow: function (e) {
        e.preventDefault();
        
        // Calculate optimal window level/width based on current slice data
        const typedData = this._getTypedData();
        
        // Calculate min/max for the entire volume
        let min = Infinity, max = -Infinity;
        for (let i = 0; i < typedData.length; i++) {
            if (typedData[i] < min) min = typedData[i];
            if (typedData[i] > max) max = typedData[i];
        }
        
        this.dataMin = min;
        this.dataMax = max;
        
        // Set window level to middle and width to full range
        this.windowLevel = Math.round((min + max) / 2);
        this.windowWidth = Math.round(max - min);
        
        // Update UI
        this.$('.g-nifti-window-level').val(this.windowLevel);
        this.$('.g-nifti-level-value').text(this.windowLevel);
        this.$('.g-nifti-window-width').val(this.windowWidth);
        this.$('.g-nifti-width-value').text(this.windowWidth);
        
        // Update slider ranges if needed
        if (min < -1000) {
            this.$('.g-nifti-window-level').attr('min', Math.floor(min));
        }
        if (max > 3000) {
            this.$('.g-nifti-window-level').attr('max', Math.ceil(max));
        }
        if ((max - min) > 4000) {
            this.$('.g-nifti-window-width').attr('max', Math.ceil(max - min));
        }
        
        this._renderSlice();
    },

    _resetView: function (e) {
        e.preventDefault();
        this.currentOrientation = 'axial';
        const maxSlice = this._getMaxSliceForOrientation();
        this.currentSlice = Math.floor(maxSlice / 2);
        
        this.$('.g-nifti-orientation-btn').removeClass('active');
        this.$('.g-nifti-orientation-btn[data-orientation="axial"]').addClass('active');
        this.$('.g-nifti-slice-slider').attr('max', maxSlice - 1).val(this.currentSlice);
        
        this._updateSliceLabel();
        this._renderSlice();
    }
});

export default NiftiView;
