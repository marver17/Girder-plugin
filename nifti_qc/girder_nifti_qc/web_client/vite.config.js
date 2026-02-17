import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import { defineConfig } from 'vite';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// https://vitejs.dev/config/
export default defineConfig({
  build: {
    sourcemap: !process.env.SKIP_SOURCE_MAPS,
    lib: {
      entry: resolve(__dirname, 'main.js'),
      name: 'GirderPluginNiftiQC',
      fileName: 'nifti-qc',
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
            'backbone': 'Backbone',
            'underscore': '_',
            '@girder/core': 'girder',
          };
          return globalMap[id] || id;
        },
      },
    },
  },
});
