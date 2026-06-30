from setuptools import setup

# Questo file esiste solo per supportare `pip install -e .` in modalità legacy.
# Tutta la configurazione è in pyproject.toml. Il client web è pre-buildato
# (Vite) e spedito in web_client/dist/* via package-data, poi servito a runtime
# da registerPluginStaticContent (modello Girder 5).
setup()
