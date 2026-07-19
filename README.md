# Agentic Galactic Discovery

**A provenance-first laboratory for finding the unexpected in the transient sky.**

Survey telescopes repeatedly image the sky and report what changed. Most alerts
have familiar explanations: variable stars, moving objects, active galaxies, or
ordinary supernovae. The interesting problem is deciding which small fraction
deserves scarce follow-up time without quietly discarding the genuinely
unexpected.

Agentic Galactic Discovery (AGD) is an early-stage, open-source research
pipeline for exploring that problem with public ZTF/Fink alerts and astronomy
catalogues. It turns bounded alert batches into validated, enriched, and
auditable candidates for human review, then measures where its own routing
logic succeeds or fails. A separate, downstream science layer uses published
cosmological constraints and lens statistics to ask more targeted questions
about gravity and the dark sector.

The distinction matters: **an unusual light curve can reveal a new object; it
does not, by itself, reveal new physics.**

> **Development snapshot:** Bronze, Silver, Gold, deterministic
> classification/anomaly assessment, Euclid Q1 tooling, constraint notebooks,
> and a bounded calibration replay are implemented. Kafka streaming,
> Spark/Delta-scale processing, Rubin ingestion, and the gravitational-wave
> counterpart channel are not yet implemented. There are no LLM calls in the
> ingestion or processing path.

[`SCIENCE_GOALS.md`](SCIENCE_GOALS.md) defines the scientific rules of
inference. [`AGD_FORWARD_PLAN.md`](AGD_FORWARD_PLAN.md) contains the detailed
roadmap and current evidence. [`AGENTS.md`](AGENTS.md) is the contributor and
coding-agent contract.

## Two Questions, Kept Deliberately Separate

AGD supports two complementary modes of inquiry. They share data and
infrastructure, but not conclusions.

### 1. What changed, and is it worth a closer look?

The **agnostic discovery path** ingests time-domain alerts, rejects poor-quality
detections, cross-matches known catalogues, characterizes light curves, and
routes unusual or time-critical events for review. It has no preferred theory
to confirm.

This path is designed for questions such as:

- Is an apparently extragalactic transient actually a nearby variable star?
- Does a light curve evolve too quickly, too slowly, or differently across
  filters for its proposed class?
- Is a candidate coincident with a known strong-lens field and therefore worth
  immediate follow-up?
- Which labelled rare events are being missed, and which routine events are
  creating false alarms?

### 2. What can populations and precision measurements tell us about physics?

The **constraint-science path** is hypothesis-driven and strictly downstream
of the alert pipeline. It compares ensemble statistics and published
measurements with explicit standard-model expectations before discussing
alternatives such as evolving dark energy or modified gravity.

The three science channels are:

1. **Combined probes:** DESI BAO, CMB, supernovae, and weak-lensing constraints
   on the dark-energy equation of state, growth, and `S8`.
2. **Strong-lens statistics:** Euclid lens abundance and profile measurements,
   with the sensitivity floor stated explicitly. Euclid Q1 is a capability
   demonstration, not a cosmological-parameter fit.
3. **Gravitational-wave standard sirens:** the planned multi-messenger channel
   linking rapid optical-counterpart discovery with tests of gravitational-wave
   propagation.

The processing pipeline never imports constraint analyses. Anomaly flags remain
agnostic; physical interpretation belongs in dedicated analyses and human
review.

## From an Alert to a Reviewable Candidate

```text
                         AGNOSTIC DISCOVERY PATH

  Fink/ZTF REST       Bronze             Silver              Gold
  alert records  -->  raw + source  -->  validated +   -->   catalog context +
                      provenance         replay-safe         light-curve features
                                               |                    |
                                               |                    v
                                               |             deterministic classifier
                                               |                    |
                                               +------------------> v
                                                          anomaly assessment
                                                                    |
                                                                    v
                                                          human-readable report

                      CONSTRAINT-SCIENCE PATH (DOWNSTREAM)

            published constraints + Euclid lens catalogues --> notebooks
```

