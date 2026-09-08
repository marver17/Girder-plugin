import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import { defineConfig } from 'vite';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

export default defineConfig({
    build: {
        sourcemap: !process.env.SKIP_SOURCE_MAPS,
        lib: {
            entry: resolve(__dirname, 'main.js'),
            name: 'GirderDiademaPipeline',
            fileName: 'diadema-pipeline',
        },
        rollupOptions: {
            // jquery è esterno come in nifti_viewer: le modali usano i plugin
            // jQuery registrati da Girder/Bootstrap (.girderModal, .modal), che
            // vivono sull'istanza globale. Bundlarne una copia darebbe un
            // oggetto senza quei metodi.
            external: [
                /^@girder\/.*/,
                'backbone',
                'underscore',
                'jquery',
            ],
            output: {
                globals: (id) => {
                    if (id.startsWith('@girder/core/')) {
                        const path = id.replace('@girder/core/', '');
                        return `girder.${path.replace(/\//g, '.')}`;
                    }
                    const globalMap = {
                        '@girder/core': 'girder',
                        'backbone':     'Backbone',
                        'underscore':   '_',
                        'jquery':       'jQuery',
                    };
                    return globalMap[id] || id;
                },
            },
        },
    },
});
