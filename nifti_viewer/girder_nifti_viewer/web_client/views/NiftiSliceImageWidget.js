import View from '@girder/core/views/View';
import { Niivue } from '@niivue/niivue';

/**
 * Niivue-based widget for rendering NIfTI volumes.
 * Provides slice navigation, orientation control, and window/level adjustments.
 */
const NiftiSliceImageWidget = View.extend({
    className: 'g-nifti-slice-image',

    initialize: function (settings) {
        this.nv = null;
        this.volumeUrl = null;
        this.volumeName = null;
        this.volumeData = null;
        
        // View state
        this.currentOrientation = 'axial';
        this.currentSliceIndex = 0;
        this.maxSlices = { axial: 0, coronal: 0, sagittal: 0 };
        
        // Callbacks for parent view
        this.onSliceChange = settings.onSliceChange || null;
        this.onVolumeLoaded = settings.onVolumeLoaded || null;

        View.prototype.initialize.call(this, settings);
    },

    destroy: function () {
        if (this.nv) {
            // Cleanup Niivue instance
            this.nv = null;
        }
        View.prototype.destroy.apply(this, arguments);
    },

    /**
     * Set the volume URL for Niivue to load
     * @param {string} url - URL to the NIfTI file
     * @param {string} name - Name of the file (e.g., 'brain.nii.gz')
     */
    setVolumeUrl: function (url, name) {
        this.volumeUrl = url;
        this.volumeName = name || 'volume.nii.gz';
        return this;
    },

    /**
     * Set orientation (axial, coronal, sagittal)
     */
    setOrientation: function (orientation) {
        this.currentOrientation = orientation;
        if (this.nv && this.nv.volumes.length > 0) {
            this._applyOrientation();
        }
        return this;
    },

    /**
     * Set the current slice index
     */
    setSlice: function (sliceIndex) {
        this.currentSliceIndex = sliceIndex;
        if (this.nv && this.nv.volumes.length > 0) {
            this._applySlice();
        }
        return this;
    },

    /**
     * Set window level and width (contrast/brightness)
     */
    setWindowLevel: function (level, width) {
        if (this.nv && this.nv.volumes.length > 0) {
            const vol = this.nv.volumes[0];
            const min = level - width / 2;
            const max = level + width / 2;
            vol.cal_min = min;
            vol.cal_max = max;
            this.nv.updateGLVolume();
        }
        return this;
    },

    /**
     * Get volume header info
     */
    getVolumeInfo: function () {
        if (this.nv && this.nv.volumes.length > 0) {
            const vol = this.nv.volumes[0];
            return {
                dims: vol.dims,
                pixDims: vol.pixDims,
                dataType: vol.hdr ? vol.hdr.datatypeCode : null,
                cal_min: vol.cal_min,
                cal_max: vol.cal_max,
                global_min: vol.global_min,
                global_max: vol.global_max
            };
        }
        return null;
    },

    /**
     * Get maximum slices for each orientation
     */
    getMaxSlices: function () {
        return this.maxSlices;
    },

    /**
     * Render the viewer
     */
    render: function () {
        // Create canvas element for Niivue
        this.$el.empty();
        const canvas = document.createElement('canvas');
        canvas.id = 'nifti-canvas-' + Date.now();
        canvas.style.width = '512px';
        canvas.style.height = '512px';
        this.$el.append(canvas);

        // Initialize Niivue
        this.nv = new Niivue({
            backColor: [0.2, 0.2, 0.2, 1],
            show3Dcrosshair: false,
            crosshairColor: [1, 0, 0, 0.5],
            crosshairWidth: 1,
            multiplanarForceRender: false,
            sliceType: this._getSliceType(),
            isRadiologicalConvention: true,
            logging: false
        });

        this.nv.attachToCanvas(canvas);

        // Load volume if URL is set
        if (this.volumeUrl) {
            this._loadVolume();
        }

        return this;
    },

    /**
     * Load volume from URL
     */
    _loadVolume: function () {
        if (!this.nv || !this.volumeUrl) return;

        this.nv.loadVolumes([{ url: this.volumeUrl, name: this.volumeName }])
            .then(() => {
                if (this.nv.volumes.length > 0) {
                    const vol = this.nv.volumes[0];
                    
                    // Calculate max slices for each orientation
                    this.maxSlices = {
                        axial: vol.dims[3] || 1,
                        coronal: vol.dims[2] || 1,
                        sagittal: vol.dims[1] || 1
                    };

                    // Apply initial settings
                    this._applyOrientation();
                    
                    // Notify parent
                    if (this.onVolumeLoaded) {
                        this.onVolumeLoaded({
                            dims: vol.dims,
                            pixDims: vol.pixDims,
                            maxSlices: this.maxSlices,
                            cal_min: vol.cal_min,
                            cal_max: vol.cal_max,
                            global_min: vol.global_min,
                            global_max: vol.global_max
                        });
                    }
                }
            })
            .catch((error) => {
                console.error('Failed to load NIfTI volume:', error);
            });
    },

    /**
     * Apply the current orientation
     */
    _applyOrientation: function () {
        if (!this.nv) return;

        const sliceType = this._getSliceType();
        this.nv.setSliceType(sliceType);
        
        // Reset slice to middle of the new orientation
        const maxSlice = this.maxSlices[this.currentOrientation] || 1;
        this.currentSliceIndex = Math.floor(maxSlice / 2);
        this._applySlice();
    },

    /**
     * Apply the current slice
     */
    _applySlice: function () {
        if (!this.nv || this.nv.volumes.length === 0) return;

        const vol = this.nv.volumes[0];
        const maxSlice = this.maxSlices[this.currentOrientation] || 1;
        const frac = maxSlice > 1 ? this.currentSliceIndex / (maxSlice - 1) : 0.5;

        // Set crosshair position based on orientation
        switch (this.currentOrientation) {
            case 'axial':
                this.nv.scene.crosshairPos = [0.5, 0.5, frac];
                break;
            case 'coronal':
                this.nv.scene.crosshairPos = [0.5, frac, 0.5];
                break;
            case 'sagittal':
                this.nv.scene.crosshairPos = [frac, 0.5, 0.5];
                break;
        }
        
        this.nv.updateGLVolume();
    },

    /**
     * Get Niivue slice type from orientation string
     */
    _getSliceType: function () {
        // Niivue slice types: 0=axial, 1=coronal, 2=sagittal, 3=multiplanar, 4=render
        switch (this.currentOrientation) {
            case 'axial': return 0;
            case 'coronal': return 1;
            case 'sagittal': return 2;
            default: return 0;
        }
    },

    /**
     * Auto-adjust window/level based on image histogram
     */
    autoLevels: function () {
        if (this.nv && this.nv.volumes.length > 0) {
            const vol = this.nv.volumes[0];
            // Use robust min/max (2nd and 98th percentile would be ideal, but use global for simplicity)
            vol.cal_min = vol.global_min;
            vol.cal_max = vol.global_max;
            this.nv.updateGLVolume();
            
            return {
                level: (vol.cal_min + vol.cal_max) / 2,
                width: vol.cal_max - vol.cal_min
            };
        }
        return null;
    },

    /**
     * Zoom in
     */
    zoomIn: function () {
        if (this.nv) {
            const currentZoom = this.nv.uiData.pan2Dxyzmm[3] || 1;
            this.nv.uiData.pan2Dxyzmm[3] = currentZoom * 1.2;
            this.nv.drawScene();
        }
        return this;
    },

    /**
     * Zoom out
     */
    zoomOut: function () {
        if (this.nv) {
            const currentZoom = this.nv.uiData.pan2Dxyzmm[3] || 1;
            this.nv.uiData.pan2Dxyzmm[3] = currentZoom / 1.2;
            this.nv.drawScene();
        }
        return this;
    },

    /**
     * Reset zoom to default
     */
    resetZoom: function () {
        if (this.nv) {
            this.nv.uiData.pan2Dxyzmm = [0, 0, 0, 1];
            this.nv.drawScene();
        }
        return this;
    },

    /**
     * Navigate to next slice
     */
    nextSlice: function () {
        const maxSlice = this.maxSlices[this.currentOrientation] || 1;
        if (this.currentSliceIndex < maxSlice - 1) {
            this.currentSliceIndex++;
            this._applySlice();
        }
        return this.currentSliceIndex;
    },

    /**
     * Navigate to previous slice
     */
    previousSlice: function () {
        if (this.currentSliceIndex > 0) {
            this.currentSliceIndex--;
            this._applySlice();
        }
        return this.currentSliceIndex;
    },

    /**
     * Go to first slice
     */
    firstSlice: function () {
        this.currentSliceIndex = 0;
        this._applySlice();
        return this.currentSliceIndex;
    },

    /**
     * Go to last slice
     */
    lastSlice: function () {
        const maxSlice = this.maxSlices[this.currentOrientation] || 1;
        this.currentSliceIndex = maxSlice - 1;
        this._applySlice();
        return this.currentSliceIndex;
    },

    /**
     * Get current slice index
     */
    getCurrentSlice: function () {
        return this.currentSliceIndex;
    }
});

export default NiftiSliceImageWidget;
