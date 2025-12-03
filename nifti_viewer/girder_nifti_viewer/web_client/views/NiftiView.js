import View from '@girder/core/views/View';
import { restRequest } from '@girder/core/rest';

import NiftiFileModel from '../models/NiftiFileModel';
import NiftiSliceImageWidget from './NiftiSliceImageWidget';
import { NIFTI_CONFIG } from '../constants/NiftiConfig';

import NiftiItemTemplate from '../templates/niftiItem.pug';
import '../stylesheets/niftiItem.styl';
import NiftiSliceMetadataTemplate from '../templates/niftiSliceMetadata.pug';
import '../stylesheets/niftiSliceMetadata.styl';

// Simple debounce function to avoid underscore dependency issues
function debounce(func, wait) {
    let timeout;
    return function (...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), wait);
    };
}

/**
 * Widget to display NIfTI metadata (similar to DICOM tags)
 */
const NiftiSliceMetadataWidget = View.extend({
    className: 'g-nifti-tags',

    initialize: function (settings) {
        this._metadata = null;
        this._volumeInfo = null;
        this._jsonMetadata = null;
    },

    setMetadata: function (metadata) {
        this._metadata = metadata;
        return this;
    },

    setVolumeInfo: function (volumeInfo) {
        this._volumeInfo = volumeInfo;
        return this;
    },

    setJsonMetadata: function (jsonMetadata) {
        this._jsonMetadata = jsonMetadata;
        return this;
    },

    render: function () {
        const tags = this._buildTagList();
        this.$el.html(NiftiSliceMetadataTemplate({ tags }));
        return this;
    },

    _buildTagList: function () {
        const tags = [];

        // Add NIfTI header info
        if (this._volumeInfo) {
            const vi = this._volumeInfo;
            
            if (vi.dims) {
                tags.push({ name: 'Dimensions', value: vi.dims.slice(1, 4).join(' × ') });
            }
            if (vi.pixDims) {
                tags.push({ name: 'Voxel Size (mm)', value: vi.pixDims.slice(1, 4).map(v => v.toFixed(2)).join(' × ') });
            }
            if (vi.maxSlices) {
                tags.push({ name: 'Axial Slices', value: vi.maxSlices.axial });
                tags.push({ name: 'Coronal Slices', value: vi.maxSlices.coronal });
                tags.push({ name: 'Sagittal Slices', value: vi.maxSlices.sagittal });
            }
            if (vi.global_min !== undefined && vi.global_max !== undefined) {
                tags.push({ name: 'Intensity Range', value: `${vi.global_min.toFixed(2)} - ${vi.global_max.toFixed(2)}` });
            }
        }

        // Add metadata from Girder item
        if (this._metadata) {
            for (const [key, value] of Object.entries(this._metadata)) {
                if (typeof value === 'object') continue;
                tags.push({ name: key, value: String(value) });
            }
        }

        // Add JSON sidecar metadata (BIDS format)
        if (this._jsonMetadata) {
            tags.push({ name: '--- JSON Metadata ---', value: '' });
            for (const [key, value] of Object.entries(this._jsonMetadata)) {
                if (typeof value === 'object' && !Array.isArray(value)) continue;
                let displayValue = Array.isArray(value) ? value.join(', ') : String(value);
                if (displayValue.length > 100) displayValue = displayValue.substring(0, 100) + '...';
                tags.push({ name: key, value: displayValue });
            }
        }

        return tags;
    }
});

/**
 * Main NIfTI viewer following DICOM viewer layout
 * Left side: image viewer with controls
 * Right side: metadata panel
 */
