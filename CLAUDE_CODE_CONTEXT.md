# Claude Code Context — Agentic Galactic Discovery

> **This document is the primary context file for Claude Code sessions working on this project. Read this first.**

## Project Owner

**Parth** — Solutions Architect at Databricks (London), specializing in GenAI and data engineering. Background in computer engineering + MBA + consulting. Deep interest in theoretical physics and cosmology — this project bridges professional Databricks expertise with scientific curiosity about the fundamental nature of reality.

## What This Project Is

An open-source platform for **real-time astronomical transient discovery** using agentic AI. We ingest streaming alert data from telescope surveys (ZTF now, Rubin/LSST in 2026), process it through a Databricks lakehouse, and use AI agents to classify events and — crucially — detect anomalies that might represent genuinely new physics.

## Current Status

**Phase 1: Foundation** — We're starting from scratch. The first goal is:
1. Build a working Fink REST API client that can pull recent ZTF transient alerts
2. Set up the Delta Lake medallion architecture (bronze/silver/gold)
3. Create a basic triage agent that classifies alerts
4. Add cross-referencing against Gaia DR3 and SIMBAD catalogs
5. Establish testing framework from day one

## Key Technical Decisions

### Why Fink API First (Not Raw Kafka)
The Fink broker already processes ZTF alerts via Spark Structured Streaming and exposes a public REST API at `https://api.fink-portal.org`. This gives us immediate access to enriched alert data without needing Kafka auth. We'll add Kafka streaming in Phase 2.

### Databricks Stack
Parth works at Databricks — this isn't just familiarity but genuine technical fit:
- Spark Structured Streaming handles the alert volume natively
- Delta Lake provides ACID, time travel, and schema evolution for the medallion architecture
- Unity Catalog handles data governance and lineage
- MLflow for experiment tracking of our ML classifiers
- All open-source components (Delta, Spark, MLflow)

### Agent Architecture
We use LLM-orchestrated agents (Claude API) for high-level scientific reasoning, but **not** for the hot path. The processing pipeline is:
1. **Hot path** (Spark): Ingest → clean → basic classification (ML models, not LLM)
2. **Warm path** (Agents): Flagged interesting events → LLM triage → cross-reference → anomaly assessment
3. **Cold path** (Human): Genuinely anomalous events → detailed report → human astronomer review

### Testing Philosophy
Science demands rigor. Every component needs:
- Unit tests for individual functions
- Integration tests for pipeline stages
- Data quality tests (Great Expectations) for each medallion layer
- Known-object tests: feed the system alerts for well-characterized objects and verify correct classification
- Regression tests: when we improve classifiers, old correct classifications must not break

## Development Guidelines for Claude Code

### Code Style
- Python 3.11+
- Type hints everywhere
- Docstrings on all public functions (Google style)
- `ruff` for linting, `black` for formatting
- Pydantic for data models and configuration
- Structured logging (not print statements)

### Dependency Management
- Use `pyproject.toml` as the source of truth
- Pin major versions, allow minor/patch updates
- Core dependencies: `astropy`, `astroquery`, `requests`, `pydantic`, `pandas`, `pyarrow`
- For Databricks: `delta-spark`, `pyspark` (development stubs only — runs on cluster)
- For agents: `anthropic` (Claude API client)
- For testing: `pytest`, `pytest-asyncio`, `great-expectations`

### Naming Conventions
- Files: `snake_case.py`
- Classes: `PascalCase`
- Functions/variables: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Astronomical IDs: preserve original format (e.g., `ZTF21aaxtctv`)

### Error Handling
- Custom exception hierarchy rooted in `AGDError`
- Never silently swallow errors in the data pipeline
- Retry with exponential backoff for external API calls
- Log full context on failures (alert ID, processing stage, error details)

## Critical API References

### Fink REST API

Base URL: `https://api.fink-portal.org`

**Get object by ZTF ID:**
```python
import requests
r = requests.post(
    "https://api.fink-portal.org/api/v1/objects",
    json={"objectId": "ZTF21aaxtctv", "output-format": "json"}
)
```

**Search by date (get alerts for a given night):**
```python
r = requests.post(
    "https://api.fink-portal.org/api/v1/latests",
    json={
        "class": "Early SN Ia candidate",
        "n": "10",
        "output-format": "json"
    }
)
```

**Cone search:**
```python
r = requests.post(
    "https://api.fink-portal.org/api/v1/explorer",
    json={
        "ra": "193.822",
        "dec": "2.896",
        "radius": "5",
        "output-format": "json"
    }
)
```

