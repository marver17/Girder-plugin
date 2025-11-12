import ConfigViewTemplate from '../templates/configView.pug';
import '../stylesheets/configView.styl';

const $ = girder.$;
const _ = girder._;

const PluginConfigBreadcrumbWidget = girder.views.widgets.PluginConfigBreadcrumbWidget;
const View = girder.views.View;
const { getApiRoot, restRequest } = girder.rest;
const events = girder.events;


//TODO fix icon for keycloak

var ConfigView = View.extend({
    events: {
        'submit .g-oauth-provider-form': function (event) {
            event.preventDefault();
            var providerId = $(event.target).attr('provider-id');
            this.$('#g-oauth-provider-' + providerId + '-error-message').empty();
            const settings = [{
                key: 'oauth.' + providerId + '_client_id',
                value: this.$('#g-oauth-provider-' + providerId + '-client-id').val().trim()
            }, {
                key: 'oauth.' + providerId + '_client_secret',
                value: this.$('#g-oauth-provider-' + providerId + '-client-secret').val().trim()
            }];
            if (_.findWhere(this.providers, { id: providerId }).takesTenantId) {
                settings.push({
                    key: 'oauth.' + providerId + '_tenant_id',
                    value: this.$('#g-oauth-provider-' + providerId + '-tenant-id').val().trim()
                });
            }
            if (_.findWhere(this.providers, { id: providerId }).isKeycloak) {
                settings.push({
                    key: 'oauth.' + providerId + '_server_url',
                    value: this.$('#g-oauth-provider-' + providerId + '-server-url').val().trim()
                });
                settings.push({
                    key: 'oauth.' + providerId + '_provider_url',
                    value: this.$('#g-oauth-provider-' + providerId + '-provider-url').val().trim()
                });
                settings.push({
                    key: 'oauth.' + providerId + '_realm',
                    value: this.$('#g-oauth-provider-' + providerId + '-realm').val().trim()
                });
            }
            this._saveSettings(providerId, settings);
        },

        'change .g-ignore-registration-policy': function (event) {
            restRequest({
                method: 'PUT',
                url: 'system/setting',
                data: {
                    key: 'oauth.ignore_registration_policy',
                    value: $(event.target).is(':checked')
                }
            }).done(() => {
                events.trigger('g:alert', {
                    icon: 'ok',
                    text: 'Setting saved.',
                    type: 'success',
                    timeout: 3000
                });
            });
        }
    },

    initialize: function () {
        this.providers = [{
            id: 'google',
            name: 'Google',
            icon: 'google',
            hasAuthorizedOrigins: true,
            takesTenantId: false,
            instructions: 'Client IDs and secret keys are managed in the Google ' +
                          'Developer Console. When creating your client ID there, ' +
                          'use the following values:'
        }, {
            id: 'globus',
            name: 'Globus',
            icon: 'globe',
            hasAuthorizedOrigins: false,
            takesTenantId: false,
            instructions: 'Client IDs and secret keys are managed in the Google ' +
                          'Developer Console. When creating your client ID there, ' +
                          'use the following values:'
        }, {
            id: 'github',
            name: 'GitHub',
            icon: 'github-circled',
            hasAuthorizedOrigins: false,
            takesTenantId: false,
            instructions: 'Client IDs and secret keys are managed in the ' +
                          'Applications page of your GitHub account settings. ' +
                          'Use the following as the authorization callback URL:'
        }, {
            id: 'bitbucket',
            name: 'Bitbucket',
            icon: 'bitbucket',
            hasAuthorizedOrigins: false,
            takesTenantId: false,
            instructions: 'Client IDs and secret keys are managed in the ' +
                          'Applications page of your Bitbucket account settings. ' +
                          'Use the following as the authorization callback URL:'
        }, {
            id: 'microsoft',
            name: 'Microsoft',
            icon: 'microsoft',
            hasAuthorizedOrigins: false,
            takesTenantId: true,
            instructions: 'Application (client) ID and secret keys can be found ' +
                          'at the "Overview" and "Certificates & secrets" sections ' +
                          'of the Azure application website. Select the "User.Read" ' +
                          'permission under "API permissions - Microsoft Graph - ' +
                          'Delegated permissions" and add this callback URL to the ' +
                          '"Redirect URIs" under "Authentication":'
        }, {
            id: 'linkedin',
            name: 'LinkedIn',
            icon: 'linkedin',
            hasAuthorizedOrigins: false,
            takesTenantId: false,
            instructions: 'Client IDs and secret keys are managed at the ' +
                          'Applications page of the LinkedIn Developers site. ' +
                          'Select the "r_basicprofile" and "r_emailaddress" ' +
                          'Default Application Permissions, and use the ' +
                          'following as an OAuth 2.0 Authorized Redirect URL:'
        }, {
            id: 'box',
            name: 'Box',
            icon: 'box-brand',
            hasAuthorizedOrigins: false,
            takesTenantId: false,
            instructions: 'Client IDs and secret keys are managed in the Box ' +
                          'Developer Services page. When creating your client ID ' +
                          'there, use the following as the authorization callback URL:'
        }, {
            id: 'cilogon',
            name: 'CILogon',
            icon: 'cilogon',
            hasAuthorizedOrigins: false,
            takesTenantId: false,
            instructions: 'Client IDs and secret keys are managed through the CILogon ' +
                          'Client Registration page. When creating your client ID ' +
                          'there, use the following as the authorization callback URL:'
        }, {
            id: 'keycloak',
            name: 'Keycloak',
            icon: 'keycloak-icon',
            hasAuthorizedOrigins: false,
            takesTenantId: false,
            isKeycloak: true,
            instructions: 'Client ID and Secret are managed in your Keycloak realm. ' +
                          'Use the following as an authorized redirect URI:'
        }];
        this.providerIds = _.pluck(this.providers, 'id');

        var settingKeys = ['oauth.ignore_registration_policy'];
        _.each(this.providerIds, function (id) {
            settingKeys.push('oauth.' + id + '_client_id');
            settingKeys.push('oauth.' + id + '_client_secret');
            if (_.findWhere(this.providers, { id: id }).takesTenantId) {
                settingKeys.push('oauth.' + id + '_tenant_id');
            }
            if (_.findWhere(this.providers, { id: id }).isKeycloak) {
                settingKeys.push('oauth.' + id + '_server_url');
                settingKeys.push('oauth.' + id + '_provider_url');
                settingKeys.push('oauth.' + id + '_realm');
            }
        }, this);

        restRequest({
            method: 'GET',
            url: 'system/setting',
            data: {
                list: JSON.stringify(settingKeys)
            }
        }).done((resp) => {
            this.settingVals = resp;
            this.render();
        });
    },

    render: function () {
        var origin = window.location.protocol + '//' + window.location.host,
            _apiRoot = getApiRoot();

        if (_apiRoot.substring(0, 1) !== '/') {
            _apiRoot = '/' + _apiRoot;
        }

        this.$el.html(ConfigViewTemplate({
            origin: origin,
            apiRoot: _apiRoot,
            providers: this.providers
        }));

        if (!this.breadcrumb) {
            this.breadcrumb = new PluginConfigBreadcrumbWidget({
                pluginName: 'OAuth login',
                el: this.$('.g-config-breadcrumb-container'),
                parentView: this
            }).render();
        }

        if (this.settingVals) {
            _.each(this.providerIds, function (id) {
                this.$('#g-oauth-provider-' + id + '-client-id').val(
                    this.settingVals['oauth.' + id + '_client_id']);
                this.$('#g-oauth-provider-' + id + '-client-secret').val(
                    this.settingVals['oauth.' + id + '_client_secret']);
                if (_.findWhere(this.providers, { id: id }).takesTenantId) {
                    this.$('#g-oauth-provider-' + id + '-tenant-id').val(
                        this.settingVals['oauth.' + id + '_tenant_id']);
                }
                if (_.findWhere(this.providers, { id: id }).isKeycloak) {
                    this.$('#g-oauth-provider-' + id + '-server-url').val(
                        this.settingVals['oauth.' + id + '_server_url']);
                    this.$('#g-oauth-provider-' + id + '-provider-url').val(
                        this.settingVals['oauth.' + id + '_provider_url']);
                    this.$('#g-oauth-provider-' + id + '-realm').val(
                        this.settingVals['oauth.' + id + '_realm']);
                }
            }, this);

            var checked = this.settingVals['oauth.ignore_registration_policy'];
            this.$('.g-ignore-registration-policy').attr('checked', checked ? 'checked' : null);
        }

        return this;
    },

    _saveSettings: function (providerId, settings) {
        var allSettings = [];
        var enabledProviders = [];

        _.each(this.providerIds, function (id) {
            var clientId = this.$('#g-oauth-provider-' + id + '-client-id').val().trim();
            var clientSecret = this.$('#g-oauth-provider-' + id + '-client-secret').val().trim();

            if (id === 'keycloak') {
                var serverUrl = this.$('#g-oauth-provider-' + id + '-server-url').val().trim();
                var realm = this.$('#g-oauth-provider-' + id + '-realm').val().trim();
                if (clientId && serverUrl && realm) {
                    enabledProviders.push(id);
                }
            } else if (clientId) {
                enabledProviders.push(id);
            }

            allSettings.push({ key: 'oauth.' + id + '_client_id', value: clientId });
            allSettings.push({ key: 'oauth.' + id + '_client_secret', value: clientSecret });

            if (_.findWhere(this.providers, { id: id }).takesTenantId) {
                var tenantId = this.$('#g-oauth-provider-' + id + '-tenant-id').val().trim();
                allSettings.push({ key: 'oauth.' + id + '_tenant_id', value: tenantId });
            }
            if (_.findWhere(this.providers, { id: id }).isKeycloak) {
                var serverUrl = this.$('#g-oauth-provider-' + id + '-server-url').val().trim();
                var providerUrl = this.$('#g-oauth-provider-' + id + '-provider-url').val().trim();
                var realm = this.$('#g-oauth-provider-' + id + '-realm').val().trim();
                allSettings.push({ key: 'oauth.' + id + '_server_url', value: serverUrl });
                allSettings.push({ key: 'oauth.' + id + '_provider_url', value: providerUrl });
                allSettings.push({ key: 'oauth.' + id + '_realm', value: realm });
            }
        }, this);

        allSettings.push({
            key: 'oauth.providers_enabled',
            value: enabledProviders
        });

        restRequest({
            method: 'PUT',
            url: 'system/setting',
            data: {
                list: JSON.stringify(allSettings)
            },
            error: null
        }).done(() => {
            events.trigger('g:alert', {
                icon: 'ok',
                text: 'Settings saved.',
                type: 'success',
                timeout: 3000
            });
        }).fail((resp) => {
            console.error('Error saving settings:', resp);
            this.$('#g-oauth-provider-' + providerId + '-error-message').text(
                resp.responseJSON.message);
        });
    }
});

export default ConfigView;
