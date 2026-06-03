"""Application configuration loaded from environment variables."""

import os

# Girder API URL reachable from the Trame Python server (container-to-container)
GIRDER_API_URL = os.environ.get("GIRDER_API_URL", "http://localhost:8080/api/v1")

# Public-facing URL used by the browser to reach the Girder API
# (may differ from GIRDER_API_URL when behind a reverse proxy)
GIRDER_PUBLIC_URL = os.environ.get("GIRDER_PUBLIC_URL", "http://localhost:8080")

# Trame server settings
TRAME_HOST = os.environ.get("TRAME_HOST", "localhost")
TRAME_PORT = int(os.environ.get("TRAME_PORT", "8080"))

# Local cache directory for files downloaded by GirderMedViewer FileFetcher
CACHE_DIR = os.environ.get("DIADEMA_CACHE_DIR", "/tmp/diadema_cache")
