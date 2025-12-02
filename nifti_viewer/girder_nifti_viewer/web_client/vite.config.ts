import { resolve } from 'path';
import { defineConfig, PluginOption } from 'vite';
import fs from 'fs';

function pugPlugin(): PluginOption {
  return {
    name: 'pug',
    enforce: 'pre',
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

function stylusPlugin(): PluginOption {
  return {
    name: 'stylus',
    enforce: 'pre',
    async transform(code: string, id: string) {
      if (!id.endsWith('.styl')) return null;
      
      const stylus = require('stylus');
      
      const css: string = await new Promise((resolve, reject) => {
        stylus.render(code, { filename: id }, (err: Error, result: string) => {
          if (err) reject(err);
          else resolve(result);
        });
      });
      
      // Return as CSS that Vite will process natively
      return {
        code: css,
        map: null,
      };
    },
  };
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    pugPlugin(),
    stylusPlugin(),
  ],
  optimizeDeps: {
    include: ['@niivue/niivue']
  },
  define: {
    'global': 'globalThis',
  },
  css: {
    // Vite will inject CSS when importing
    devSourcemap: true,
  },
  build: {
    sourcemap: !process.env.SKIP_SOURCE_MAPS,
    chunkSizeWarningLimit: 1500,
    lib: {
      entry: resolve(__dirname, 'main.js'),
      name: 'GirderPluginNiftiViewer',
      fileName: (format) => format === 'umd' ? 'girder-plugin-nifti-viewer.umd.cjs' : 'girder-plugin-nifti-viewer.js',
      formats: ['es', 'umd'],
    },
    rollupOptions: {
      external: [
        /^@girder\/.*/,
        'jquery',
        'backbone',
        'underscore',
      ],
      output: {
        globals: (id: string) => {
          if (id.startsWith('@girder/core/')) {
            const path = id.replace('@girder/core/', '');
            return `girder.${path.replace(/\//g, '.')}`;
          }
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
