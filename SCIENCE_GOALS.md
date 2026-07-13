# Science Goals & Methodology

## Mission Statement

Agentic Galactic Discovery (AGD) automates the detection and characterization of astronomical transients, with particular emphasis on identifying events that are anomalous — events that don't fit existing classification schemes and may signal genuinely new physical phenomena.

Alongside this discovery mission, AGD maintains a **constraint-science mission**: using ensemble statistics and multi-messenger events to test whether gravity and the dark sector behave as GR+ΛCDM predicts — including whether deviations of the kind predicted by extra-dimensional (braneworld-type) models are present or excluded. The execution roadmap for both missions lives in `AGD_FORWARD_PLAN.md`; this document defines the science and its rules of inference.

## Two Decoupled Modes of Inquiry

This is the project's central methodological commitment:

1. **Agnostic anomaly discovery.** The pipeline flags events that deviate from expectation *without* preference for any explanation. Anomaly hunting biased toward a favoured hypothesis manufactures confirmations; the discovery pipeline must never encode a preferred theory.
2. **Hypothesis-driven constraint science.** Specific theoretical models (evolving dark energy, modified gravity, braneworld scenarios) are tested against *ensemble* statistics and *precision measurements* in dedicated analysis notebooks — separate from, and downstream of, the discovery pipeline.

The rationale: a single anomalous light curve is, with overwhelming prior probability, instrumental, then astrophysical, and only remotely gravitational in origin. Single events discover new *objects*; new *gravity* shows up as statistical deviations in ensembles — with one important exception (gravitational-wave standard sirens, below) where a single well-measured multi-messenger event carries genuine dimensional information.

Code consequence: discovery components (`src/processing/`, `src/agents/`) never import or depend on constraint analyses (`src/analysis/`, notebooks). Claims are kept separate too.

## Scientific Context

### The Transient Sky

The night sky is not static. Stars explode, neutron stars merge, black holes consume matter, and phenomena we haven't yet categorized occur every night. Survey telescopes like ZTF and Rubin/LSST scan the sky systematically, generating an **alert** for every detected change. The challenge is volume: ZTF produces ~1 million alerts per night; Rubin/LSST ~10 million. Finding the scientifically valuable needles requires automated triage good enough to not discard the unexpected.

### Why Anomalies Matter

Physics advances through two mechanisms:

1. **Confirmation**: Observations matching theoretical predictions validate and refine models — a Type Ia supernova matching its light-curve template strengthens its use as a standard candle.
2. **Surprise**: Observations that *don't* match force revision. Accelerating cosmic expansion (1998) came from Type Ia supernovae dimmer than expected; pulsars were discovered because Jocelyn Bell noticed a "scruff" that fit no known source type.

This project is designed to be excellent at both — the anomaly capability is what makes it distinctive; the constraint capability is what makes anomalies interpretable.

## The Data Landscape

Each data source has a defined role. Roles are not interchangeable.

| Source | Modality | Role in AGD |
|---|---|---|
| **ZTF / Fink** (live) | Streaming alerts | Time-domain backbone: transient detection, classification, anomaly flagging. Testbed for Rubin scale. |
| **Rubin/LSST** (alerts began 2026) | Streaming alerts, 10× ZTF | Same role at survey depth; also the counterpart-discovery engine for the GW siren channel. |
| **Gaia DR3 / SIMBAD** | Static astrometric/object catalogs | Cross-match backbone: star–extragalactic discrimination (parallax, proper motion), host association. |
| **Euclid Q1** (Mar 2025) | Deep imaging catalogs, 63.1 deg² | Tooling and schema fluency; strong-lens catalogue (~500 candidates) for the lens-statistics harness. **Explicitly not sufficient for cosmological-parameter fits** — it is a capability demo. |
| **Euclid Q2** (Jun 2026) | Galactic Bulge Survey, 4.8 deg² | Microlensing science overlap; Roman 2027 precursor field. Optional ingestion. |
| **Euclid DR1-Foundation** (Nov 2026) / full DR1 (mid-2027) | ~1900 deg² imaging + spectra | The Stage-IV lensing/growth upgrade; ~7000 expected lens candidates. Q1 harnesses must swap in cleanly. |
| **DESI (BAO + RSD)** | Spectroscopic survey releases | Geometric probe: w(z) fits (CPL parametrisation); DR2's evolving-dark-energy hint is the live question. |
| **CMB — Planck legacy, ACT DR6** | Public chains/likelihoods | High-z anchor breaking H₀–r_d and w₀–w_a degeneracies; S₈ tension. |
| **SNe Ia — DES-SN5YR, Pantheon+, Union3** | Public distance tables | Third leg of the combined-probe fit. |
| **KiDS-1000 / DES Y3 weak lensing** | Stage-III lensing results | Growth-of-structure (S₈, γ) constraints available *today*, pre-Euclid-DR1. |
| **LIGO/Virgo/KAGRA public alerts** | GW triggers (GCN/GraceDB) | Standard-siren channel: each BNS with an EM counterpart is a d_L^GW vs d_L^EM test of graviton leakage. |

## Target Science Cases

### Tier 1: Automated Classification (Validation Mode)

Efficiently classify known transient types to free human attention:

- **Type Ia Supernovae**: cosmological distance measurements; early detection enables spectroscopic follow-up while young.
- **Core-Collapse Supernovae** (II, Ib, Ic): massive stellar evolution; subtypes reveal progenitors.
- **Kilonovae**: electromagnetic counterparts to neutron-star mergers — rare, and the linchpin of the standard-siren channel (Tier 3).
- **AGN**: supermassive black hole accretion; flares and state changes probe extreme physics.
- **Variable Stars**: eclipsing binaries, Cepheids, RR Lyrae.
- **Solar System Objects**: asteroids, comets, NEOs.

