/**
 * Configuration constants for NIfTI Viewer
 * Centralizes all magic numbers and configuration values
 */

export const NIFTI_CONFIG = {
    // Canvas dimensions
    CANVAS_WIDTH: 512,
    CANVAS_HEIGHT: 512,
    CANVAS_BG_COLOR: [0.2, 0.2, 0.2, 1],

    // Playback settings
    PLAY_INITIAL_INTERVAL: 500,  // milliseconds between frames
    PLAY_MIN_INTERVAL: 50,        // fastest playback speed
    PLAY_SPEED_FACTOR: 0.5,       // speed multiplier on repeated play clicks

    // UI responsiveness
    SLIDER_DEBOUNCE_MS: 50,       // debounce time for slice slider

    // Zoom settings
    ZOOM_IN_FACTOR: 1.2,          // zoom in multiplier
    ZOOM_OUT_FACTOR: 0.8,         // zoom out multiplier
    ZOOM_DEFAULT: [0, 0, 0, 1],   // default pan/zoom state

    // Network/Loading
    LOAD_TIMEOUT_MS: 30000,       // 30 seconds timeout for file loading

    // Crosshair
    CROSSHAIR_COLOR: [1, 0, 0, 0.5],  // red with 50% opacity
    CROSSHAIR_WIDTH: 1,
    CROSSHAIR_VISIBLE: false,

    // Window/Level Presets (for future implementation)
    WINDOW_LEVEL_PRESETS: {
        default: { level: 50, width: 400 },
        brain: { level: 40, width: 80 },
        bone: { level: 700, width: 400 },
        lung: { level: -500, width: 1500 },
        abdomen: { level: 60, width: 360 },
        liver: { level: 80, width: 150 },
    },

    // Orientation modes
    ORIENTATIONS: {
        AXIAL: 'axial',
        CORONAL: 'coronal',
        SAGITTAL: 'sagittal'
    },

    // Niivue slice type mappings
    SLICE_TYPES: {
        axial: 0,
        coronal: 1,
        sagittal: 2,
        multiplanar: 3,
        render: 4
    }
};

export default NIFTI_CONFIG;
