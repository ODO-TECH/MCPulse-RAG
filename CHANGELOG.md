# Changelog

All notable changes to this project will be documented in this file.

## [0.1.0] - 2026-07-13

### Added

- Unified top-level `docker-compose.yml` for `qdrant`, `knowledge-mcp`, and `ragcheck`
- Root `.env.example` for configurable knowledge-base mount path
- Example env files for both services
- Repository `.gitignore` for secrets and runtime data
- Public-facing `README.md` with project overview and env setup guide
- Chinese documentation in `README_CN.md`
- MIT license
- Initial `CHANGELOG.md`
- Project version file

### Notes

- Existing service logic and algorithms were kept unchanged
- Deployment structure was reorganized for public repository publishing

## [0.2.0] - 2026-08-16

### Changed

- Upgraded `knowledge-mcp` from SSE to Streamable HTTP at `/mcp`
- Reworked `knowledge-mcp` startup so MCP can start immediately while indexing runs in the background
- Replaced filesystem-event watcher defaults with polling defaults for NAS-mounted knowledge directories
- Added `ingest_knowledge` for manual incremental sync and kept `reindex` for full rebuilds
- Hardened indexing so missing Qdrant collections are rebuilt even when local index state already exists
- Pinned the MCP Python SDK to a known working version and added startup validation for `FastMCP`
- Simplified Docker images to avoid unnecessary system package installation during NAS builds
- Upgraded `RAGcheck` to inspect Qdrant collections and MCP tool availability over Streamable HTTP
- Updated public defaults to generic knowledge-base names and provider-neutral model API variables
- Kept email delivery in `RAGcheck` and prepared a parallel `ragcheck-qqbot` branch for users who prefer bot delivery

### Added

- Public `ragcheck-qqbot` branch variant with example configuration

### Notes

- The open-source repository no longer includes personal knowledge-base naming, provider-specific defaults, or personal delivery settings
