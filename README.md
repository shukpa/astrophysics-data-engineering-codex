# Agentic Galactic Discovery

**Real-time astronomical transient discovery using agentic AI**

An open-source platform for detecting and classifying astronomical transients from telescope survey data. We ingest streaming alerts from ZTF (and soon Rubin/LSST), process them through a medallion lakehouse architecture (local Parquet today, Databricks-ready), and use AI agents to identify genuinely anomalous events that might represent new physics.

Beyond the transient stream, AGD is growing a **multi-probe science layer**: batch ingestion of Euclid open-data catalogues (starting with the Q1 strong-lens sample) and a falsifiable, combined-probe cosmology analysis (DESI + CMB + SNe + weak lensing) that tests whether dark energy and gravity deviate from GR+ΛCDM. The full roadmap and phase state live in [`AGD_FORWARD_PLAN.md`](AGD_FORWARD_PLAN.md).

See [`AGENTS.md`](AGENTS.md) for the repository's development instructions and operating conventions, and [`SCIENCE_GOALS.md`](SCIENCE_GOALS.md) for the science motivation.

## Vision

Every night, survey telescopes like the Zwicky Transient Facility (ZTF) generate hundreds of thousands of alerts about objects that have changed brightness. Most are known phenomena—variable stars, asteroids, routine supernovae. But hidden in this data stream could be something unprecedented: a new class of transient, a rare kilonova from merging neutron stars, or gravitational microlensing revealing an isolated black hole.

This project combines modern data engineering with AI agents to:
1. **Process alerts at scale** using Spark and Delta Lake
2. **Classify known phenomena** with ML models (hot path)
3. **Investigate interesting events** with LLM-powered agents (warm path)
4. **Surface true anomalies** for human astronomer review (cold path)

## Architecture

### Medallion Data Architecture

We use the medallion (bronze/silver/gold) architecture for progressive data refinement:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           DATA FLOW                                      │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   Fink API ──► Bronze ──► Silver ──► Gold ──► Agents ──► Reports        │
│                  │          │         │          │                       │
│                  │          │         │          ▼                       │
│               Raw data   Cleaned   Enriched   Anomaly                   │
│               + metadata  + valid  + xmatch   Assessment                │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

| Layer | Purpose | Contents |
|-------|---------|----------|
| **Bronze** | Raw ingestion | Alerts as-received from Fink, with ingestion metadata. Append-only, preserves everything. |
| **Silver** | Cleaned & validated | Schema enforced, bad detections filtered, coordinates standardized, duplicates removed. |
| **Gold** | Enriched & ready | Cross-matched with Gaia/SIMBAD, light curve features computed, ML classifications attached. |

### Processing Paths

| Path | Latency | Method | Purpose |
|------|---------|--------|---------|
| **Hot** | Seconds | Spark + ML | Ingest, clean, basic classification |
| **Warm** | Minutes | LLM Agents | Triage flagged events, cross-reference, assess anomalies |
| **Cold** | Hours | Human | Review detailed reports for genuinely unusual events |

## Project Structure

