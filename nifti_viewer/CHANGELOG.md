# Changelog

All notable changes to the **girder-nifti-viewer** plugin are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/) and this
project adheres to [Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-06-30

First stable release.

### Added
- NIfTI viewer for Girder with BIDS-aware browsing.
- Advanced metadata search over neuroimaging items.

### Changed
- Reconciled the package version (previously inconsistent between `setup.py`
  and `pyproject.toml`) to a single source of truth.

### Fixed
- Escaped the search regular expression to avoid ReDoS.
- Made upload parsing non-blocking.
- Removed the dead integration toward the deprecated `nifti_qc` plugin.
