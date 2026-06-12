"""Application configuration loaded from environment variables."""

import os

# Girder API URL reachable from the Trame Python server (container-to-container)
GIRDER_API_URL = os.environ.get("GIRDER_API_URL", "http://localhost:8080/api/v1")

# Public-facing URL used by the browser to reach the Girder API
# (may differ from GIRDER_API_URL when behind a reverse proxy)
GIRDER_PUBLIC_URL = os.environ.get("GIRDER_PUBLIC_URL", "http://localhost:8080")

# Base URL of the Girder native web UI, opened from the Admin page for settings
# not exposed by the plugin (assetstores, users, OAuth). Behind nginx the Girder
# UI lives under /girder; in dev it is the root of GIRDER_PUBLIC_URL.
GIRDER_ADMIN_URL = os.environ.get("GIRDER_ADMIN_URL", GIRDER_PUBLIC_URL)

# Trame server settings
TRAME_HOST = os.environ.get("TRAME_HOST", "localhost")
TRAME_PORT = int(os.environ.get("TRAME_PORT", "8080"))

# Local cache directory for files downloaded by GirderMedViewer FileFetcher
CACHE_DIR = os.environ.get("DIADEMA_CACHE_DIR", "/tmp/diadema_cache")
