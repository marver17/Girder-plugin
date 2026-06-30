# Changelog

All notable changes to the **girder-oauth** plugin are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/) and this
project adheres to [Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-06-30

First stable release as a standalone plugin.

### Added
- OAuth2 login via the supported providers.

### Changed
- Pinned a static package version (`1.0.0`) instead of deriving it from
  `setuptools_scm`, so the plugin builds reproducibly outside the original
  Girder monorepo.
