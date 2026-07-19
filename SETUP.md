# Setup Guide

## Prerequisites

- Python 3.11+
- Git
- (Optional) Databricks CLI — for deploying to Databricks workspace
- (Optional) Docker — for future local Kafka testing

## Local Development Setup

### 1. Clone and Install

```bash
git clone https://github.com/<your-org>/agentic-galactic-discovery.git
cd agentic-galactic-discovery

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Install in development mode
pip install -e ".[dev]"
```

### 2. Configuration

Create a `.env` file in the repo root for optional runtime configuration:

```bash
touch .env
```

Optional environment variables:
```bash
# Optional: Fink livestream credentials for future Kafka ingestion
FINK_USERNAME=
FINK_GROUP_ID=
FINK_SERVERS=

# Optional: Databricks (for deployment)
DATABRICKS_HOST=
DATABRICKS_TOKEN=
```

The public ZTF/Fink REST API (`https://api.ztf.fink-portal.org`) requires **no authentication**. You can start immediately.

`src/utils/config.py` is the runtime configuration source of truth. `config/default.yaml` is currently a planning artifact and is not loaded automatically.

### 3. Verify Installation

```bash
# Run the test suite
pytest tests/ -v

# Check linting
ruff check src/ tests/
```

### 4. Run an Offline Smoke Test

For offline development and testing:

```bash
PYTHONPATH=. python scripts/run_fink_gold_smoke.py \
  --source synthetic --no-crossmatch --storage-base /tmp/agd-smoke
```

This exercises the bounded bronze -> silver -> gold path without external services.

### 5. Run the Labelled Calibration Replay

The bundled BTS manifest contains independently labelled ZTF objects. Fetch their
bounded Fink histories, split them temporally, and report classification and
routing diagnostics:

```bash
PYTHONPATH=. python scripts/run_fink_calibration_replay.py \
  --manifest tests/fixtures/calibration/ztf_bts_replay_manifest.json \
  --split-date 2021-01-01 --max-objects 20 --max-alerts 100 \
  --max-alerts-per-object 100 \
  --no-crossmatch
```

This command requires Fink egress. The anomaly score and trials-corrected FAP
remain routing heuristics until evaluated on a sufficiently large, independent
replay set; the bundled manifest is a capability smoke, not a discovery claim.
The default run is 100 alerts and the total-alert hard cap is 1,000.

## Databricks Workspace Setup

### Option A: Databricks Community Edition (Free)

1. Sign up at https://community.cloud.databricks.com
2. Create a cluster with Spark 3.5+ and Python 3.11+
3. Upload notebooks from `notebooks/` directory
4. Install libraries: `astropy`, `astroquery`, `requests`

### Option B: Full Databricks Workspace

```bash
# Install CLI
pip install databricks-cli

# Configure
databricks configure --token

# Deploy notebooks
databricks workspace import_dir notebooks/ /Shared/agd/

```

Configure any external cluster separately. The local processors support Parquet
and JSON only; Delta mode is explicitly rejected until a real Delta writer is
implemented.

## Project Dependencies

### Core (always needed)
- `astropy` — Astronomical computations, coordinate transforms
- `astroquery` — Query astronomical databases (SIMBAD, Gaia, VizieR)
- `requests` — HTTP client for Fink API
- `pydantic` — Data models, configuration, validation
- `pandas` — DataFrame operations
- `pyarrow` — Parquet file handling (Delta-compatible)
- `pyyaml` — Configuration file parsing

### Agents
- The deterministic classifier and anomaly agent require no provider runtime
- Future LLM orchestration must remain outside the real-time hot path

### Streaming (future)
- `fink-client` — Fink Kafka consumer
- `confluent-kafka` — Kafka client library
- `fastavro` — Fast Avro serialization

### Databricks (future deployment)
- `delta-spark` — optional future Delta Lake runtime
- `pyspark` — optional future Spark runtime
- `mlflow` — Experiment tracking

### Development
- `pytest` — Testing framework
- `pytest-asyncio` — Async test support
- `pytest-cov` — Coverage reporting
- `ruff` — Linting
- `black` — Code formatting
- `great-expectations` — Data quality validation
- `httpx` — Async HTTP client (for testing)

## Fink Livestream Registration (future streaming)

To receive real-time Kafka alerts from Fink:

1. Fill the registration form at https://fink-broker.readthedocs.io/en/latest/services/livestream/
2. Fink will send credentials (username, group_id, servers)
3. Register locally: `fink_client_register -username <USER> -group_id <GID> -servers <SERVERS>`
4. Test: `fink_consumer --display -limit 1`
