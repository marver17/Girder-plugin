/**
 * routes.js – Registra la route di configurazione DIADEMA Pipeline
 *
 * Aggiunge il link "Configure" nella pagina dei plugin di Girder
 * (Amministrazione → Plugin → DIADEMA Pipeline → Configure)
 */

import events from '@girder/core/events';
import router from '@girder/core/router';
import { exposePluginConfig } from '@girder/core/utilities/PluginUtils';

import ConfigView from './views/ConfigView';

exposePluginConfig('diadema_pipeline', 'plugins/diadema_pipeline/config');

router.route('plugins/diadema_pipeline/config', 'diademaConfig', function () {
    events.trigger('g:navigateTo', ConfigView);
});
