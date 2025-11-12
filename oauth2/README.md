# OAuth2 Plugin per Girder

Aggiunto al plugin standard di girder la possibilità di loggarsi con keycloak
## Requisiti

- Girder 5.0.0+
- Python 3.8+

### Installazione (3 steps)

```bash
# 1. Install backend
cd /oauth2
pip install -e .

# For Keycloak support:
pip install python-keycloak

# 2. Build frontend
cd girder_oauth/web_client
npm install && npm run build

# 3. Restart Girder
girder serve
```

