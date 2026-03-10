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
            external: [
                /^@girder\/.*/,
                'backbone',
                'underscore',
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
                    };
                    return globalMap[id] || id;
                },
            },
        },
    },
});