const NiftiView = View.extend({
    className: 'g-nifti-view',

    events: {
        // Slice navigation via slider
        'input .g-nifti-slider': '_onSliderInput',

        // Navigation buttons
        'click .g-nifti-first': '_firstSlice',
        'click .g-nifti-previous': '_previousSlice',
        'click .g-nifti-play': 'play',
        'click .g-nifti-pause': 'pause',
        'click .g-nifti-next': '_nextSlice',
        'click .g-nifti-last': '_lastSlice',

        // Zoom controls
        'click .g-nifti-zoom-in': '_zoomIn',
        'click .g-nifti-zoom-out': '_zoomOut',
        'click .g-nifti-reset-zoom': '_resetZoom',
        'click .g-nifti-auto-levels': '_autoLevels',

        // Window/Level controls
        'click .g-nifti-wl-header': '_toggleWindowLevelPanel',
        'input .g-nifti-window-slider': '_onWindowChange',
        'input .g-nifti-level-slider': '_onLevelChange',

        // Orientation buttons
        'click .g-nifti-orientation-btn': '_changeOrientation'
    },

    initialize: function (settings) {
        this.item = settings.item;
        this.parentView = settings.parentView;
        this.niftiInfo = this.item.get('nifti');

        // NiftiFileModel for cached volume loading
        this._niftiFileModel = null;

        // Volume and metadata state
        this._volumeInfo = null;
        this._jsonMetadata = null;

        // View widgets
        this._sliceImageWidget = null;
        this._sliceMetadataWidget = null;

        // Navigation state
        this._currentOrientation = 'axial';
        this._currentSlice = 0;
        this._maxSlices = 0;

        // Playback state
        this._playing = false;
        this._playInterval = NIFTI_CONFIG.PLAY_INITIAL_INTERVAL;
        this._playTimer = null;

        // Window/Level state
        this._currentWindow = 400;
        this._currentLevel = 50;
        this._windowLevelPanelVisible = false;

        // Create debounced slider handler
        this._debouncedSliderHandler = debounce((sliceIndex) => {
            this._setSlice(sliceIndex);
        }, NIFTI_CONFIG.SLIDER_DEBOUNCE_MS);

        // Create debounced window/level handlers
        this._debouncedWindowHandler = debounce((window) => {
            this._applyWindowLevel(this._currentLevel, window);
        }, 50);

        this._debouncedLevelHandler = debounce((level) => {
            this._applyWindowLevel(level, this._currentWindow);
        }, 50);
    },

    _onSliderInput: function (e) {
        const sliceIndex = parseInt(e.target.value);
        this._debouncedSliderHandler(sliceIndex);
    },

    render: function () {
        // Get total files info
        const files = this.niftiInfo.files || [];

        this.$el.html(NiftiItemTemplate({
            files: files,
            nifti: this.niftiInfo
        }));

        // Initialize metadata widget
        this._sliceMetadataWidget = new NiftiSliceMetadataWidget({
            el: this.$('.g-nifti-tags'),
            parentView: this
        });
        this._sliceMetadataWidget
            .setMetadata(this.niftiInfo.meta || {})
            .render();

        // Initialize image widget with Niivue
        this._sliceImageWidget = new NiftiSliceImageWidget({
            el: this.$('.g-nifti-image'),
            parentView: this,
            onVolumeLoaded: (volumeInfo) => this._onVolumeLoaded(volumeInfo),
            onSliceChange: (sliceIndex) => this._onSliceChangeFromWheel(sliceIndex)
        });

        // Get NIfTI file info
        const niftiFile = this.niftiInfo.files[0];
        const volumeName = niftiFile.name;

        // Create NiftiFileModel for cached loading
        this._niftiFileModel = new NiftiFileModel({ _id: niftiFile.id });

        // Show loading overlay
        this.$('.g-nifti-loading').show();
        this.$('.g-nifti-loading-filename').text(volumeName);
        this.$('.g-nifti-filename').text('Loading NIfTI file...');

        // Load volume using cached model with progress tracking
        this._niftiFileModel.getVolumeWithProgress((loaded, total) => {
            // Update progress bar
            if (total > 0) {
                const percent = Math.round((loaded / total) * 100);
                this.$('.g-nifti-progress-bar').css('width', percent + '%');
                const loadedMB = (loaded / 1024 / 1024).toFixed(1);
                const totalMB = (total / 1024 / 1024).toFixed(1);
                this.$('.g-nifti-progress-text').text(`${loadedMB} MB / ${totalMB} MB (${percent}%)`);
            }
        })
            .then((arrayBuffer) => {
                // Hide loading overlay
                this.$('.g-nifti-loading').hide();

                // Pass cached ArrayBuffer to widget for fast loading
                this._sliceImageWidget
                    .setVolumeBuffer(arrayBuffer, volumeName)
                    .render();
            })
            .catch((error) => {
                console.error('Failed to load NIfTI volume:', error);

                // Show detailed error message
                const errorMessage = this._getErrorMessage(error);
                this.$('.g-nifti-loading').html(`
                    <div class="alert alert-danger">
                        <i class="icon-warning-sign"></i>
                        <strong>Failed to load NIfTI file</strong>
                        <p>${errorMessage}</p>
                        <button class="btn btn-sm btn-primary g-nifti-retry">
                            <i class="icon-refresh"></i> Retry
                        </button>
                    </div>
                `);

                // Add retry handler
                this.$('.g-nifti-retry').on('click', () => {
                    this.render();
                });
            });

        // Load JSON sidecar if available
        this._loadJsonMetadata();

        return this;
    },

    _onVolumeLoaded: function (volumeInfo) {
        this._volumeInfo = volumeInfo;

        // Set initial max slices for current orientation
        this._maxSlices = volumeInfo.maxSlices[this._currentOrientation] || 1;
        this._currentSlice = Math.floor(this._maxSlices / 2);

        // Update UI controls
        this.$('.g-nifti-slider')
            .attr('max', this._maxSlices - 1)
            .val(this._currentSlice);
        this._updateSliceLabel();

        // Enable controls
        this._toggleControls(true);

        // Update metadata widget with volume info
        this._sliceMetadataWidget
            .setVolumeInfo(volumeInfo)
            .render();
    },

    _loadJsonMetadata: function () {
        // Look for JSON sidecar file
        const jsonFile = (this.niftiInfo.files || []).find(f => 
            f.name.endsWith('.json')
        );

        if (jsonFile) {
            restRequest({
                url: `file/${jsonFile.id}/download`,
                method: 'GET',
                error: null
            }).done((data) => {
                try {
                    this._jsonMetadata = typeof data === 'string' ? JSON.parse(data) : data;
                    this._sliceMetadataWidget
                        .setJsonMetadata(this._jsonMetadata)
                        .render();
                } catch (e) {
                    console.error('Failed to parse JSON metadata:', e);
                }
            });
        }
    },

    _setSlice: function (sliceIndex) {
        this._currentSlice = sliceIndex;
        if (this._sliceImageWidget) {
            this._sliceImageWidget.setSlice(sliceIndex);
        }
        this._updateSliceLabel();
    },

    _updateSliceLabel: function () {
        this.$('.g-nifti-filename').text(
            `${this._currentOrientation.charAt(0).toUpperCase() + this._currentOrientation.slice(1)}: ${this._currentSlice + 1} / ${this._maxSlices}`
        );
    },

    _toggleControls: function (enable) {
        this.$('.g-nifti-controls button').girderEnable(enable);
    },

    // Navigation methods
    _firstSlice: function () {
        this._setSlice(0);
        this.$('.g-nifti-slider').val(0);
    },

    _previousSlice: function () {
        let newSlice = this._currentSlice - 1;
        if (newSlice < 0) newSlice = this._maxSlices - 1;
        this._setSlice(newSlice);
        this.$('.g-nifti-slider').val(newSlice);
    },

    _nextSlice: function () {
        let newSlice = this._currentSlice + 1;
        if (newSlice >= this._maxSlices) newSlice = 0;
        this._setSlice(newSlice);
        this.$('.g-nifti-slider').val(newSlice);
    },

    _lastSlice: function () {
        this._setSlice(this._maxSlices - 1);
        this.$('.g-nifti-slider').val(this._maxSlices - 1);
    },

    // Playback methods
    play: function () {
        // CRITICAL FIX: Clear any existing timer to prevent memory leak
        if (this._playTimer) {
            clearTimeout(this._playTimer);
            this._playTimer = null;
        }

        if (this._playing) {
            // Speed up on repeated play clicks
            this._playInterval = Math.max(
                NIFTI_CONFIG.PLAY_MIN_INTERVAL,
                this._playInterval * NIFTI_CONFIG.PLAY_SPEED_FACTOR
            );
        } else {
            this._playing = true;
        }
        this._step();
    },

    pause: function () {
        this._playing = false;
        this._playInterval = NIFTI_CONFIG.PLAY_INITIAL_INTERVAL;
        if (this._playTimer) {
            clearTimeout(this._playTimer);
            this._playTimer = null;
        }
    },

    _step: function () {
        if (!this._playing) return;
        this._nextSlice();
        this._playTimer = setTimeout(() => this._step(), this._playInterval);
    },

    // Zoom methods
    _zoomIn: function () {
        if (this._sliceImageWidget) {
            this._sliceImageWidget.zoomIn();
        }
    },

    _zoomOut: function () {
        if (this._sliceImageWidget) {
            this._sliceImageWidget.zoomOut();
        }
    },

    _resetZoom: function () {
        if (this._sliceImageWidget) {
            this._sliceImageWidget.resetZoom();
        }
    },

    _autoLevels: function () {
        if (this._sliceImageWidget) {
            this._sliceImageWidget.autoLevels();
        }
    },

    // Orientation change
    _changeOrientation: function (e) {
        e.preventDefault();
        const $target = this.$(e.currentTarget);
        const newOrientation = $target.data('orientation');

        if (newOrientation !== this._currentOrientation) {
            this._currentOrientation = newOrientation;

            // Update button states
            this.$('.g-nifti-orientation-btn').removeClass('active');
            $target.addClass('active');

            // Update widget
            if (this._sliceImageWidget) {
                this._sliceImageWidget.setOrientation(newOrientation);

                // Get new max slices from widget
                const maxSlices = this._sliceImageWidget.getMaxSlices();
                this._maxSlices = maxSlices[newOrientation] || 1;
                this._currentSlice = this._sliceImageWidget.getCurrentSlice();

                // Update slider
                this.$('.g-nifti-slider')
                    .attr('max', this._maxSlices - 1)
                    .val(this._currentSlice);
            }

            this._updateSliceLabel();
        }
    },

    /**
     * Handle slice change from mouse wheel navigation
     * Updates slider and label to reflect Niivue's current position
     */
    _onSliceChangeFromWheel: function (sliceIndex) {
        this._currentSlice = sliceIndex;

        // Update slider position
        this.$('.g-nifti-slider').val(sliceIndex);

        // Update label
        this._updateSliceLabel();
    },

    // Window/Level controls
    _toggleWindowLevelPanel: function () {
        this._windowLevelPanelVisible = !this._windowLevelPanelVisible;

        const $controls = this.$('.g-nifti-wl-controls');
        const $toggleIcon = this.$('.g-nifti-wl-toggle i');

        if (this._windowLevelPanelVisible) {
            $controls.slideDown(200);
            $toggleIcon.removeClass('icon-angle-down').addClass('icon-angle-up');

            // Enable sliders
            this.$('.g-nifti-window-slider').prop('disabled', false);
            this.$('.g-nifti-level-slider').prop('disabled', false);
        } else {
            $controls.slideUp(200);
            $toggleIcon.removeClass('icon-angle-up').addClass('icon-angle-down');
        }
    },

    _onWindowChange: function (e) {
        const window = parseInt(e.target.value);
        this._currentWindow = window;
        this.$('.g-nifti-window-value').text(window);
        this._debouncedWindowHandler(window);
    },

    _onLevelChange: function (e) {
        const level = parseInt(e.target.value);
        this._currentLevel = level;
        this.$('.g-nifti-level-value').text(level);
        this._debouncedLevelHandler(level);
    },

    _applyWindowLevel: function (level, window) {
        if (this._sliceImageWidget) {
            this._sliceImageWidget.setWindowLevel(level, window);
        }
    },

    _getErrorMessage: function (error) {
        // Parse error and return user-friendly message
        const errorStr = error.message || error.toString();

        if (errorStr.includes('404') || errorStr.includes('Not Found')) {
            return 'File not found. The NIfTI file may have been deleted or moved.';
        }
        if (errorStr.includes('timeout') || errorStr.includes('Timeout')) {
            return 'Request timeout. The file is too large or the connection is slow. Please try again.';
        }
        if (errorStr.includes('NetworkError') || errorStr.includes('Failed to fetch')) {
            return 'Network error. Please check your internet connection and try again.';
        }
        if (errorStr.includes('403') || errorStr.includes('Forbidden')) {
            return 'Access denied. You do not have permission to view this file.';
        }
        if (errorStr.includes('500') || errorStr.includes('Internal Server Error')) {
            return 'Server error. Please contact your administrator.';
        }
        if (errorStr.includes('decode') || errorStr.includes('parse')) {
            return 'Invalid NIfTI file format. The file may be corrupted.';
        }

        // Default error message
        return `Error: ${errorStr}`;
    },

    destroy: function () {
        this.pause();

        if (this._sliceImageWidget) {
            this._sliceImageWidget.destroy();
        }
        if (this._sliceMetadataWidget) {
            this._sliceMetadataWidget.destroy();
        }

        // Clear cached volume if needed (optional - can keep for reuse)
        // Uncomment to free memory immediately:
        // if (this._niftiFileModel) {
        //     this._niftiFileModel.clearCache();
        // }

        View.prototype.destroy.apply(this, arguments);
    }
});

export default NiftiView;
