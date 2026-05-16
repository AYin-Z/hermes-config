# Contributing

Thanks for your interest in contributing to the MemOS-Hermes integration!

## What this project needs

### Bug fixes & improvements
- **SearchHandler server-side turn exclusion** — `exclude_turn_id` support in MemOS search to prevent current-turn self-pollution (see `CHANGELOG.md` for context)
- **Project isolation** — search filtering by `project_id` in MemOS
- **Health check improvements** — the `/product/health/detail` endpoint could be smarter
- **Idempotency** — the current 30s in-memory cache could be replaced with a Neo4j-backed dedup

### Documentation
- Example configs for different embedding backends (OpenAI, local vLLM, etc.)
- Migration guide from the official memos-local-plugin (SQLite) to the Docker REST API

### Testing
- Add more test cases to `scripts/acceptance-test.py`
- CI integration (GitHub Actions)

## How to contribute

1. Fork the repo
2. Create a feature branch: `git checkout -b feat/my-improvement`
3. Commit your changes (conventional commits preferred)
4. Open a Pull Request

## Code style

- Python: keep it simple. No unnecessary abstractions.
- The adapter (`bridge_client.py`) should stay thin — it translates, not thinks.
- Patches for MemOS server-side (`patches/`) should be minimal and reversible.

## PR guidelines

- If you're fixing a specific failure mode from the acceptance test (V01-V15), mention which
- If adding a new MemOS endpoint, update `patches/apply-patches.sh`
- Test with `python3 scripts/acceptance-test.py --quick` before submitting
