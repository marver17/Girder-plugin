import { getCurrentUser } from '@girder/core/auth';
import { AccessType } from '@girder/core/constants';
import events from '@girder/core/events';
import { restRequest } from '@girder/core/rest';
import { wrap } from '@girder/core/utilities/PluginUtils';

import ItemView from '@girder/core/views/body/ItemView';
import SearchFieldWidget from '@girder/core/views/widgets/SearchFieldWidget';

import NiftiView from './views/NiftiView';
import ParseNiftiItemTemplate from './templates/parseNiftiItem.pug';

wrap(ItemView, 'render', function (render) {
    this.once('g:rendered', () => {
        // Add a button to force NIfTI extraction
        if (this.model.get('_accessLevel') >= AccessType.WRITE) {
            this.$('.g-item-actions-menu').prepend(ParseNiftiItemTemplate({
                item: this.model,
                currentUser: getCurrentUser()
            }));
        }

        // If the item has NIfTI data, render the viewer
        if (this.model.has('nifti')) {
            new NiftiView({
                parentView: this,
                item: this.model
            })
                .render()
                .$el.insertAfter(this.$('.g-item-info'));
        }
    });
    return render.call(this);
});

ItemView.prototype.events['click .g-nifti-parse-item'] = function () {
    restRequest({
        method: 'POST',
        url: `item/${this.model.id}/parseNifti`,
        error: null
    })
        .done((resp) => {
            // Show success message
            events.trigger('g:alert', {
                icon: 'ok',
                text: 'NIfTI item parsed successfully.',
                type: 'success',
                timeout: 4000
            });
            
            // Reload the item to show the viewer
            this.model.fetch().done(() => {
                this.render();
            });
        })
        .fail((resp) => {
            // Show error message
            events.trigger('g:alert', {
                icon: 'cancel',
                text: resp.responseJSON.message || 'Failed to parse NIfTI item.',
                type: 'danger',
                timeout: 5000
            });
        });
};

SearchFieldWidget.addMode(
    'nifti',
    ['item'],
    'NIfTI metadata search',
    `You are searching for text in NIfTI metadata. Only Girder items which have been preprocessed to
        extract NIfTI images will be searched. The search text may appear anywhere within the metadata 
        keys or values of a NIfTI file.`
);