### Fink Classification Labels
Fink assigns machine-learning classifications to alerts. Key classes include:
- `SN candidate` — Supernova candidate
- `Early SN Ia candidate` — Early-stage Type Ia supernova
- `Kilonova candidate` — Neutron star merger remnant
- `Microlensing candidate` — Gravitational microlensing
- `Solar System MPC` — Known solar system object
- `Variable Star` — Various variable star types
- `AGN` — Active galactic nuclei
- `Unknown` — Unclassified

### SIMBAD (via astroquery)
```python
from astroquery.simbad import Simbad
result = Simbad.query_region("193.822 2.896", radius="5s")
```

### Gaia DR3 (via astroquery)
```python
from astroquery.gaia import Gaia
job = Gaia.launch_job_async(
    "SELECT * FROM gaiadr3.gaia_source "
    "WHERE CONTAINS(POINT('ICRS', ra, dec), "
    "CIRCLE('ICRS', 193.822, 2.896, 0.001)) = 1"
)
result = job.get_results()
```

## Astronomy Concepts for Code Context

### Alert Structure (ZTF)
Each ZTF alert contains:
- **candidId**: Unique alert identifier
- **objectId**: ZTF object identifier (e.g., `ZTF21aaxtctv`)
- **ra, dec**: Right ascension and declination (sky coordinates, degrees)
- **magpsf**: PSF magnitude (brightness — lower = brighter)
- **sigmapsf**: Magnitude uncertainty
- **fid**: Filter ID (1=g, 2=r, 3=i bands)
- **jd**: Julian date of observation
- **diffmaglim**: Limiting magnitude of the difference image
- **prv_candidates**: Previous 30 days of detections (light curve history)
- **cutoutScience/Template/Difference**: Image stamps (when available)

### Medallion Architecture for Alerts

**Bronze**: Raw alerts as-received, minimal transformation. Append-only. Preserves everything including image cutouts.

**Silver**: Cleaned and validated alerts. Schema enforced. Deduplication applied. Bad detections filtered. Coordinates standardized. Time converted to standard formats (JD, MJD, ISO).

**Gold**: Enriched alerts. Cross-matched with Gaia, SIMBAD, TNS. Light curve features computed. ML classifications attached. Ready for agent consumption.

### Key Astronomical Measures
- **Magnitude**: Logarithmic brightness scale. Each step of 1 mag = 2.512x brightness change. Fainter objects have HIGHER magnitudes. ZTF reaches ~20.5 mag.
- **Julian Date (JD)**: Continuous day count used in astronomy. JD 2460000 ≈ Feb 2023.
- **Modified Julian Date (MJD)**: MJD = JD - 2400000.5. More convenient for modern dates.
- **Right Ascension (RA)**: Celestial longitude, 0-360 degrees (or 0-24 hours)
- **Declination (Dec)**: Celestial latitude, -90 to +90 degrees

## What To Build First

When starting a Claude Code session, the immediate priorities are:

1. **`pyproject.toml`** — Project configuration with all dependencies
2. **`src/ingestion/fink_api_client.py`** — Robust Fink API client with retry logic, rate limiting, and pagination
3. **`src/utils/config.py`** — Pydantic-based configuration management
4. **`src/processing/bronze_processor.py`** — Bronze layer: receive alerts, validate schema, write to Delta-compatible format
5. **`tests/test_ingestion/test_fink_api_client.py`** — Tests for the Fink client

The system should be demonstrable end-to-end as soon as possible: pull alerts from Fink → store in bronze → basic classification → display results.

## Open Questions & Decisions Needed

- **Agent framework**: Pure Claude API tool-use vs. LangChain vs. custom orchestration?
- **Dashboard**: Streamlit (simpler) vs. Plotly Dash (more flexible)?
- **Alert storage format**: Parquet files locally for development, Delta Lake on Databricks for production?
- **Image handling**: Store cutout images in the medallion architecture or separate object store?
- **Scheduling**: Databricks workflows vs. Airflow vs. simple cron for nightly batch processing?

## Links & Resources

- Fink API docs: https://fink-broker.readthedocs.io
- Fink tutorials: https://github.com/astrolabsoftware/fink-tutorials
- ZTF alert schema: https://zwickytransientfacility.github.io/alert_stream/
- Rubin/LSST early science: https://rubinobservatory.org/for-scientists/resources/early-science
- ANTARES client: https://pypi.org/project/antares-client/
- astropy: https://www.astropy.org/
- astroquery: https://astroquery.readthedocs.io/
