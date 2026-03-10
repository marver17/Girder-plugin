/**
 * Vite config per Plugin Template
 * ──────────────────────────────────────────────────────────────────────────
 * Build in modalità library: genera un bundle UMD (per browser) e ESM.
 *
 * REGOLA CRITICA – external:
 *   Tutte le librerie fornite da Girder (@girder/core, backbone, underscore,
 *   jquery) DEVONO essere esternalizzate. In caso contrario vengono incluse
 *   nel bundle causando conflitti con le istanze già caricate da Girder
 *   (es. due istanze di Backbone → eventi non funzionano).
 * ──────────────────────────────────────────────────────────────────────────
 */

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
            name: 'GirderPluginTemplate',       // nome globale per il bundle UMD
            fileName: 'plugin-template',         // → plugin-template.js / plugin-template.umd.cjs
        },
        rollupOptions: {
            // Librerie fornite dall'host Girder: NON includere nel bundle
            external: [
                /^@girder\/.*/,   // @girder/core, @girder/jobs, ecc.
                'backbone',
                'underscore',
                'jquery',
                'handlebars',
                'bootstrap',
            ],
            output: {
                // Mappa i moduli esterni alle variabili globali presenti
                // nel contesto di esecuzione del browser (window.*)
                globals: {
                    '@girder/core/events':                    'girder.events',
                    '@girder/core/utilities/PluginUtils':     'girder.utilities.PluginUtils',
                    '@girder/core/views/body/ItemView':       'girder.views.body.ItemView',
                    backbone:   'Backbone',
                    underscore: '_',
                    jquery:     '$',
                },
            },
        },
    },
});
