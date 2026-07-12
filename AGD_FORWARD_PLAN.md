# AGD Forward Plan — Euclid Integration, Multi-Probe Constraints & Repo Convergence

**Date:** 2026-07-12
**Target repo:** `github.com/shukpa/astrophysics-data-engineering-codex` (HEAD: `9561de3`, PR #1 merged)
**Execution environment:** agent-agnostic — currently Claude (Fable) via Claude Code; subsequently Codex + GPT 5.6 Sol
**Purpose:** Carry AGD forward from the Codex-evolved silver pipeline into the gold layer, Euclid open-data integration, and a rigorous (falsifiable) treatment of the extra-dimensional/dark-matter thread. Incorporates the data-source assessment from the project's Euclid/JWST/Gaia comparison chat, with release dates corrected to the post-June-2026 revised Euclid timeline.

**Multi-agent operating model (deliberate, do not undo):** This repo is evolved by multiple AI toolchains in rotation — currently Claude (Fable) executing this plan, then Codex + GPT 5.6 Sol for further evolution. The removal of `CLAUDE.md`/`CLAUDE_CODE_CONTEXT.md` was a deliberate de-provider-ing of the repo. **`AGENTS.md` is the single, provider-neutral operating contract for every agent.** No agent re-introduces provider-specific context files, model assumptions, or tooling lock-in. Coordination between agents happens through three artifacts only: `AGENTS.md` (rules), this plan file committed to the repo (roadmap + phase state), and PR history (provenance). Each phase's PR description must state what was done and what the next agent needs to know, so a different toolchain can pick up any phase cold.

---

## 1. Repo vetting summary (verified 2026-07-12)

### What was checked
Cloned HEAD, reviewed all 4 commits, read the new silver processor and smoke script in full, ran the full test suite and ruff in a sandbox.

### Verdict: healthy, mergeable state
- **72/72 unit tests pass** (4 integration tests deselected). Failures initially observed were environment-only (sandbox had Python 3.10; repo requires 3.11+ for `enum.StrEnum`, plus `astropy` and `responses` needed installing).
- **`ruff check src/ scripts/ tests/` — clean** on the untouched tree.
- **Commit history:** `3b02c87` initial scaffold synced from the Claude Code repo → `c39b195` Codex migration (deleted `CLAUDE.md` + `CLAUDE_CODE_CONTEXT.md`, added `AGENTS.md`) → `aa3ba17`/`9561de3` (PR #1, merged 2026-07-12): provider-neutral silver pipeline.

### What PR #1 added (good quality)
- `src/processing/silver_processor.py` (337 lines): quality gates (finite ra/dec/magpsf/sigmapsf/jd, `sigmapsf ≤ 1.0`, `rb ≥ 0.2` — consistent with `config/default.yaml` rejection filters), dedup keyed on `candid` with fallback `(object_id, jd, fid)`, ranked by `drb → rb → ingestion_timestamp`. Full provenance: bronze processing ID, source IDs, SHA-256 of the canonicalised raw payload plus the payload JSON itself.
- `src/ingestion/fink_api_client.py`: canonicalisation of Fink's `i:`/`v:`/`d:` field prefixes into the pipeline's unprefixed schema — a real correctness fix for live API responses.
- `scripts/run_fink_silver_smoke.py`: live bronze→silver smoke run with optional Databricks `CREATE TABLE` SQL generation. Tested.
- Architecture rules held: no LLM in hot path, medallion layers not skipped, provenance preserved, provider-neutral.

### Issues found (ordered by priority)
1. **Multi-agent drift risk is unmitigated by automation.** The de-Clauding (removal of `CLAUDE.md`/`CLAUDE_CODE_CONTEXT.md` in favour of neutral `AGENTS.md`) is deliberate and stays. But with multiple toolchains committing, the only drift protections are conventions in `AGENTS.md` — nothing mechanical enforces test/lint/style parity across agents. CI (item 2) and committing this plan file to the repo are the mitigations; each agent must be pointed at `AGENTS.md` + the plan at session start.
2. **No CI.** No `.github/workflows/`. Tests pass locally but nothing enforces it on push/PR — especially important with multiple agent toolchains committing here.
3. **`config/default.yaml` is not loaded at runtime** (acknowledged in AGENTS.md as a "planning artifact"). Two sources of truth: Pydantic defaults in `src/utils/config.py` vs the YAML. The silver rejection filters are currently duplicated in both.
4. **`datetime.utcnow()`** used in processors — deprecated in Python 3.12. Trivial fix (`datetime.now(timezone.utc)`).
5. **Raw payload stored in full in silver rows** (JSON string + hash). Fine at ZTF scale; will not survive Rubin volumes. The gold-layer design should not copy this pattern.
6. **Still stubs:** `src/agents/` is empty, no gold layer, no cross-matching, no Euclid/lensing/cosmology code anywhere.

---

## 2. Data landscape & theoretical framing

### 2.1 Euclid releases — status and roles (dates verified 2026-07-12)

| Release | Date | Content | Role for AGD |
|---|---|---|---|
| **Q1** | 19 Mar 2025 (out) | 63.1 deg², ~26M detections, three Deep Fields; SLDE strong-lens catalogue (497 candidates, 250 grade A) | **Tooling & schema fluency.** Explicit caveat: Q1 is *not* large enough for meaningful cosmological-parameter derivation — it is a capability demo (morphology, dwarf galaxies, photo-z, lens finding). Build the access scaffold and lens harness on it; do not fit cosmology to it. |
| **Q2** | 24 Jun 2026 (out) | Euclid Galactic Bulge Survey: 4.8 deg² VIS imaging near the Galactic Centre, >60M stars, photometry + astrometry catalogues | **Microlensing / transient tie-in.** Not a cosmology release. But its microlensing science goal overlaps AGD's `SCIENCE_GOALS.md` (microlensing light-curve anomalies), and it is the reference field for Roman's 2027 bulge survey. Optional ingestion target after Q1. |
| **DR1-Foundation** | Nov 2026 (revised — was 21 Oct 2026) | ~1900 deg², raw + calibrated images, catalogues, spectra; ~7000 expected lens candidates | **The cosmology upgrade.** Weak-lensing growth-of-structure at Stage-IV scale. The Q1 harness must swap in cleanly. |
| **Full DR1** | mid-2027 (revised) | Complete DR1 | Long-horizon. |

> Note: the earlier project chat cited DR1 = 21 Oct 2026 and Q2 = 24 Jun 2026 (then upcoming). The June 2026 timeline revision split DR1 into DR1-Foundation (Nov 2026) + full DR1 (mid-2027); Q2 shipped on schedule and is now public.

### 2.2 Euclid access paths (fit to existing workflow)

1. **`astroquery.esa.euclid`** — Python TAP/ADQL against the ESA archive, image/spectra retrieval via DataLink. The clean API analogue to the DESI pull; primary path for AGD. Scaffold in Phase 2.
2. **IRSA (NASA/IPAC) mirror** — TAP/ADQL; Q1 is also on the AWS Open Data Repository, so queries run without downloading the full ~35 TB.
3. **ESA Datalabs** — hosted notebooks against the full volume (Cosmos account, invite code `EUCLIDQ1`). Use for exploration too heavy for local pulls; not a pipeline dependency.

### 2.3 Multi-probe source ranking (for the extra-dimensional / dark-energy question)

For testing whether gravity/dark energy deviates from GR+ΛCDM in ways extra-dimensional models predict, geometric probes + growth of structure constrain the theory. Priority order:

1. **DESI** (in stack) — spectroscopic BAO + RSD. DR2's w0waCDM hint of evolving dark energy is exactly the signal braneworld/modified-gravity models care about. Cleanest API; feeds the existing CPL notebook (`feat/desi-wz-fit`).
2. **CMB — Planck (legacy) + ACT DR6** — the high-z anchor that breaks the H₀–r_d and w₀–w_a degeneracies. Planck 2018 chains as baseline; ACT DR6 tightens lensing and small-scale spectra. S₈ growth tension lives here. Public chains plug into `cobaya`/`emcee`.
3. **Type Ia SNe — Pantheon+ / Union3 / DES-SN5YR** — third leg of the combined-probe fit. DES-SN5YR (2024) is the most recent large sample; public tables, trivial to fold into the DESI fit.
4. **KiDS-1000 + DES Y3 (weak lensing, pre-Euclid)** — the current Stage-III growth-of-structure measurements. Use these for real S₈/γ constraints *today* rather than waiting for Euclid DR1, which then upgrades this axis by an order of magnitude.
5. **Rubin/LSST + ZTF** (in AGD) — not a dark-energy-fit source directly, but the counterpart-discovery engine for the GW standard-siren channel (see 2.4, channel 3) — which is the most direct extra-dimension test available, and the one AGD's existing architecture serves natively. Eventually also the Northern-hemisphere lensing counterpart to Euclid via DESC.
6. **LIGO/Virgo/KAGRA public alerts** (new) — GW triggers via GCN/GraceDB; combined with an EM counterpart from the alert stream, each BNS event is a d_L^GW vs d_L^EM graviton-leakage test. Zero-cost data (public, low volume), high physics leverage.

### 2.4 Honest framing (the project's own convergence rule)

None of these datasets "detect a dimension." Extra-dimensional models are constrained through three falsifiable channels, and the pipeline must keep **agnostic anomaly discovery** decoupled from **hypothesis testing** (biasing the anomaly hunt toward a preferred explanation manufactures confirmations):

1. **Combined-probe parameters (w₀, w_a, γ, S₈)** — Phase 3a. Ensemble statistics; a braneworld/DGP-type model earns or loses credibility by where these land vs GR+ΛCDM. Available now (DESI+CMB+SN+Stage-III lensing).
2. **Lens/growth statistics** — Phase 3b. Direct KK/RS-II corrections to individual lensing observables are suppressed by ~(ℓ/r)² and unmeasurable (lab torsion-balance limits already push RS-II to sub-mm scales; self-accelerating DGP is ruled out). The strong-lens harness is a *statistics* instrument and a DR1-ready asset; its notebook must say so explicitly.
3. **GW standard sirens (graviton leakage)** — Phase 5, and the reason the ZTF/Rubin time-domain pipeline is itself an extra-dimension instrument. If gravitons leak into extra dimensions, GW sources appear dimmer than their EM counterparts (d_L^GW > d_L^EM). GW170817 + kilonova constrained large spacetime dimensions to D ≈ 4.0 ± ~0.1 (Pardo, Fishbach, Holz & Spergel 2018, JCAP). Improving this requires exactly AGD's core competency: rapid optical-counterpart identification in alert streams after GW triggers. This is the only channel where a single well-measured event carries dimensional information.

**Design consequence:** single anomalous light curves are, with overwhelming prior, instrumental → astrophysical → only then gravitational. The anomaly agent flags weirdness agnostically; the constraint notebooks (3a/3b) and the siren channel (5) do the extra-dimensional physics. Do not conflate the two in code or in claims.

---

## 3. Execution plan (branch-per-phase, any agent)

### Phase 0 — Repo convergence & hygiene  `chore/repo-convergence`
*Small, do first, unblocks everything.*

1. **Harden `AGENTS.md` as the sole agent contract** (no provider-specific context files — the de-Clauding stands). Add to it: (a) the multi-agent handoff protocol — read `AGENTS.md` + `AGD_FORWARD_PLAN.md` at session start, one branch/PR per phase, PR description states what changed and what the next agent needs; (b) a "do not add provider-specific files or model assumptions" rule; (c) updated Current Technical Direction as phases land. Commit **this plan file** to the repo root so roadmap state travels with the code, not with any one chat tool.
2. Add **CI**: `.github/workflows/ci.yml` — Python 3.11 + 3.12 matrix, `ruff check`, `black --check`, `pytest -m "not integration"`. CI is the provider-neutral enforcement layer that keeps all agents honest.
3. Resolve the **config duality**: implement YAML loading in `src/utils/config.py` (Pydantic settings source) so `config/default.yaml` is real, or delete the keys that will never load. Pick one; update AGENTS.md.
4. Replace `datetime.utcnow()` → `datetime.now(timezone.utc)`; enable ruff `DTZ` rules to prevent regression.

**Acceptance:** CI green on main; one config source of truth; `AGENTS.md` + committed plan file sufficient for any toolchain to start a phase cold.

### Phase 1 — Gold layer + Gaia/SIMBAD cross-match  `feat/gold-crossref`
*Already the sprint plan; also the prerequisite for everything Euclid.*

1. `src/crossref/gaia_client.py` — astroquery cone search against Gaia DR3, 5″ radius (config-driven), retry/backoff per architecture rule 2. Cache results locally (Parquet) — Gaia TAP is slow and rate-limited.
2. `src/crossref/simbad_client.py` — same pattern.
3. `src/processing/gold_processor.py` — silver → gold: nearest-neighbour matches (separation, Gaia G mag, parallax, proper motion, SIMBAD otype), light-curve features from `prv_candidates`. Carry `raw_payload_hash` + silver processing ID as provenance pointers; do **not** copy raw JSON into gold.
4. Star/extragalactic discriminator: significant Gaia parallax or proper motion ⇒ galactic — the single most valuable feature for downstream lens/transient logic.
5. Tests: mocked TAP responses; one integration test hitting live Gaia with a tiny cone.

**Acceptance:** end-to-end smoke run bronze→silver→gold on live Fink data; cross-match columns populated; tests green.

### Phase 2 — Euclid access scaffold + Q1 ingestion  `feat/euclid-q1`
*New data modality: batch catalogue ingestion via TAP, not streaming alerts. Keep it in the medallion.*

1. `src/ingestion/euclid_client.py` — TAP/ADQL client built on `astroquery.esa.euclid` (fallback: IRSA TAP). Query pattern scaffold (mirrors the Fink access scaffold; verify live table/column names via `tap_schema` before hardcoding):

   ```python
   from astroquery.esa.euclid import Euclid

   # Schema discovery first — do not trust remembered table names
   tables = Euclid.launch_job(
       "SELECT table_name FROM tap_schema.tables "
       "WHERE schema_name = 'catalogue'"
   ).get_results()

   # Q1 MER final catalogue: cone search on a Deep Field (EDF-S shown)
   job = Euclid.launch_job_async("""
       SELECT object_id, right_ascension, declination,
              flux_vis_psf, flux_y_templfit, flux_j_templfit,
              flux_h_templfit, point_like_prob, spurious_prob
       FROM catalogue.mer_catalogue
       WHERE 1 = CONTAINS(
           POINT('ICRS', right_ascension, declination),
           CIRCLE('ICRS', 52.93, -28.09, 0.1))
   """)
   df = job.get_results().to_pandas()
   ```

   Wrap in the standard AGD client pattern: retry/backoff, timeout, structured logging, local Parquet cache keyed on query hash.
2. Ingest two catalogue products, each with full provenance (source URL/query, retrieval date, catalogue version, DR tag — `Q1` now, `DR1F` in November):
   - **MER final catalogue** subsets (schema fluency; the object backbone), via TAP.
   - **SLDE strong-lens catalogue** (497 candidates; arXiv:2503.15324 + SLDE B–E companions), as `src/models/lenses.py` → Pydantic `EuclidLensCandidate` (position, grade, θ_E where present, discovery engine, DR tag).
3. Bronze/silver treatment mirrors alerts: raw rows preserved; silver applies grade filtering and coordinate standardisation.
4. **Lens-field cross-match:** gold-layer job matching Fink/ZTF transients against Euclid lens positions (configurable radius). Any hit is flagged `lens_field_transient` — the time-delay cosmography channel; always escalates in Phase 4.
5. Tests with bundled fixtures (~20 catalogue rows) so CI never depends on ESA availability.
6. *(Optional, post-Q1)* Q2 Galactic Bulge catalogue ingestion — same client, different schema tag. Motivation: microlensing anomaly science overlaps AGD's transient mission and Roman's 2027 bulge campaign.

**Acceptance:** live TAP query returns MER rows into bronze; SLDE catalogue queryable locally; `lens_field_transient` job runs (likely empty at 63 deg² — fine); schema documented for DR1-Foundation swap-in.

### Phase 3 — Constraint & lensing science harness  `feat/constraint-harness`
*The falsifiable version of the extra-dimensional thread. Notebook-first. Two tracks, ordered by constraining power.*

**3a. Combined-probe fit (primary channel).** Extend the DESI w(z) CPL notebook (`feat/desi-wz-fit`) into the full stack, staged:
   1. ΛCDM sanity check (existing plan).
   2. DESI DR2 BAO w₀waCDM fit — best-fit values transcribed from arXiv:2503.14738, not memory (H₀–r_d degeneracy note applies).
   3. + CMB priors (Planck 2018 chains baseline; ACT DR6 where it tightens).
   4. + SN (DES-SN5YR primary; Pantheon+/Union3 as cross-checks).
   5. + growth axis: S₈/γ from KiDS-1000 and DES Y3 — the axis that most directly separates modified gravity from ΛCDM *today*, pre-Euclid-DR1.
   6. Verdict cell: where (w₀, w_a, γ) land vs GR+ΛCDM vs representative braneworld/DGP predictions. Model credibility is earned or lost here — no narrative without a number.

**3b. Strong-lens statistics harness (secondary; DR1-ready asset).** `src/analysis/lensing.py` + `notebooks/euclid_lens_statistics.ipynb`:
   - SIS/SIE: θ_E ↔ velocity dispersion ↔ projected mass within θ_E. Pure functions, unit-tested against published values.
   - Q1 SLDE sample statistics (θ_E and redshift distributions) vs ΛCDM strong-lens abundance forecasts.
   - **Sensitivity floor:** what fractional deviation is detectable at N≈500 (Q1) vs N≈7000 (DR1-Foundation)? Conclusions cell states explicitly that braneworld-scale effects sit below the Q1 floor.
   - Analysis depends on gold; pipeline never imports analysis.

**Acceptance:** both notebooks run top-to-bottom from local data; every conclusion traces to a computed number; the 3a verdict cell and 3b sensitivity-floor figure exist and are re-runnable against DR1-Foundation.

### Phase 4 — Anomaly agent, lens-aware  `feat/anomaly-agent`
*Existing roadmap item, now with the lensing hook. Provider-neutral per AGENTS.md.*

1. `src/agents/anomaly_agent.py` — warm path only. Inputs: gold row + cross-match context + `lens_field_transient` flag. Output: structured assessment (anomaly score, rationale, recommended action) with full provenance.
2. Escalation rule: `lens_field_transient` hits always escalate to human review regardless of ML score.
3. Nightly CLI report (`scripts/nightly_report.py`): counts by class, new lens-field matches, top anomalies.

**Acceptance:** agent runs on a real nightly batch; report generated; zero LLM calls in bronze/silver/gold path.

### Phase 5 — Multi-messenger GW counterpart channel  `feat/gw-counterparts`
*The channel where the time-domain pipeline itself does extra-dimensional physics. Builds directly on Phases 1 and 4.*

1. `src/ingestion/gw_alert_client.py` — consume LIGO/Virgo/KAGRA public alerts (GCN Kafka / GraceDB API): event ID, skymap (HEALPix), distance posterior, source classification (BNS/NSBH probability). Same client pattern: retry, timeout, provenance, local cache.
2. Cross-match job: on a GW trigger with non-trivial BNS probability, filter incoming Fink/ZTF alerts against the skymap credible region + distance-consistent host constraints; Fink's own `Kilonova candidate` tag is a first-class input. Flag `gw_counterpart_candidate` in gold.
3. Escalation: `gw_counterpart_candidate` outranks everything — counterpart science is time-critical (hours). Nightly report gets a GW section.
4. `notebooks/gw_siren_dimensions.ipynb` — the physics: reproduce the GW170817 D = 4 constraint from published d_L^GW and EM host distance (validation cell), then a forecast cell: how the constraint on graviton leakage / number of large dimensions scales with N well-localised BNS events with counterparts in the Rubin era. Staged like 3a/3b: reproduce standard result first, quantify sensitivity, only then discuss braneworld parameter space.

**Acceptance:** GW alert client tested against archived GraceDB events; cross-match runs end-to-end on a replayed historical trigger (GW170817-era ZTF data or simulated stream); notebook reproduces the published D ≈ 4.0 ± 0.1 constraint before any forecasting.

### November 2026 checkpoint — DR1-Foundation
When DR1-Foundation drops (~1900 deg²): re-run Phase 2 ingestion with `DR tag = DR1F`; re-run notebook 3b (the sensitivity floor tells you immediately which questions just became answerable); fold Euclid weak-lensing growth constraints into notebook 3a when consortium likelihoods/chains publish. This is the order-of-magnitude upgrade to the lensing axis.

---

## 4. Kickoff prompt (works for any agent toolchain)

> Read AGENTS.md, then AGD_FORWARD_PLAN.md. Execute Phase 0 (`chore/repo-convergence`): create the branch, implement all four items, run ruff + black + pytest, open a PR whose description states what changed and what the next agent needs to know. Do not touch silver/bronze logic in this phase. Do not add provider-specific context files or assumptions.

Then proceed phase by phase, one branch and PR each — regardless of which toolchain (Claude/Fable, Codex/GPT 5.6 Sol, or other) picks up the phase.

---

## Sources
- Euclid Q1 SLDE-A lens catalogue: https://arxiv.org/abs/2503.15324 ; A&A Q1 special issue (SLDE B–E, clusters, double-source-plane)
- Euclid Q1 overview: https://www.euclid-ec.org/science/q1/
- Euclid Q2 (Galactic Bulge Survey, 24 Jun 2026): https://www.euclid-ec.org/science/q2/ ; https://www.cosmos.esa.int/web/euclid/q2-data-release
- DR1 revised timeline (DR1-Foundation Nov 2026, full DR1 mid-2027): https://www.cosmos.esa.int/web/euclid/euclid-dr1 ; https://telescoper.blog/2026/06/16/euclid-update-revised-timeline/
- DESI DR2 BAO: https://arxiv.org/abs/2503.14738
- GW dimensional constraint (D = 4 from GW170817): Pardo, Fishbach, Holz & Spergel 2018, JCAP — https://arxiv.org/abs/1801.08160
- GW public alerts: https://gracedb.ligo.org and GCN Kafka (https://gcn.nasa.gov)
