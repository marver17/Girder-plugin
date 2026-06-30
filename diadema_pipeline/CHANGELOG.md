# Changelog

All notable changes to the **girder-diadema-pipeline** plugin are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/) and this
project adheres to [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-06-30

Initial public (alpha) release.

### Added
- Pipeline orchestration plugin for Girder driving the MRIQC, FreeSurfer and
  LST-AI Celery workers.
- REST endpoints, plugin settings and the web-client launch/monitoring UI.

### Changed
- Hardened job code and security; baked the plugin into the worker images for
  the full deployment.