```
astrophysics-data-engineering-codex/
├── src/
│   ├── __init__.py
│   ├── exceptions.py               # Custom exception hierarchy (AGDError)
│   ├── models/
│   │   └── alerts.py               # Pydantic models for ZTF/Fink alerts
│   ├── ingestion/
│   │   ├── fink_api_client.py      # Fink REST API client (retry/backoff)
│   │   └── euclid_client.py        # ESA Euclid TAP client (MER, provenance, DR tag)
│   ├── crossref/
│   │   ├── gaia_client.py          # Gaia DR3 cone search (retry, Parquet cache)
│   │   ├── simbad_client.py        # SIMBAD cone search (retry, Parquet cache)
│   │   └── utils.py                # Separation, NaN handling, cache keys
│   ├── processing/
│   │   ├── bronze_processor.py     # Bronze layer processing
│   │   ├── silver_processor.py     # Validation, quality filtering, deduplication
│   │   ├── gold_processor.py       # Cross-match enrichment, discriminator, LC features,
│   │   │                           #   Euclid lens-field flagging
│   │   └── euclid_lens_processor.py # SLDE lens catalogue bronze/silver
│   ├── utils/
│   │   └── config.py               # Pydantic-based runtime configuration
│   └── agents/                     # (Future: AI agent implementations)
├── scripts/
│   ├── run_fink_silver_smoke.py    # Live bronze→silver smoke run
│   ├── run_fink_gold_smoke.py      # Bronze→silver→gold smoke (live or synthetic)
│   └── ingest_euclid_q1.py         # Euclid Q1: live MER TAP + SLDE lens catalogue
├── tests/
│   ├── conftest.py                 # Shared pytest fixtures
│   ├── test_ingestion/             # Fink API client tests
│   ├── test_crossref/              # Gaia/SIMBAD client tests (mocked + live-gated)
│   ├── test_processing/            # Bronze, silver & gold processor tests
│   ├── test_scripts/               # Smoke-script tests
│   └── test_utils/                 # Config tests
├── config/
│   └── default.yaml                # Non-loaded planning config for future phases
├── .github/workflows/ci.yml        # CI: ruff + black + pytest (Python 3.11 / 3.12)
├── AGENTS.md                       # Provider-neutral agent operating contract
├── AGD_FORWARD_PLAN.md             # Roadmap & per-phase execution plan
├── SCIENCE_GOALS.md                # Science motivation
├── pyproject.toml                  # Project configuration & dependencies
└── README.md
```

## Current Status

**Implemented — ZTF/Fink transient pipeline (bronze → silver → gold):**

- [x] Project structure and Pydantic runtime configuration
- [x] Custom exception hierarchy
- [x] Pydantic models for ZTF alerts
- [x] Bronze layer processor
- [x] Fink API client with retry logic
- [x] Silver layer processor (quality gates, dedup, provenance)
- [x] Repo convergence (Phase 0): CI, single config source of truth, timezone-aware datetimes
- [x] Gold layer + Gaia DR3 / SIMBAD cross-match (Phase 1): cone-search clients with
      retry + Parquet cache, star/extragalactic discriminator, light-curve features,
      provenance pointers (no raw payload JSON in gold)
- [x] Euclid Q1 open-data ingestion (Phase 2): ESA TAP client (MER final catalogue →
      bronze with DR-tagged provenance), SLDE strong-lens catalogue → bronze/silver
      with grade filtering, and the gold-layer `lens_field_transient` cross-match
- [x] Test framework + smoke/ingest scripts (live or offline synthetic)

**Next — see [`AGD_FORWARD_PLAN.md`](AGD_FORWARD_PLAN.md) for the full plan:**

- [ ] Multi-probe constraint & lensing science harness (`feat/constraint-harness`)
- [ ] Lens-aware anomaly agent (`feat/anomaly-agent`)
- [ ] Multi-messenger GW counterpart channel (`feat/gw-counterparts`)

## Getting Started

### Prerequisites

- Python 3.11+
- (Optional) Databricks workspace for production deployment

### Installation

```bash
# Clone the repository
git clone https://github.com/your-org/astrophysics-data-engineering.git
cd astrophysics-data-engineering

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows

# Install dependencies
pip install -e ".[dev]"
```

### Configuration

Configuration is managed via environment variables or a manually created `.env` file:

```bash
# .env example
AGD_ENVIRONMENT=development
STORAGE_BASE_PATH=./data
FINK_TIMEOUT_SECONDS=30
```

The **single runtime source of truth** is `src/utils/config.py` (Pydantic settings, overridable via environment variables / `.env`). `config/default.yaml` is **not loaded** by the application — it is a planning reference for configuration that future phases will implement in Pydantic, and it must not duplicate any runtime value. See `AGENTS.md` → "Configuration".