| Stage | What it does today | Key guarantee |
|---|---|---|
| **Bronze** | Canonicalizes Fink's prefixed fields and stores the original payload with ingestion metadata. | Source records remain auditable. |
| **Silver** | Validates coordinates, time, filter, and photometry; applies quality gates; deduplicates candidates. | Replay-idempotent writes preserve nullable, full-precision ZTF candidate IDs and provenance. |
| **Gold** | Adds Gaia DR3/SIMBAD context, stellar discrimination, Euclid lens-field matching, and per-filter light-curve features. | Derived results retain source and processing identifiers. |
| **Classifier** | Uses the Fink label and deterministic evidence agreement to assign class, confidence, alternatives, anomaly score, and priority. | No hidden model or LLM decision in the hot path. |
| **Anomaly assessment** | Adds a baseline comparison, deviation estimate, trials-corrected false-alarm heuristic, and systematic checks to flagged events. | Flags explain why an event was routed. |
| **Report** | Produces Markdown, JSON, and Parquet outputs for a scoped batch or night. | Review counts and trials cannot silently mix unrelated nights. |

Lens-field transients always receive `CRITICAL` priority. The future
gravitational-wave counterpart flag is designed to receive the same treatment.

### Light Curves Without Mixing Colour and Time

ZTF observes in multiple filters. Alternating between a faint `g`-band
measurement and a brighter `r`-band measurement can look like dramatic
variability if the filters are combined indiscriminately.

Gold therefore computes independent `g`/`r`/`i` features, including detection
count, time span, weighted magnitude, amplitude and rate with propagated
photometric uncertainty, and cadence. Earlier same-object rows from a Fink
object-history batch are included; future observations and repeated epochs are
excluded. These features feed the deterministic routing logic and the
calibration replay.

## Current State of Development

| Capability | State | Notes |
|---|---|---|
| Fink/ZTF REST ingestion | Implemented | Public API, canonical field mapping, configurable timeout/retry/backoff, visible parse failures. |
| Bronze/Silver processing | Implemented | Quality gates, provenance, Parquet/JSON output, replay-idempotent Silver. |
| Gaia DR3/SIMBAD enrichment | Implemented | Cone searches, retry/cache behavior, stellar/extragalactic evidence, graceful degradation. |
| Euclid Q1 tooling | Implemented | MER access scaffold, SLDE lens catalogue processing, lens-field transient matching. |
| Per-filter light-curve features | Implemented | Uncertainty- and cadence-aware; compatible with bounded Fink history replay. |
| Classification/anomaly assessment | Implemented | Deterministic, explainable routing and scoped nightly reports. |
| Constraint and lensing notebooks | Implemented | Published-value provenance and explicit sensitivity floors. |
| Labelled calibration replay | Implemented | BTS/Fink replay, object-disjoint temporal evaluation, measured false positives and misses. |
| GW counterpart channel | Planned | GraceDB/GCN ingestion, skymap filtering, counterpart escalation, standard-siren notebook. |
| Kafka, Spark/Delta, Rubin-scale processing | Future | Local processing currently uses pandas/PyArrow and Parquet/JSON; Delta is explicitly rejected. |

The current implementation is a **bounded research pipeline**, not a
production real-time broker. Runs are manual by default. The calibration CLI
defaults to 100 alerts and enforces a 1,000-alert total hard cap so exploratory
work remains inexpensive and reviewable.

## Quick Start

### Install

AGD supports Python 3.11 and 3.12.

```bash
git clone <repository-or-fork-url> agd
cd agd

python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Runtime configuration is provided by `src/utils/config.py` through environment
variables or an optional `.env` file. `config/default.yaml` is a planning
reference and is not loaded by the application.

```bash
# Optional runtime overrides
export STORAGE_BASE_PATH=./data
export FINK_TIMEOUT_SECONDS=30
export FINK_MAX_RETRIES=3
```

The default Fink endpoint is `https://api.ztf.fink-portal.org`. Local storage
supports Parquet and JSON. Requesting Delta fails explicitly until a real Delta
writer is implemented.

### Run the Pipeline Offline

Exercise Bronze, Silver, and Gold without external services:

```bash
PYTHONPATH=. python scripts/run_fink_gold_smoke.py \
  --source synthetic \
  --no-crossmatch \
  --limit 25 \
  --storage-base /tmp/agd-smoke
```

Generate a scoped review report from the resulting Gold data:

```bash
PYTHONPATH=. python scripts/nightly_report.py \
  --gold-path /tmp/agd-smoke/gold/alerts \
  --output-dir /tmp/agd-smoke/reports
```

The report contains classification counts, follow-up priorities, lens-field
matches, anomaly assessments, provenance, and system metrics.

### Run a Small Live Fink Smoke

With network access to the public Fink API:

