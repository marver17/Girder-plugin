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
     * Get volume with progress tracking
     * @param {Function} onProgress - Callback (loaded, total) => void
     * @returns {Promise<ArrayBuffer>}
     */
    getVolumeWithProgress: function (onProgress) {
        // If already cached, return immediately with full progress
        if (this._volumePromise && this._volumeCompleted) {
            return this._volumePromise.then((buffer) => {
                if (onProgress) {
                    onProgress(buffer.byteLength, buffer.byteLength);
                }
                return buffer;
            });
        }

        // Create new promise with progress tracking
        if (!this._volumePromise) {
            this._volumePromise = this._loadVolumeWithProgress(onProgress);
            this._volumePromise.then(() => {
                this._volumeCompleted = true;
            });
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
     * Load volume with progress tracking
     * @private
     * @param {Function} onProgress - Callback (loaded, total) => void
     * @returns {Promise<ArrayBuffer>}
     */
    _loadVolumeWithProgress: function (onProgress) {
        const fileId = this.get('_id') || this.id;

        if (!fileId) {
            return Promise.reject(new Error('File ID not provided'));
        }

        const url = `/api/v1/file/${fileId}/download`;

        return fetch(url, {
            method: 'GET',
            credentials: 'same-origin'
        })
            .then((response) => {
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }

                const contentLength = response.headers.get('Content-Length');
                const total = contentLength ? parseInt(contentLength, 10) : 0;

                if (!response.body || !onProgress || total === 0) {
                    // No progress tracking available, use simple arrayBuffer
                    return response.arrayBuffer();
                }

                // Stream with progress tracking
                const reader = response.body.getReader();
                const chunks = [];
                let loaded = 0;

                const read = () => {
                    return reader.read().then(({ done, value }) => {
                        if (done) {
                            // Combine all chunks
                            const allChunks = new Uint8Array(loaded);
                            let position = 0;
                            for (const chunk of chunks) {
                                allChunks.set(chunk, position);
                                position += chunk.length;
                            }
                            return allChunks.buffer;
                        }

                        chunks.push(value);
                        loaded += value.length;
                        onProgress(loaded, total);

                        return read();
                    });
                };

                return read();
            })
            .catch((error) => {
                // Clear cache on error so retry is possible
                this._volumePromise = null;
                this._volumeCompleted = false;
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
