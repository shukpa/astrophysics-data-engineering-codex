# AGENTS.md

## Project: Agentic Galactic Discovery (AGD)

This file is the primary operating context for Codex sessions in this repo.

## Mission

Build an open-source platform for real-time astronomical transient discovery. The system ingests alert data from Fink/ZTF now and should evolve toward Rubin/LSST-scale processing, with a strict medallion architecture and scientifically defensible provenance.

## How Codex Should Start Work

1. Read this file first.
2. Scan the current repo state before proposing changes: `rg --files`, `git status --short`, and the relevant files under `src/`, `tests/`, and `config/`.
3. Prefer the Pydantic settings in `src/utils/config.py` as the runtime source of truth.
4. Treat `config/default.yaml` as a planning artifact unless code is added to load it.
5. Run targeted tests for the area being changed, then run broader validation if the environment has the required tools installed.

## Quick Reference

- Python: 3.11+
- Style: `ruff` + `black`, type hints, Google docstrings
- Testing: `pytest tests/ -v`
- Runtime config: `src/utils/config.py`
- Logging: structured logging

## Commands

```bash
# Run tests
pytest tests/ -v

# Run linter
ruff check src/ tests/

# Format code
black src/ tests/
```

## Architecture Rules

1. No LLM calls in the hot path. Use ML models for real-time classification and reserve LLMs for flagged events.
2. Every function that touches external APIs must have retry logic and timeout handling.
3. Preserve the medallion flow: Bronze to Silver to Gold. Do not skip layers.
4. Test everything: unit, integration, and data-quality checks.
5. Preserve provenance so every derived result traces back to source alert IDs.

## Current Technical Direction

- Fink REST API is the Phase 1 ingestion source.
- Bronze processing is implemented; silver, gold, and agent orchestration are still evolving.
- The repo is now Codex-first for development workflow.
- The planned agent runtime provider is OpenAI-based, but no production agent runtime has been implemented yet.

## Key Files

- `src/ingestion/fink_api_client.py`: primary alert ingestion client
- `src/processing/bronze_processor.py`: bronze layer processing
- `src/utils/config.py`: runtime settings and environment-variable contract
- `config/default.yaml`: planning/default config artifact, not loaded at runtime today
- `tests/conftest.py`: shared test fixtures

## Working Rules

- Prefer `rg` for search and `rg --files` for file discovery.
- Keep changes minimal and targeted.
- Do not introduce provider-specific assumptions unless the code actually uses them.
- If docs and code disagree, fix the docs or fix the code so one source of truth remains clear.
