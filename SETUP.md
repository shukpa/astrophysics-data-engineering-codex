# Setup Guide

## Prerequisites

- Python 3.11+
- Git
- (Optional) Databricks CLI — for deploying to Databricks workspace
- (Optional) Docker — for local Kafka testing in Phase 2

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

Copy the example environment file and fill in your API keys:

```bash
cp .env.example .env
```

Required environment variables:
```bash
# Anthropic API key (for agent layer)
ANTHROPIC_API_KEY=sk-ant-...

# Optional: Fink livestream credentials (Phase 2)
FINK_USERNAME=
FINK_GROUP_ID=
FINK_SERVERS=

# Optional: Databricks (for deployment)
DATABRICKS_HOST=
DATABRICKS_TOKEN=
```

The Fink REST API requires **no authentication** for Phase 1. You can start immediately.

### 3. Verify Installation

```bash
# Run the connection test
python -m src.ingestion.fink_api_demo

# Run the test suite
pytest tests/ -v

# Check linting
ruff check src/ tests/
```

### 4. Download Sample Data

For offline development and testing:

```bash
python scripts/download_sample_data.py
```

This downloads a curated set of alert data to `data/sample_alerts/`.

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

# Create cluster configuration
databricks clusters create --json-file config/databricks_cluster.json
```

## Project Dependencies

### Core (always needed)
- `astropy` — Astronomical computations, coordinate transforms
- `astroquery` — Query astronomical databases (SIMBAD, Gaia, VizieR)
- `requests` — HTTP client for Fink API
- `pydantic` — Data models, configuration, validation
- `pandas` — DataFrame operations
- `pyarrow` — Parquet file handling (Delta-compatible)
- `pyyaml` — Configuration file parsing

### Agents (Phase 3)
- `anthropic` — Claude API client
- (Future: evaluate LangChain vs custom orchestration)

### Streaming (Phase 2)
- `fink-client` — Fink Kafka consumer
- `confluent-kafka` — Kafka client library
- `fastavro` — Fast Avro serialization

### Databricks (production deployment)
- `delta-spark` — Delta Lake (dev stubs, actual runtime on Databricks)
- `pyspark` — Spark (dev stubs, actual runtime on Databricks)
- `mlflow` — Experiment tracking

### Development
- `pytest` — Testing framework
- `pytest-asyncio` — Async test support
- `pytest-cov` — Coverage reporting
- `ruff` — Linting
- `black` — Code formatting
- `great-expectations` — Data quality validation
- `httpx` — Async HTTP client (for testing)

## Fink Livestream Registration (Phase 2)

To receive real-time Kafka alerts from Fink:

1. Fill the registration form at https://fink-broker.readthedocs.io/en/latest/services/livestream/
2. Fink will send credentials (username, group_id, servers)
3. Register locally: `fink_client_register -username <USER> -group_id <GID> -servers <SERVERS>`
4. Test: `fink_consumer --display -limit 1`
