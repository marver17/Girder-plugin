import Model from '@girder/core/models/Model';

/**
 * Model for NIfTI file with ArrayBuffer caching.
 * Downloads the file once and caches the ArrayBuffer for reuse.
 * Multiple calls to getVolume() return the same Promise to avoid race conditions.
 */
const NiftiFileModel = Model.extend({
    resourceName: 'file',

    /**
     * Get volume ArrayBuffer with caching.
     * Returns a Promise that resolves to an ArrayBuffer.
     * The promise is cached, so subsequent calls return the same promise.
     * @returns {Promise<ArrayBuffer>}
     */
    getVolume: function () {
        if (!this._volumePromise) {
            this._volumePromise = this._loadVolume();
        }
        return this._volumePromise;
    },

    /**
     * Internal method to download NIfTI file as ArrayBuffer.
     * @returns {Promise<ArrayBuffer>}
     * @private
     */
    _loadVolume: function () {
        const fileId = this.get('_id') || this.id;

        if (!fileId) {
            return Promise.reject(new Error('File ID not provided'));
        }

        // Use fetch API for binary data download
        return fetch(`/api/v1/file/${fileId}/download`, {
            method: 'GET',
            credentials: 'same-origin'
        })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.arrayBuffer();
        })
        .catch((error) => {
            // Clear cache on error so retry is possible
            this._volumePromise = null;
            throw error;
        });
    },

    /**
     * Clear cached volume data.
     * Useful for memory management when the file is no longer needed.
     */
    clearCache: function () {
        this._volumePromise = null;
    }
});

export default NiftiFileModel;
