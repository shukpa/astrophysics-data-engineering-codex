# AGENTS.md

## Project: Agentic Galactic Discovery (AGD)

This file is the **single, provider-neutral operating contract for every agent**
that works in this repo, regardless of toolchain (Claude/Fable, Codex/GPT, or
other). It is the primary operating context. There are intentionally **no**
provider-specific context files (e.g. no `CLAUDE.md`, no `CLAUDE_CODE_CONTEXT.md`);
their removal was deliberate. Do not re-introduce them.

## Mission

Build an open-source platform for real-time astronomical transient discovery. The
system ingests alert data from Fink/ZTF now and should evolve toward Rubin/LSST-scale
processing, with a strict medallion architecture and scientifically defensible
provenance. The forward roadmap (gold layer, Euclid open-data integration, and a
falsifiable multi-probe cosmology thread) lives in `AGD_FORWARD_PLAN.md`.

## Multi-Agent Operating Model

This repo is evolved by multiple AI toolchains in rotation. Coordination happens
through **three artifacts only**:

1. `AGENTS.md` — the rules (this file).
2. `AGD_FORWARD_PLAN.md` — the roadmap and per-phase state.
3. PR history — provenance of what changed and why.

Rules for every agent:

- **Provider neutrality is mandatory.** Do not add provider-specific context
  files, model/vendor assumptions, or tooling lock-in anywhere in the repo. The
  `model` field in planning config is a placeholder resolved by whichever runtime
  the operator selects.
- **One branch and one PR per phase.** Branch names follow the plan
  (`chore/...`, `feat/...`). Keep changes minimal and scoped to the phase.
- **Hand off explicitly.** Every PR description must state what changed and what
  the next agent needs to know, so a different toolchain can pick up any phase cold.
- **CI is the enforcement layer.** `.github/workflows/ci.yml` runs ruff, black,
  and the test suite on every push/PR to `main`. Keep it green; keep the checks in
  sync with the Commands below.

## How Any Agent Should Start Work

1. Read this file first, then `AGD_FORWARD_PLAN.md` for current phase state, then
   `SCIENCE_GOALS.md` for the science rules of inference (it governs the science;
   the plan governs sequencing).
2. Scan the current repo state before proposing changes: `rg --files`,
   `git status --short`, and the relevant files under `src/`, `tests/`, and `config/`.
3. `src/utils/config.py` (Pydantic settings) is the **single runtime source of
   truth** for configuration.
4. `config/default.yaml` is a **non-loaded planning reference** only — see
   "Configuration" below. Do not treat it as runtime config.
5. Run targeted tests for the area being changed, then the broader validation
   (ruff + black + pytest) that CI will run.

## Quick Reference

- Python: 3.11+ (CI tests 3.11 and 3.12)
- Style: `ruff` + `black`, type hints, Google docstrings
- Testing: `pytest tests/ -v`
- Runtime config: `src/utils/config.py`
- Logging: structured logging

## Commands

```bash
# Install (with dev tooling)
pip install -e ".[dev]"

# Run tests (unit + data-quality; integration deselected, as CI does)
pytest -m "not integration"

# Run linter
ruff check src/ scripts/ tests/

# Check formatting (CI fails on unformatted code)
black --check src/ scripts/ tests/

# Auto-format
black src/ scripts/ tests/
```

## Configuration (single source of truth)

- **`src/utils/config.py` is the only runtime configuration.** Pydantic settings
  with environment-variable / `.env` overrides. All runtime values live here.
- **`config/default.yaml` is a non-loaded planning artifact.** Nothing reads it.
  It holds only forward-looking config for phases not yet implemented
  (anomaly-agent thresholds, classification taxonomy, nightly digest). It must
  **not** duplicate any value already defined in Pydantic or in processor code
  (e.g. the silver rejection thresholds live in
  `src/processing/silver_processor.py`). When a phase implements one of these
  sections, move it into Pydantic and delete it from the YAML — Phase 1 did
  exactly this for the catalog cross-match section (now `CrossmatchSettings`).

## Architecture Rules

1. No LLM calls in the hot path. Use ML models for real-time classification and
   reserve LLMs for flagged events (warm path only).
2. Every function that touches external APIs must have retry logic and timeout
   handling.
3. Preserve the medallion flow: Bronze to Silver to Gold. Do not skip layers.
4. Test everything: unit, integration, and data-quality checks.
5. Preserve provenance so every derived result traces back to source alert IDs.
6. Use timezone-aware UTC datetimes (`datetime.now(UTC)`); naive `datetime.utcnow()`
   is banned and enforced by ruff `DTZ` rules.
7. Analysis/science code (notebooks, `src/analysis/`) may depend on the pipeline
   (gold); the pipeline must never import analysis code.

## Current Technical Direction

- Fink REST API is the ingestion source; bronze, silver, and gold processing are
  implemented (streaming ZTF alerts through the full medallion).
- **Phase 0 (repo convergence) landed:** CI, single config source of truth,
  timezone-aware datetimes, and this hardened contract.
- **Phase 1 (gold + cross-match) landed:** Gaia DR3 / SIMBAD cone-search clients
  (retry + Parquet cache), gold processor with nearest-neighbour enrichment,
  star/extragalactic discriminator, light-curve features, and provenance
  pointers (no raw payload JSON in gold). Catalog outages degrade gracefully to
  null match columns. Note: astroquery's Gaia TAP layer ignores `HTTPS_PROXY`;
  in a CONNECT-proxy environment set `CROSSMATCH_TAP_PROXY_URL` (and
  `CROSSMATCH_TAP_CA_BUNDLE` if the proxy re-terminates TLS) so the Gaia client
  tunnels through it. Unset by default = direct network. SIMBAD needs nothing
  (it uses `requests`, which honours `HTTPS_PROXY`).