```bash
PYTHONPATH=. python scripts/run_fink_silver_smoke.py \
  --class "SN candidate" \
  --limit 25 \
  --storage-base /tmp/agd-fink-smoke
```

For Gold enrichment, use `run_fink_gold_smoke.py`. Add `--no-crossmatch` when
Gaia/SIMBAD egress is unavailable; catalog fields will remain null rather than
blocking the batch.

### Replay Labelled Objects and Measure Failure Modes

The bundled manifest contains a small set of independently labelled ZTF Bright
Transient Survey (BTS) objects. The replay fetches bounded Fink histories,
processes them through the medallion, and evaluates classification and routing
on temporally separated cohorts:

```bash
PYTHONPATH=. python scripts/run_fink_calibration_replay.py \
  --manifest tests/fixtures/calibration/ztf_bts_replay_manifest.json \
  --split-date 2021-01-01 \
  --max-objects 20 \
  --max-alerts 100 \
  --max-alerts-per-object 100 \
  --no-crossmatch
```

The output includes predictions and metrics for classification accuracy,
precision, recall, false-positive rate, and missed labelled review targets.
Long-lived objects crossing the split contribute only post-split predictions;
their earlier photometry can still inform later features without placing the
same object in both evaluation cohorts.

`truth_is_rare` means **worth reviewing**, not **evidence of new physics**.
The current anomaly score and false-alarm calculation are routing heuristics,
not empirically calibrated discovery significances.

## What the First Live Calibration Run Tells Us

A bounded 100-alert BTS/Fink replay was run on 19 July 2026 with catalog
cross-matching disabled. Eight labelled objects returned data. All 100 alerts
passed Bronze, Silver, and Gold with no Silver rejections, duplicate candidate
IDs, invalid coordinates/photometry, or null provenance. Gold recovered
multi-epoch history for 92 alerts and repeated-filter features for 88.

The routing results are more instructive than the successful plumbing:

| Cohort | Composition | Result |
|---|---|---|
| **Training-era diagnostic** | 27 TDE/LBV review targets and 13 SN IIP controls | 1/27 review targets flagged: **3.7% recall, 26 misses**; no control false positives. |
| **Temporal holdout** | 60 SN Ia controls; no rare targets | One false positive: **1.7%**; rare-event recall is undefined. |

Comparable coarse-class accuracy was `12/13` in the training-era diagnostic
and `27/43` in the holdout. These are small-sample diagnostics, not a measure
of survey performance.

The immediate scientific conclusion is straightforward: **the pipeline can
replay and characterize real alerts, but the present routing heuristic is not
yet useful for reliable rare-event discovery.** The next calibration step is to
expand and balance the labelled temporal holdout, especially with rare
post-split targets, then measure and tune missed-event and false-positive
rates before adding scheduled compute or new science channels.

## Scientific Scope and Guardrails

AGD follows three tiers from [`SCIENCE_GOALS.md`](SCIENCE_GOALS.md):

1. **Validation:** classify familiar transient populations, including
   supernovae, kilonova candidates, active galaxies, variable stars, and
   Solar System objects.
2. **Discovery:** flag unexpected light-curve, spatial, colour, temporal, or
   cross-reference behavior and escalate lens-field transients. No theoretical
   interpretation is attached to an anomaly flag.
3. **Constraints:** test explicit physical hypotheses using ensemble or
   multi-messenger observables in reproducible, downstream analyses.

Every anomaly assessment is expected to state its baseline, deviation,
false-alarm context, and known-systematic checks. Every constraint analysis
must first reproduce the published baseline, state its sensitivity floor, and
only then compare theory space. Null results are results.

### Data Sources and Their Roles

| Source | Role in AGD |
|---|---|
| **ZTF/Fink** | Time-domain testbed: public alert retrieval, classification context, and light-curve history. |
| **Gaia DR3/SIMBAD** | Astrometric and object context for stellar/extragalactic discrimination and cross-match checks. |
| **Euclid Q1** | Schema and strong-lens capability demo; roughly 500 lens candidates over 63.1 square degrees. |
| **Euclid DR1-Foundation** | Planned lensing/growth upgrade and larger lens-statistics sample. |
| **DESI, CMB, SNe Ia, KiDS/DES weak lensing** | Published combined-probe constraints used by the analysis notebooks. |
| **LIGO/Virgo/KAGRA** | Planned public-alert and standard-siren channel requiring rapid optical counterpart identification. |

