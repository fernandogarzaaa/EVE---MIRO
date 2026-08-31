# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-08-31

### Added

- `eve-miro` CLI (`setup`, `serve`, `run`, `api`, `doctor`) and one-liner installers (`install.sh`, `install.ps1`).
- Fail-closed in-tree engines: MiroFish Flask + EVE CLI. `EVE_MIRO_ENGINES=stub` is a **test double only**.
- On-disk local graph memory (`MIROFISH_MEMORY=local`) when Zep Cloud is not configured.
- Live public-data adapters: Open-Meteo, USGS, OpenSky, GDACS, GDELT, OSM, NASA STAC, CelesTrak, CoinGecko, World Bank, NOAA SWPC, AISStream (key-gated).
- OASIS twitter/reddit `actions.jsonl` harvest via `PlatformActionLogger`. Truncated runs start in a peak posting hour.
- `map_mirofish_result` copies WorldState Open-Meteo `wind_speed_10m` / precipitation into `predicted_series` and derives congestion from posts-per-round. Social action types (`CREATE_POST`) are kept.
- CI: ruff lint + pytest (`FIXTURES=1`) with concurrency cancel-in-progress.
- GitHub Release workflow on `v*` tags (sdist/wheel, `install.sh` / `install.ps1`, sha256). No secrets.

### Changed

- Production live `fetch()` fail-closes (`ProviderError`) on HTTP/parse/missing-key errors. Fixtures remain the offline path (`FIXTURES=1`).
- Docker Compose default `EVE_MIRO_ENGINES=in-tree`.
- User-Agent `eve-miro/1.0`.
- EVE `observe` / `select` / `transfer` are labeled **local-heuristic** in provenance. Only `validate()` invokes `eve.js`.

### Honest limitations

- Live OASIS still needs Python **3.11** (`mirofish/.venv`) plus an OpenAI-compatible LLM (Ollama/GGUF). This release did not run a live GPU loop.
- AISStream live is WebSocket-only; missing key or live request without a REST snapshot raises `ProviderError`.
- Weather MAE for a 1-hour sim at information cutoff needs at least the first post-cutoff hour in `predicted_series` (mapper emits ≥2 hours of persistence).
