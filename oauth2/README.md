# OAuth2 Plugin per Girder

Aggiunto al plugin standard di girder la possibilità di loggarsi con keycloak
## Requisiti

- Girder 5.0.0+
- Python 3.8+

## Installazione

1. Copia il plugin in `girder/plugins/`
2. Installa dipendenze: `pip install -e .`
3. Avviare frontend usando npm build e poi npm install all'interno del folder ../web_client
3. Configura i provider OAuth nell'admin panel
4. Abilita il plugin

