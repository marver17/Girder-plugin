import { resolve } from 'path';
import { defineConfig } from 'vite';

function pugPlugin() {
  return {
    name: 'pug',
    transform(src: string, id: string) {
      if (id.endsWith('.pug')) {
        const { compileClient } = require('pug');
        return {
          code: `${compileClient(src, {filename: id})}\nexport default template`,
          map: null,
        };
      }
    },
  };
}

function stylusPlugin() {
  return {
    name: 'stylus',
    transform(src: string, id: string) {
      if (id.endsWith('.styl')) {
        const stylus = require('stylus');
        return new Promise((resolve, reject) => {
          stylus.render(src, { filename: id }, (err: Error, css: string) => {
            if (err) reject(err);
            else resolve({
              code: `const style = document.createElement('style');
style.textContent = ${JSON.stringify(css)};
document.head.appendChild(style);
export default style;`,
              map: null,
            });
          });
        });
      }
    },
  };
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    pugPlugin(),
    stylusPlugin(),
  ],
  build: {
    sourcemap: !process.env.SKIP_SOURCE_MAPS,
    lib: {
      entry: resolve(__dirname, 'main.js'),
      name: 'GirderPluginNiftiViewer',
      fileName: (format) => format === 'umd' ? 'girder-plugin-nifti-viewer.umd.cjs' : 'girder-plugin-nifti-viewer.js',
      formats: ['es', 'umd'],
    },
    rollupOptions: {
      external: [
        // Girder core modules should be external (provided by Girder)
        /^@girder\/.*/,
        // jQuery, Backbone, Underscore are provided by Girder
        'jquery',
        'backbone',
        'underscore',
      ],
      output: {
        globals: (id: string) => {
          // Map @girder/core imports to the global girder object
          if (id.startsWith('@girder/core/')) {
            const path = id.replace('@girder/core/', '');
            return `girder.${path.replace(/\//g, '.')}`;
          }
          // Map other globals
          const globalMap: Record<string, string> = {
            'jquery': 'jQuery',
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