### Running Tests

```bash
pytest                          # Run all tests
pytest -m "not integration"     # Skip integration tests (what CI runs)
AGD_RUN_INTEGRATION_TESTS=1 pytest -m integration  # Live Fink/Gaia queries
pytest --cov=src                # With coverage report
```

Integration tests hit live services (Fink, Gaia). astroquery's Gaia TAP layer
ignores `HTTPS_PROXY`, so behind a CONNECT proxy also export
`CROSSMATCH_TAP_PROXY_URL` (and `CROSSMATCH_TAP_CA_BUNDLE` if the proxy
re-terminates TLS) — the Gaia client then tunnels through it. In a normal
direct-network environment none of this is needed.

### Basic Usage

```python
from src.processing import BronzeProcessor
from src.utils.config import get_settings

# Initialize processor
processor = BronzeProcessor()

# Process raw alerts (from Fink API)
raw_alerts = [
    {
        "objectId": "ZTF21aaxtctv",
        "ra": 193.822,
        "dec": 2.896,
        "magpsf": 18.5,
        "sigmapsf": 0.05,
        "fid": 1,
        "jd": 2460000.5,
    }
]

# Validate and create batch
batch = processor.process_alerts(raw_alerts)
print(f"Processed {batch.count} alerts")

# Write to bronze layer
processor.write_batch(batch)

# Read back and analyze
df = processor.read_bronze_data()
stats = processor.get_statistics()
```

## Key Concepts

### Astronomical Measures

| Measure | Description |
|---------|-------------|
| **Magnitude** | Logarithmic brightness scale. Lower = brighter. Each step of 1 mag = 2.512x brightness change. |
| **Julian Date (JD)** | Continuous day count used in astronomy. JD 2460000 ≈ Feb 2023. |
| **RA/Dec** | Right Ascension (0-360°) and Declination (-90° to +90°) — celestial coordinates. |
| **Filter (g/r/i)** | Photometric bands: g (green, ~475nm), r (red, ~625nm), i (infrared, ~775nm). |

### ZTF Alert Structure

Each alert contains:
- **objectId**: Unique ZTF identifier (e.g., `ZTF21aaxtctv`)
- **candid**: Unique alert/candidate ID
- **ra, dec**: Sky coordinates in degrees
- **magpsf, sigmapsf**: Brightness measurement and uncertainty
- **fid**: Filter ID (1=g, 2=r, 3=i)
- **jd**: Julian date of observation
- **prv_candidates**: Previous 30 days of detections (light curve history)

### Fink Classifications

The Fink broker assigns ML classifications:
- `SN candidate` — Supernova candidate
- `Early SN Ia candidate` — Early-stage Type Ia supernova
- `Kilonova candidate` — Neutron star merger remnant
- `Microlensing candidate` — Gravitational microlensing event
- `Variable Star` — Various variable star types
- `AGN` — Active galactic nucleus
- `Solar System MPC` — Known solar system object

## Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Data Processing | Apache Spark | Distributed alert processing |
| Storage | Delta Lake | ACID transactions, time travel, schema evolution |
| Data Models | Pydantic | Validation, serialization, type safety |
| Configuration | pydantic-settings | Environment-based config management |
| Logging | structlog | Structured logging for observability |
| Astronomy | astropy, astroquery | Coordinate transforms, catalog queries |
| AI Agents | Provider-neutral (future) | Scientific reasoning and anomaly assessment |
| Testing | pytest | Unit, integration, and data quality tests |

## Development Guidelines

### Code Style

- Python 3.11+ with type hints everywhere
- Google-style docstrings on public functions
- `ruff` for linting, `black` for formatting
- Structured logging (no print statements)

### Testing Philosophy

Science demands rigor:
- Unit tests for individual functions
- Integration tests for pipeline stages
- Known-object tests: verify correct classification of well-characterized objects
- Regression tests: improvements must not break existing correct classifications

