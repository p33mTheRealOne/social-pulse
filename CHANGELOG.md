# Changelog

## 0.5.0
- Documentation: new README, contributing guide, security policy.
- GitHub Actions CI (Linux and Windows, Python 3.11 and 3.12) and ruff linting.
- Warning when Instagram views come from the legacy counter instead of the app's play count.

## 0.4.0
- HTTP API (FastAPI): API keys, rate limiting, caching, batch endpoint, Docker image.
- `--fields` option (CLI and API) to fetch only the metrics you need.
- Requests and redirects restricted to the supported platforms' domains.

## 0.3.0
- Multiple sources per platform, merged per field.
- Instagram JSON API with your own cookies (reposts, shares, play count).
- Exact YouTube comment counts, Facebook post and reel parsers, X reposts/saves/views.

## 0.1.0
- First version: TikTok, X, Instagram and Facebook metrics from the terminal.
