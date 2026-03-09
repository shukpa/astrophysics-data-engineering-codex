# Agentic Galactic Discovery

**Real-time astronomical transient discovery using agentic AI**

An open-source platform for detecting and classifying astronomical transients from telescope survey data. We ingest streaming alerts from ZTF (and soon Rubin/LSST), process them through a Databricks lakehouse architecture, and use AI agents to identify genuinely anomalous events that might represent new physics.

Development workflow in this repo is Codex-first. See `AGENTS.md` for the active agent instructions and operating conventions.

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
astrophysics-data-engineering/
├── src/
│   ├── __init__.py
│   ├── exceptions.py           # Custom exception hierarchy (AGDError)
│   ├── models/
│   │   ├── __init__.py
│   │   └── alerts.py           # Pydantic models for ZTF/Fink alerts
│   ├── ingestion/
│   │   └── __init__.py         # (Future: Fink API client)
│   ├── processing/
│   │   ├── __init__.py
│   │   └── bronze_processor.py # Bronze layer processing
│   ├── utils/
│   │   ├── __init__.py
│   │   └── config.py           # Pydantic-based configuration
│   └── agents/
│       └── __init__.py         # (Future: AI agent implementations)
├── tests/
│   ├── conftest.py             # Shared pytest fixtures
│   ├── test_processing/
│   │   └── test_bronze_processor.py
│   └── test_utils/
│       └── test_config.py
├── pyproject.toml              # Project configuration & dependencies
└── README.md
```

## Current Status

**Phase 1: Foundation** — Building the core infrastructure:

- [x] Project structure and configuration
- [x] Custom exception hierarchy
- [x] Pydantic models for ZTF alerts
- [x] Bronze layer processor
- [x] Test framework
- [x] Fink API client with retry logic
- [ ] Silver layer processor
- [ ] Gold layer with cross-matching
- [ ] Basic triage agent

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
OPENAI_API_KEY=your-api-key  # For future agent features
```

The runtime source of truth is `src/utils/config.py`. `config/default.yaml` is currently a planning/defaults artifact and is not loaded by the application runtime.

### Running Tests

```bash
pytest                          # Run all tests
pytest -m "not integration"     # Skip integration tests
pytest --cov=src                # With coverage report
```

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
| AI Agents | OpenAI API | Scientific reasoning and anomaly assessment |
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

### Phase 1: Foundation (Current)
- Core infrastructure, bronze layer, Fink client

### Phase 2: Pipeline
- Silver/gold layers, cross-matching with Gaia/SIMBAD, basic ML classification

### Phase 3: Agents
- OpenAI-powered triage agent, anomaly detection, report generation

### Phase 4: Production
- Databricks deployment, Kafka streaming, monitoring dashboards

## Contributing

Contributions welcome! Please read through the codebase, run the tests, and open a PR with your changes.

## License

MIT License — see [LICENSE](LICENSE) for details.

## Acknowledgments

- [Fink Broker](https://fink-broker.org/) for providing the alert stream API
- [ZTF](https://www.ztf.caltech.edu/) for the transient survey data
- [Databricks](https://databricks.com/) for the lakehouse platform