### Error Handling

- Custom exceptions inherit from `AGDError`
- Never silently swallow pipeline errors
- Retry with exponential backoff for external APIs
- Log full context on failures (alert ID, stage, details)

## Roadmap

The authoritative, phase-by-phase plan (with acceptance criteria and data-source
detail) is [`AGD_FORWARD_PLAN.md`](AGD_FORWARD_PLAN.md). Summary:

| Phase | Branch | Focus |
|-------|--------|-------|
| **0 — Repo convergence** ✅ | `chore/repo-convergence` | CI, single config source of truth, timezone-aware datetimes, hardened agent contract |
| **1 — Gold + cross-match** ✅ | `feat/gold-crossref` | Silver→gold; Gaia DR3 / SIMBAD cone-search cross-match; star/extragalactic discrimination |
| **2 — Euclid Q1 ingestion** ✅ | `feat/euclid-q1` | Batch TAP/ADQL ingestion of Euclid open data (MER catalogue + Q1 strong-lens sample) through the medallion; transient↔lens-field cross-match |
| **3 — Constraint & lensing harness** | `feat/constraint-harness` | Falsifiable multi-probe cosmology fit (DESI + CMB + SNe + weak lensing → w₀, wₐ, γ vs GR+ΛCDM) and strong-lens statistics |
| **4 — Anomaly agent** | `feat/anomaly-agent` | Lens-aware, provider-neutral warm-path anomaly assessment + nightly report |
| **5 — GW counterpart channel** | `feat/gw-counterparts` | LIGO/Virgo/KAGRA public alerts → skymap-filtered ZTF/Rubin counterpart search; GW standard-siren (graviton-leakage) test |

### Euclid data landscape

Euclid ingestion (Phase 2) targets the ESA/IRSA open-data releases via
`astroquery.esa.euclid` (TAP/ADQL): **Q1** (out; strong-lens capability demo),
with the harness designed to swap cleanly to **DR1-Foundation** (~1900 deg²,
Nov 2026) — the Stage-IV weak-lensing upgrade. Euclid is treated as batch
catalogue ingestion inside the same bronze→silver→gold medallion, not a second
pipeline.

### Science framing (honest by design)

No single dataset "detects a new dimension." Extra-dimensional models are tested
through three falsifiable channels, kept deliberately decoupled from the *agnostic*
anomaly hunt (biasing discovery toward a favoured explanation manufactures
confirmations):

1. **Combined-probe parameters** — the dark-energy equation of state **(w₀, wₐ)**,
   growth index **γ**, and **S₈**, constrained by DESI + CMB + SNe + Stage-III weak
   lensing (Phase 3a).
2. **Lens / growth statistics** — strong-lens abundance and profile statistics as a
   DR1-ready ensemble instrument (Phase 3b).
3. **GW standard sirens** — if gravitons leak into extra dimensions, GW sources look
   dimmer than their EM counterparts (d_L^GW > d_L^EM); GW170817 pinned spacetime to
   D ≈ 4.0 ± 0.1. Sharpening this needs exactly AGD's competency — rapid optical
   counterpart ID after GW triggers (Phase 5).

Every conclusion traces to a computed number. See
[`SCIENCE_GOALS.md`](SCIENCE_GOALS.md) and `AGD_FORWARD_PLAN.md` §2.4.

### Longer horizon
- Databricks/Delta deployment, Kafka streaming, monitoring dashboards
- Rubin/LSST-scale ingestion

## Contributing

Contributions welcome! Please read through the codebase, run the tests, and open a PR with your changes.

## License

MIT License — see [LICENSE](LICENSE) for details.

## Acknowledgments

- [Fink Broker](https://fink-broker.org/) for providing the alert stream API
- [ZTF](https://www.ztf.caltech.edu/) for the transient survey data
- [Databricks](https://databricks.com/) for the lakehouse platform