### Tier 2: Anomaly Detection (Discovery Mode — agnostic by design)

Flag events that resist classification or exhibit unexpected properties:

- **Unusual Light Curves**: brightness evolution matching no standard template — new explosion mechanisms, exotic end states, or foreground lensing effects.
- **Spatial Anomalies**: events in unexpected locations (hostless supernova-like transients).
- **Multi-Band Anomalies**: colors matching no known source class.
- **Temporal Anomalies**: rise/fade timescales inconsistent with known mechanisms.
- **Cross-Reference Mismatches**: host properties inconsistent with apparent transient type.
- **Lens-Field Transients**: any transient coincident with a known strong-lens system (Euclid SLDE catalogue) — automatic escalation; a lensed transient is a time-delay cosmography candidate.

No Tier 2 flag carries theoretical interpretation. Interpretation happens in Tier 3 or in human review.

### Tier 3: Constraint Science (Hypothesis-Testing Mode)

Extra-dimensional and modified-gravity models are **not** tested by looking for weird individual events. They are tested through three falsifiable channels, each with a defined observable and a defined standard-model expectation:

1. **Combined-probe cosmological parameters** — (w₀, w_a), growth index γ, S₈ from DESI BAO + CMB + SNe + Stage-III weak lensing. A braneworld/DGP-type model earns or loses credibility by whether these parameters land where it predicts versus where GR+ΛCDM predicts. This is the primary channel, available now.
2. **Strong-lens and growth statistics** — Einstein-radius distributions, lens abundances, and (at DR1 scale) substructure statistics from Euclid, compared against ΛCDM forecasts. Direct Kaluza–Klein/RS-II corrections to individual lensing observables are suppressed to unmeasurability at galactic scales (laboratory torsion-balance limits already confine RS-II to sub-millimetre scales; the self-accelerating DGP branch is excluded). This channel constrains dark-matter *microphysics via structure*, where extra-dimensional scenarios can differ from CDM. Every analysis must publish its **sensitivity floor**: the smallest deviation detectable at current sample size.
3. **Gravitational-wave standard sirens** — if gravitons leak into large extra dimensions, GW sources appear systematically dimmer than their electromagnetic counterparts (d_L^GW > d_L^EM). GW170817 plus its kilonova constrained the number of large spacetime dimensions to D = 4.0 ± ~0.1 (Pardo, Fishbach, Holz & Spergel 2018, JCAP). Improving this constraint requires rapid optical-counterpart identification in alert streams following GW triggers — AGD's native competency. This is the one channel where a single well-measured event carries dimensional information, and the flagship link between the discovery pipeline and the constraint mission.

Retained theory-motivated searches, subordinate to the same rules:

- **Microlensing anomalies**: light-curve deviations from point-source models — planetary systems, primordial black holes, exotic compact objects (Euclid Q2 bulge field and Roman-era synergy).
- **Dark matter substructure signatures**: correlations in transient rates/properties attributable to substructure — ensemble analyses only.

## Methodology

### Statistical Rigor

Every anomaly flag must include:

1. **Baseline comparison**: expected behavior for the most likely source class
2. **Deviation quantification**: in sigma
3. **False alarm probability**: given the number of alerts processed
4. **Known-systematic exclusion**: detector artifacts, weather, satellite trails, instrumental effects

### Constraint-Analysis Rigor (staged notebooks)

Every constraint analysis proceeds in mandatory stages:

1. **Reproduce the standard result first.** Before testing any alternative, the notebook must recover the published GR+ΛCDM (or published measurement) baseline from primary data. Best-fit values are transcribed from primary sources, never from memory.
2. **Quantify the sensitivity floor.** State what fractional deviation the current sample could detect. If the theory's predicted deviation sits below the floor, the notebook says so explicitly.
3. **Only then compare theory space.** Model credibility is decided by where measured parameters land relative to predictions — no narrative without a number. Null results are results.

### Classification Confidence Framework

Each classified event receives: primary class; confidence score (0.0–1.0); alternative classes with scores; anomaly score (how well the best classification actually fits); follow-up priority (LOW / MEDIUM / HIGH / CRITICAL). GW-counterpart candidates and lens-field transients escalate to CRITICAL regardless of ML score — both are time-critical science.

### Validation Strategy

Before claiming any discovery:

1. **Internal validation**: cross-check against multiple catalogs and detection algorithms
2. **Literature check**: previously reported?
3. **Artifact rejection**: instrumental explanations excluded?
4. **Independent confirmation**: persists across nights/filters?
5. **Human review**: all CRITICAL-priority events require human astronomer assessment

## Metrics

### System Performance
- Alert processing latency (receipt → classification)
- Classification accuracy on known-type test sets
- False positive rate for anomaly flags
- Catalog cross-match completeness
- GW trigger → counterpart-candidate list latency

### Scientific Output
- Events correctly classified per night
- Genuine anomalies identified vs. false alarms
- Time-to-classification for time-critical events (early SNe, kilonova candidates)
- Correlation between anomaly scores and human-verified interest

### Constraint Output
- Reproduction of published baselines (pass/fail per notebook)
- Sensitivity floors published per analysis and updated per data release
- Parameter constraints ((w₀, w_a), γ, D) with provenance to primary data

## Relationship to the Forward Plan

`AGD_FORWARD_PLAN.md` (repo root) is the execution roadmap: phases, branches, acceptance criteria, and data-release checkpoints (notably Euclid DR1-Foundation, Nov 2026). This document is the standing definition of what the project is scientifically for and the inference rules any contributor — human or AI agent, any toolchain — must follow. If the two documents conflict, this one governs the science; the plan governs the sequencing.
