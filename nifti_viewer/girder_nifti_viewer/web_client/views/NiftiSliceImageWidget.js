import View from '@girder/core/views/View';
import { Niivue } from '@niivue/niivue';
import { NIFTI_CONFIG } from '../constants/NiftiConfig';

/**
 * Niivue-based widget for rendering NIfTI volumes.
 * Provides slice navigation, orientation control, and window/level adjustments.
 */
const NiftiSliceImageWidget = View.extend({
    className: 'g-nifti-slice-image',

    initialize: function (settings) {
        this.nv = null;
        this.volumeUrl = null;
        this.volumeBuffer = null;  // ArrayBuffer for cached loading
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
            // FIX: Properly cleanup Niivue volumes usando removeVolumeByIndex
            if (this.nv.volumes && this.nv.volumes.length > 0) {
                // Rimuovi tutti i volumi dalla fine all'inizio
                for (let i = this.nv.volumes.length - 1; i >= 0; i--) {
                    try {
                        this.nv.removeVolumeByIndex(i);
                    } catch (e) {
                        console.warn('Error removing volume:', e);
                    }
                }
            }
            this.nv = null;
        }

        // CRITICAL FIX: Explicitly cleanup canvas to prevent memory leak
        const canvas = this.el.querySelector('canvas');
        if (canvas) {
            // Force canvas cleanup by resetting dimensions
            canvas.width = 0;
            canvas.height = 0;
            canvas.remove();
        }

        // Clear buffer reference for GC
        this.volumeBuffer = null;
        View.prototype.destroy.apply(this, arguments);
    },

    /**
     * Set the volume URL for Niivue to load
     * @param {string} url - URL to the NIfTI file
     * @param {string} name - Name of the file (e.g., 'brain.nii.gz')
     */
    setVolumeUrl: function (url, name) {
        this.volumeUrl = url;
        this.volumeBuffer = null;  // Clear buffer if using URL
        this.volumeName = name || 'volume.nii.gz';
        return this;
    },

    /**
     * Set the volume from an ArrayBuffer (preferred for caching)
     * @param {ArrayBuffer} buffer - ArrayBuffer containing NIfTI data
     * @param {string} name - Name of the file (e.g., 'brain.nii.gz')
     */
    setVolumeBuffer: function (buffer, name) {
        this.volumeBuffer = buffer;
        this.volumeUrl = null;  // Clear URL if using buffer
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
            backColor: NIFTI_CONFIG.CANVAS_BG_COLOR,
            show3Dcrosshair: false,
            crosshairColor: [0, 0, 0, 0],  // Alpha = 0 per nascondere completamente il crosshair
            crosshairWidth: 0,
            multiplanarForceRender: false,
            sliceType: this._getSliceType(),
            isRadiologicalConvention: true,
            logging: false,
            // FIX: Usa dragMode pan per permettere spostamento con tasto destro
            // 0 = none, 1 = contrast (windowing), 2 = measurement, 3 = pan
            dragMode: 3  // pan mode: tasto destro sposta l'immagine senza windowing
        });

        this.nv.attachToCanvas(canvas);

        // Previeni il menu contestuale del browser sul tasto destro
        canvas.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            return false;
        });

        // Load volume if buffer or URL is set (prefer buffer for caching)
        if (this.volumeBuffer || this.volumeUrl) {
            this._loadVolume();
        }

        return this;
    },

    /**
     * Load volume from ArrayBuffer or URL
     * Prefers ArrayBuffer (cached) over URL loading
     */
    _loadVolume: function () {
        if (!this.nv) return;

        let loadPromise;

        // Prefer ArrayBuffer loading (cached) over URL
        if (this.volumeBuffer) {
            // Load from cached ArrayBuffer
            loadPromise = this.nv.loadFromArrayBuffer(this.volumeBuffer, this.volumeName);
        } else if (this.volumeUrl) {
            // Fallback to URL loading
            loadPromise = this.nv.loadVolumes([{ url: this.volumeUrl, name: this.volumeName }]);
        } else {
            return;
        }

        loadPromise
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
     * Auto-adjust window/level based on image histogram with percentiles
     */
    autoLevels: function () {
        if (this.nv && this.nv.volumes.length > 0) {
            const vol = this.nv.volumes[0];

            let min, max;

            // FIX: Calcola percentili per un contrasto migliore
            if (vol.img && vol.img.length > 1000) {
                // Campiona i voxel per performance (ogni N voxel)
                const sampleRate = Math.max(1, Math.floor(vol.img.length / NIFTI_CONFIG.AUTO_LEVEL_SAMPLE_RATE));
                const samples = [];

                for (let i = 0; i < vol.img.length; i += sampleRate) {
                    const value = vol.img[i];
                    if (!isNaN(value) && isFinite(value)) {
                        samples.push(value);
                    }
                }

                if (samples.length > 10) {
                    // Ordina e trova percentili
                    samples.sort((a, b) => a - b);
                    const p2Idx = Math.floor(samples.length * NIFTI_CONFIG.AUTO_LEVEL_PERCENTILE_LOW);
                    const p98Idx = Math.floor(samples.length * NIFTI_CONFIG.AUTO_LEVEL_PERCENTILE_HIGH);

                    min = samples[p2Idx];
                    max = samples[p98Idx];
                } else {
                    // Fallback se non ci sono abbastanza samples
                    min = vol.global_min;
                    max = vol.global_max;
                }
            } else {
                // Fallback: usa global_min/max con margine del 5%
                const range = vol.global_max - vol.global_min;
                min = vol.global_min + range * 0.05;
                max = vol.global_max - range * 0.05;
            }

            // Evita min == max
            if (min >= max) {
                min = vol.global_min;
                max = vol.global_max;
            }

            vol.cal_min = min;
            vol.cal_max = max;
            this.nv.updateGLVolume();

            return {
                level: (min + max) / 2,
                width: max - min
            };
        }
        return null;
    },

    /**
     * Zoom in
     */
    zoomIn: function () {
        if (this.nv) {
            // FIX: Per le slice 2D, Niivue usa pan2Dxyzmm[3] per lo zoom
            // setScale() è solo per il rendering 3D
            const currentZoom = this.nv.scene.pan2Dxyzmm[3];
            this.nv.scene.pan2Dxyzmm[3] = currentZoom * NIFTI_CONFIG.ZOOM_IN_FACTOR;
            this.nv.drawScene();
        }
        return this;
    },

    /**
     * Zoom out
     */
    zoomOut: function () {
        if (this.nv) {
            // FIX: Per le slice 2D, Niivue usa pan2Dxyzmm[3] per lo zoom
            const currentZoom = this.nv.scene.pan2Dxyzmm[3];
            this.nv.scene.pan2Dxyzmm[3] = currentZoom * NIFTI_CONFIG.ZOOM_OUT_FACTOR;
            this.nv.drawScene();
        }
        return this;
    },

    /**
     * Reset zoom to default
     */
    resetZoom: function () {
        if (this.nv) {
            // FIX: Reset zoom 2D a 1.0 e ripristina anche la posizione (pan)
            // pan2Dxyzmm = [x, y, z, zoom]
            // Resetta tutto a [0, 0, 0, 1.0]
            this.nv.scene.pan2Dxyzmm = [0, 0, 0, 1.0];
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