Euclid Q1 is intentionally not used to claim cosmological-parameter
constraints. The strong-lens notebook reports the optimistic counting-only
three-sigma abundance floor: about 13.4% for `N ~= 500` and 3.6% for
`N ~= 7000`, before completeness, purity, sample variance, or modeling
systematics.

## Repository Guide

```text
src/
  ingestion/     Fink REST and Euclid TAP clients
  models/        Alert, classification, cross-match, and lens data contracts
  processing/    Bronze, Silver, Gold, lens processing, deterministic classifier
  crossref/      Gaia DR3/SIMBAD clients and coordinate/cache utilities
  agents/        Deterministic warm-path anomaly assessment
  analysis/      Calibration, cosmology constraints, and lensing utilities

scripts/
  run_fink_silver_smoke.py       Live Fink -> Bronze -> Silver
  run_fink_gold_smoke.py         Live/synthetic -> Bronze -> Silver -> Gold
  run_fink_calibration_replay.py Bounded BTS/Fink replay and routing metrics
  nightly_report.py              Classification and anomaly-review outputs
  ingest_euclid_q1.py            Euclid Q1 catalogue ingestion

notebooks/
  combined_probe_constraints.ipynb  Published cosmological-constraint harness
  euclid_lens_statistics.ipynb      Strong-lens toolkit and sensitivity floor

tests/           Unit, data-quality, integration-gated, and replay tests
```

## Development and Validation

Run the local validation suite before publishing changes:

```bash
python -m ruff check src/ tests/ scripts/
python -m black --check src/ tests/ scripts/
python -m pytest tests/ -v
```

Live integrations are opt-in:

```bash
AGD_RUN_INTEGRATION_TESTS=1 python -m pytest tests/ -m integration -v
```

Gaia's TAP client can require an explicit CONNECT proxy in restricted network
environments. Set `CROSSMATCH_TAP_PROXY_URL` and, when TLS is re-terminated,
`CROSSMATCH_TAP_CA_BUNDLE`. Offline tests use fixtures and mocked services.

The current validated development snapshot has **274 passing tests and 7
live-gated skips**. Scientific and pipeline changes should include focused
regression coverage and preserve the Bronze -> Silver -> Gold contract.

## Roadmap

The detailed acceptance criteria and handoff notes live in
[`AGD_FORWARD_PLAN.md`](AGD_FORWARD_PLAN.md).

| Phase | Focus | State |
|---|---|---|
| **0. Repository convergence** | Runtime configuration, UTC handling, contributor contract. | Implemented |
| **1. Gold and cross-match** | Gaia/SIMBAD enrichment and stellar discrimination. | Implemented |
| **2. Euclid Q1** | MER/SLDE tooling and lens-field matching. | Implemented |
| **3. Constraint and lensing harness** | Published cosmological constraints and strong-lens statistics. | Implemented |
| **4. Classification and anomaly assessment** | Deterministic routing, rigor fields, and nightly report. | Implemented |
| **4.5. Reliability and calibration** | Replay safety, per-filter features, and labelled temporal evaluation. | Implemented on the current development branch |
| **5. GW counterpart channel** | Public GW triggers, skymap filtering, counterpart escalation, standard-siren analysis. | Planned |

Longer-term work includes larger labelled replays, Rubin/LSST ingestion,
streaming, scale-out storage/processing, and operational monitoring. None of
those should precede evidence that the bounded review loop is scientifically
useful.

## References and Acknowledgments

AGD builds on openly available astronomy services and published results:

- [Fink ZTF documentation](https://doc.ztf.fink-broker.org/) and the
  [Fink Broker](https://fink-broker.org/)
- [Zwicky Transient Facility](https://www.ztf.caltech.edu/) and the
  [ZTF Bright Transient Survey Sample Explorer](https://sites.astro.caltech.edu/ztf/bts/explorer.php)
- [Euclid Q1 strong-lens catalogue paper](https://arxiv.org/abs/2503.15324)
- [DESI DR2 BAO results](https://arxiv.org/abs/2503.14738)
- [GW170817 dimensional-constraint analysis](https://arxiv.org/abs/1801.08160)

See [`SCIENCE_GOALS.md`](SCIENCE_GOALS.md) for the full scientific context and
[`AGD_FORWARD_PLAN.md`](AGD_FORWARD_PLAN.md) for source provenance, release
checkpoints, and phase-level detail.

## License

MIT. See [`LICENSE`](LICENSE).
