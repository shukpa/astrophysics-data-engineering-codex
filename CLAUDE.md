# CLAUDE.md

## Project: Agentic Galactic Discovery (AGD)

**Read CLAUDE_CODE_CONTEXT.md first** — it contains full project context, API references, and development guidelines.

## Quick Reference

- **Python**: 3.11+
- **Style**: ruff + black, type hints, Google docstrings
- **Testing**: pytest, run with `pytest tests/ -v`
- **Config**: Pydantic models in `src/utils/config.py`
- **Logging**: Structured logging via `src/utils/logging_config.py`

## Commands

```bash
# Run tests
pytest tests/ -v

# Run linter
ruff check src/ tests/

# Format code
black src/ tests/

# Run the Fink API demo
python -m src.ingestion.fink_api_demo

# Run the full pipeline (local development)
python -m src.pipeline.run --mode=batch --source=fink-api
```

## Architecture Rules

1. **No LLM calls in the hot path** — ML models for real-time classification, LLMs for flagged events only
2. **Every function that touches external APIs** must have retry logic and timeout handling
3. **Delta Lake medallion**: Bronze (raw) → Silver (clean) → Gold (enriched). Never skip a layer.
4. **Test everything**: unit, integration, data quality. Science demands rigor.
5. **Preserve provenance**: every derived result must trace back to source alert IDs

## Key Files

- `src/ingestion/fink_api_client.py` — Primary data source (Phase 1)
- `src/processing/bronze_processor.py` — First pipeline stage
- `src/agents/orchestrator.py` — Agent routing and synthesis
- `config/default.yaml` — All configuration lives here
- `tests/conftest.py` — Shared test fixtures including sample alerts
