# Quick Start Guide - OAuth Plugin (Girder 5)

## ⚡ 5-Minute Setup

### Prerequisites
- Girder 5.0.0+ installed and running
- Python 3.8+
- Node.js 16+
- OAuth provider account (e.g., Keycloak, Google, GitHub)

### Installation (3 steps)

```bash
# 1. Install backend
cd /workspace/plugins_developer/oauth2-v5
pip install -e .

# For Keycloak support:
pip install python-keycloak

# 2. Build frontend
cd girder_oauth/web_client
npm install && npm run build

# 3. Restart Girder
girder serve
```

### First Use - Keycloak Example (5 minutes)

#### 1. Keycloak Server Setup

In Keycloak Admin Console:

```
1. Select your realm (or create new)
2. Go to Clients → Create
3. Configure:
   Client ID: girder-client
   Client Protocol: openid-connect
   Access Type: confidential
   Valid Redirect URIs: http://localhost:8080/api/v1/oauth/keycloak/callback
4. Save
5. Go to Credentials tab → Copy Client Secret
```

#### 2. Girder Configuration

In Girder:

```
1. Log in as admin
2. Go to Admin Console → Plugins
3. Enable "OAuth Login"
4. Click "Configure"
5. Find Keycloak section
6. Enter:
   Server URL: https://your-keycloak.com
   Realm: your-realm
   Client ID: girder-client
   Client Secret: [paste from Keycloak]
7. Save
```

#### 3. Test Login

```
1. Log out of Girder
2. Click "Sign in with Keycloak"
3. Authenticate with Keycloak
4. Redirected back to Girder
5. New user created automatically!
```

### Quick Setup - Other Providers

#### Google OAuth

1. **Google Cloud Console**: https://console.cloud.google.com/
   ```
   APIs & Services → Credentials → Create OAuth Client
   Redirect URI: http://localhost:8080/api/v1/oauth/google/callback
   ```

2. **Girder**:
   ```
   OAuth Settings → Google
   Client ID: [from Google]
   Client Secret: [from Google]
   ```

#### GitHub OAuth

1. **GitHub**: https://github.com/settings/developers
   ```
   OAuth Apps → New OAuth App
   Callback URL: http://localhost:8080/api/v1/oauth/github/callback
   ```

2. **Girder**:
   ```
   OAuth Settings → GitHub
   Client ID: [from GitHub]
   Client Secret: [from GitHub]
   ```

#### Microsoft Azure

1. **Azure Portal**: https://portal.azure.com/
   ```
   App registrations → New registration
   Redirect URI: http://localhost:8080/api/v1/oauth/microsoft/callback
   API Permissions: User.Read
   ```

2. **Girder**:
   ```
   OAuth Settings → Microsoft
   Client ID: [Application ID]
   Client Secret: [from Certificates & secrets]
   ```

### Configuration UI Tour

```
┌─────────────────────────────────────┐
│  OAuth Provider Configuration       │
├─────────────────────────────────────┤
│  ☑ Keycloak                         │
│    Server URL: [________________]   │
│    Realm:      [________________]   │
│    Client ID:  [________________]   │
│    Secret:     [****************]   │
│                                      │
│  ☑ Google                           │
│    Client ID:  [________________]   │
│    Secret:     [****************]   │
│                                      │
│  ☐ GitHub       [Enable]            │
│  ☐ Microsoft    [Enable]            │
│                                      │
│  [Save Configuration]               │
└─────────────────────────────────────┘
```

### Common Workflows

#### 1. Single Sign-On (SSO) with Keycloak

```bash
# Users can now:
1. Click "Sign in with Keycloak"
2. Enter Keycloak credentials once
3. Access Girder and other Keycloak-connected apps seamlessly
```

#### 2. Social Login for Public Site

```bash
# Enable multiple providers:
1. Google (for Gmail users)
2. GitHub (for developers)
3. Microsoft (for enterprise)

# Users choose their preferred method
```

#### 3. Academic/Research Access

```bash
# Use CILogon or Globus:
1. Enable CILogon
2. Users authenticate via institutional login
3. Access based on .edu email verification
```

### Programmatic Usage

#### Check User's OAuth Providers

```python
from girder.models.user import User

user = User().findOne({'login': 'username'})
oauth_providers = list(user.get('oauth', {}).keys())
print(f"User authenticated via: {oauth_providers}")
```

#### Force OAuth Re-authentication

```python
# Remove OAuth connection
user['oauth'].pop('keycloak', None)
User().save(user)
```

### Troubleshooting

#### "Invalid redirect URI" Error

```bash
# Solution: Verify callback URL exactly matches
# Girder:   http://localhost:8080/api/v1/oauth/keycloak/callback
# Provider: http://localhost:8080/api/v1/oauth/keycloak/callback
#           ↑ Must match exactly, including protocol and port
```

#### Keycloak "Invalid credentials" Error

```bash
# Solution: Check all 4 fields
1. Server URL: https://keycloak.example.com (no trailing /)
2. Realm: master (case-sensitive)
3. Client ID: girder-client (exact match from Keycloak)
4. Client Secret: (regenerate if unsure)
```

#### Button Not Appearing on Login Page

```bash
# Solution: Check configuration
1. Is plugin enabled? (Admin → Plugins)
2. Is provider enabled? (OAuth Settings page)
3. Are credentials saved? (Click Save button)
4. Hard refresh browser (Ctrl+Shift+R)
```

### Security Checklist

- [ ] Use HTTPS in production (not http)
- [ ] Configure callback URLs for production domain
- [ ] Rotate client secrets regularly
- [ ] Use minimal OAuth scopes (openid, email, profile only)
- [ ] Enable state parameter (automatic in plugin)
- [ ] Review OAuth user accounts periodically

### Testing

#### Test Each Provider

```bash
# For each enabled provider:
1. Log out of Girder
2. Click provider button
3. Authenticate
4. Verify redirect back to Girder
5. Check user account created
6. Try logging in again (should skip provider auth if session active)
```

#### Verify Configuration

```python
# Check settings in MongoDB
mongo girder
> db.setting.find({key: /^oauth\./}).pretty()

# Should show:
# - oauth.keycloak_client_id
# - oauth.keycloak_client_secret
# - oauth.keycloak_realm
# - oauth.keycloak_server_url
# - oauth.providers_enabled
```

### Next Steps

- Read full documentation: `README.md`
- Configure additional providers
- Test with real users
- Review `CHANGELOG.md` for latest features
- Set up monitoring for OAuth failures

### Production Deployment

```bash
# 1. Update callback URLs for production domain
https://your-girder.com/api/v1/oauth/{provider}/callback

# 2. Use environment variables for secrets
export KEYCLOAK_CLIENT_SECRET="secret"

# 3. Enable HTTPS
# Update Girder configuration for HTTPS

# 4. Test thoroughly
# All providers, all user types
```

### Support

- Documentation: `/workspace/plugins_developer/oauth2-v5/README.md`
- Keycloak docs: https://www.keycloak.org/documentation
- OAuth 2.0 spec: https://oauth.net/2/

---

**Pro Tip**: Start with one provider (Keycloak or Google) to learn the flow, then add others as needed!