- **Phase 2 (Euclid Q1 ingestion) landed:** `EuclidClient` (ESA TAP/ADQL via
  astroquery, retry + Parquet cache + per-query provenance with a DR tag —
  `Q1` now, flip `EUCLID_DR_TAG` to `DR1F` at the DR1-Foundation swap-in);
  MER final-catalogue cone searches into Euclid bronze; SLDE strong-lens
  catalogue (file-based — it is NOT exposed via ESA TAP, verified against
  `tap_schema`) through bronze→silver with grade filtering; gold-layer
  lens-field cross-match flags `lens_field_transient` (these always escalate
  to human review in Phase 4). Same `EUCLID_TAP_PROXY_URL` convention as the
  Gaia client behind a CONNECT proxy. Re-run `EuclidClient.discover_tables`
  after each data release before trusting table names.
- **Phase 3 (constraint & lensing harness) landed:** the analysis layer
  `src/analysis/` — strictly downstream of gold, the pipeline never imports it.
  `constraints.py` holds published DESI DR2 / Planck 2018 / KiDS-1000 / DES Y3 /
  DES-SN5YR values transcribed from source with arXiv provenance (no memory,
  no narrative without a number); `cosmology.py` is the combined-probe toolkit
  (CPL w(z), flat w0waCDM distances via astropy, growth index γ, S8, tension in
  σ); `lensing.py` is the SIS/SIE harness (θ_E ↔ σ_v ↔ projected mass on
  astropy angular-diameter distances, plus the 1/√N survey sensitivity floor).
  Two runnable notebooks render the science: `notebooks/combined_probe_
  constraints.ipynb` (3a verdict cell — where w0/wa/γ/S8 land vs GR+ΛCDM vs
  braneworld/DGP) and `notebooks/euclid_lens_statistics.ipynb` (3b sensitivity
  floor — Q1 and DR1 both sit orders of magnitude above braneworld-scale lensing
  effects; the harness is a DR1-ready ΛCDM instrument, not a per-lens dimension
  probe). Every relation is unit-tested against physics identities and the
  transcribed values. New runtime deps: `numpy`, `scipy` (astropy distance
  integrals); `matplotlib`/`nbformat`/`nbconvert` are dev-only (notebooks).
  Re-run against DR1-Foundation by updating the numbers in `constraints.py` and
  swapping N≈500 → N≈7000 — no code change.
- The anomaly agent (Phase 4) and the GW standard-siren counterpart channel
  (Phase 5) are the next phases — see `AGD_FORWARD_PLAN.md`.
- No production agent runtime or provider has been selected; the platform stays
  provider-neutral by design.

## Key Files

- `AGD_FORWARD_PLAN.md`: roadmap and per-phase execution plan
- `SCIENCE_GOALS.md`: science definition + rules of inference (governs on conflict)
- `.github/workflows/ci.yml`: CI (ruff + black + pytest on 3.11 / 3.12)
- `src/ingestion/fink_api_client.py`: primary alert ingestion client
- `src/processing/bronze_processor.py`: bronze layer processing
- `src/processing/silver_processor.py`: silver layer processing (quality gates,
  dedup, rejection thresholds)
- `src/processing/gold_processor.py`: gold layer processing (cross-match
  enrichment, discriminator, light-curve features)
- `src/crossref/gaia_client.py` / `src/crossref/simbad_client.py`: catalog
  cone-search clients (retry, timeout, Parquet cache)
- `src/ingestion/euclid_client.py`: ESA Euclid TAP client (MER catalogue,
  schema discovery, provenance, DR-tagged cache)
- `src/processing/euclid_lens_processor.py`: SLDE lens catalogue
  bronze/silver (file-based; grade filtering)
- `src/models/lenses.py`: EuclidLensCandidate / EuclidLensCatalog
- `src/analysis/`: Phase 3 constraint & lensing harness (downstream of gold;
  never imported by the pipeline) — `constraints.py` (transcribed published
  values + provenance), `cosmology.py` (CPL/w0waCDM/growth/tension),
  `lensing.py` (SIS/SIE + sensitivity floor)
- `notebooks/combined_probe_constraints.ipynb` / `notebooks/euclid_lens_
  statistics.ipynb`: the 3a verdict and 3b sensitivity-floor notebooks
- `scripts/ingest_euclid_q1.py`: Euclid Q1 ingestion (live MER + SLDE file;
  `--skip-mer` for offline environments)
- `scripts/run_fink_gold_smoke.py`: bronze→silver→gold smoke run
  (`--source synthetic --no-crossmatch` for offline environments;
  `--lens-catalog` to exercise the lens-field cross-match)
- `src/utils/config.py`: runtime settings and environment-variable contract
- `config/default.yaml`: non-loaded planning config for future phases
- `tests/conftest.py`: shared test fixtures

## Working Rules

- Prefer `rg` for search and `rg --files` for file discovery.
- Keep changes minimal and targeted.
- Do not introduce provider-specific assumptions unless the code actually uses them.
- If docs and code disagree, fix the docs or fix the code so one source of truth
  remains clear.
