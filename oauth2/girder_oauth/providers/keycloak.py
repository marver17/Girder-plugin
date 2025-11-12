import warnings
from contextlib import contextmanager
from urllib.parse import quote, urlparse

from girder.api.rest import getApiUrl
from girder.exceptions import RestException
from girder.models.setting import Setting

import jwt

from ..settings import PluginSettings
from .base import ProviderBase

try:
    from keycloak import KeycloakOpenID
except ImportError:
    KeycloakOpenID = None


# TODO add optional TLS verification settings
class Keycloak(ProviderBase):
    _AUTH_SCOPES = ['openid', 'email', 'profile']

    def getClientIdSetting(self):
        return Setting().get(PluginSettings.KEYCLOAK_CLIENT_ID)

    def getClientSecretSetting(self):
        return Setting().get(PluginSettings.KEYCLOAK_CLIENT_SECRET)

    def getRealm(self):
        return Setting().get(PluginSettings.KEYCLOAK_REALM)

    def getKeycloakServerUrl(self):
        return Setting().get(PluginSettings.KEYCLOAK_SERVER_URL)

    def _getHostHeader(self):
        serverUrl = self.getKeycloakServerUrl()
        if not serverUrl:
            return None
        parsed = urlparse(serverUrl)
        # urlparse returns empty netloc when schema missing; fall back to path
        return parsed.netloc or parsed.path or None

    @contextmanager
    def _overrideHostHeader(self, connection):
        host_header = self._getHostHeader()
        if not host_header:
            yield
            return

        previous = connection.headers.get('Host')
        connection.headers['Host'] = host_header
        try:
            print(f"[DEBUG] Overriding Host header to: {host_header}")
            yield
        finally:
            if previous is None:
                connection.headers.pop('Host', None)
            else:
                connection.headers['Host'] = previous
            print("[DEBUG] Restored previous Host header")

    @classmethod
    def getUrl(cls, state):
        if KeycloakOpenID is None:
            warnings.warn(
                'python-keycloak is not installed, Keycloak provider will be unavailable.')
            return None

        clientId = Setting().get(PluginSettings.KEYCLOAK_CLIENT_ID)
        realm = Setting().get(PluginSettings.KEYCLOAK_REALM)
        # Use SERVER_URL (external/browser URL) for redirect, not PROVIDER_URL (internal)
        serverUrl = Setting().get(PluginSettings.KEYCLOAK_SERVER_URL)

        if not clientId or not realm or not serverUrl:
            return None

        redirectUri = '/'.join((getApiUrl(), 'oauth', cls.getProviderName(external=False), 'callback'))

        url = (
            f'{serverUrl}/realms/{realm}/protocol/openid-connect/auth'
            f'?client_id={clientId}'
            f'&response_type=code'
            f'&scope={" ".join(cls._AUTH_SCOPES)}'
            f'&redirect_uri={quote(redirectUri, safe="")}'
            f'&state={quote(state, safe="")}'
        )
        return url

    def getToken(self, code):
        if KeycloakOpenID is None:
            raise Exception('python-keycloak is not installed. Please install it to use the Keycloak provider.')
        client_secret = self.getClientSecretSetting()
        serverUrl = Setting().get(PluginSettings.KEYCLOAK_PROVIDER_URL) or Setting().get(
            PluginSettings.KEYCLOAK_SERVER_URL)
        keycloak_openid_args = {
            'server_url': serverUrl,
            'client_id': self.getClientIdSetting(),
            'realm_name': self.getRealm(),
            "verify" : False
        }
        if client_secret:
            keycloak_openid_args['client_secret_key'] = client_secret
        keycloak_openid = KeycloakOpenID(**keycloak_openid_args)
        redirectUri = '/'.join((getApiUrl(), 'oauth', self.getProviderName(external=False), 'callback'))

        try:
            with self._overrideHostHeader(keycloak_openid.connection):
                token = keycloak_openid.token(
                    grant_type='authorization_code',
                    code=code,
                    redirect_uri=redirectUri
                )
        except Exception as e:
            raise Exception(f'Error acquiring token: {e}')

        return token

    def getUser(self, token):
        if KeycloakOpenID is None:
            raise Exception('python-keycloak is not installed. Please install it to use the Keycloak provider.')
        client_secret = self.getClientSecretSetting()
        # Use PROVIDER_URL (internal) for server-to-server API calls
        serverUrl = Setting().get(PluginSettings.KEYCLOAK_PROVIDER_URL) or Setting().get(
            PluginSettings.KEYCLOAK_SERVER_URL)
        
        print(f"[DEBUG] getUser - serverUrl: {serverUrl}")
        print(f"[DEBUG] getUser - realm: {self.getRealm()}")
        print(f"[DEBUG] getUser - client_id: {self.getClientIdSetting()}")
        print(f"[DEBUG] getUser - token keys: {token.keys()}")
        
        keycloak_openid_args = {
            'server_url': serverUrl,
            'client_id': self.getClientIdSetting(),
            'realm_name': self.getRealm(),
            "verify" : False

        }
        if client_secret:
            keycloak_openid_args['client_secret_key'] = client_secret
        keycloak_openid = KeycloakOpenID(**keycloak_openid_args)

        try:
            with self._overrideHostHeader(keycloak_openid.connection):
                decoded = jwt.decode(token['access_token'], options={"verify_signature": False})
                print(f"[DEBUG] access_token iss: {decoded.get('iss')}")
                print(f"[DEBUG] access_token aud: {decoded.get('aud')}")
                print(f"[DEBUG] Calling userinfo with access_token (first 20 chars): {token['access_token'][:20]}...")
                user_data = keycloak_openid.userinfo(token['access_token'])
            print(f"[DEBUG] userinfo SUCCESS: {user_data}")
        except Exception as e:
            print(f"[DEBUG] userinfo FAILED: {type(e).__name__}: {e}")
            raise RestException(f'Failed to fetch user info from Keycloak: {e}', code=502)

        oauthId = user_data.get('sub')
        if not oauthId:
            raise RestException('Keycloak did not return user ID.', code=502)

        email = user_data.get('email')
        if not email:
            raise RestException('Keycloak user has no registered email address.', code=502)

        firstName = user_data.get('given_name', '')
        lastName = user_data.get('family_name', '')

        user = self._createOrReuseUser(oauthId, email, firstName, lastName)
        return user