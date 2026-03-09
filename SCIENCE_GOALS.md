# Science Goals & Methodology

## Mission Statement

Agentic Galactic Discovery aims to automate the detection and characterization of astronomical transients, with particular emphasis on identifying events that are anomalous — events that don't fit neatly into existing classification schemes and may signal genuinely new physical phenomena.

## Scientific Context

### The Transient Sky

The night sky is not static. Stars explode, neutron stars merge, black holes consume matter, asteroids tumble past, and phenomena we haven't yet categorized occur every night. Modern survey telescopes like ZTF and the upcoming Rubin/LSST scan the sky systematically, detecting changes by comparing new images against reference images. Any detected change generates an **alert**.

The challenge is volume: ZTF produces ~1 million alerts per night, and Rubin/LSST will produce ~10 million. The vast majority are known types of objects behaving as expected. Finding the scientifically valuable needles in this haystack requires automated triage — and that triage must be good enough to not discard the unexpected.

### Why Anomalies Matter

Physics advances through two mechanisms:

1. **Confirmation**: Observations that match theoretical predictions validate and refine our models. When a detected supernova matches the expected Type Ia light curve template, it strengthens our use of Type Ia as standard candles for cosmology.

2. **Surprise**: Observations that *don't* match predictions force us to revise our models. The discovery of accelerating cosmic expansion (1998 Nobel Prize) came from Type Ia supernovae that were dimmer than expected. Pulsars were discovered because Jocelyn Bell noticed a "scruff" in radio data that didn't fit any known source type.

This project is designed to be excellent at both — but the anomaly detection capability is what makes it distinctive.

## Target Science Cases

### Tier 1: Automated Classification (Validation Mode)

Efficiently classify known transient types to free human attention:

- **Type Ia Supernovae**: Critical for cosmological distance measurements. Early detection enables spectroscopic follow-up while the supernova is young and most scientifically useful.
- **Core-Collapse Supernovae** (Types II, Ib, Ic): Probe massive stellar evolution. Subtypes reveal progenitor properties.
- **Kilonovae**: Electromagnetic counterparts to neutron star mergers. Extremely rare and scientifically valuable for multi-messenger astronomy and understanding r-process nucleosynthesis.
- **Active Galactic Nuclei (AGN)**: Supermassive black hole accretion events. Flares and state changes probe extreme physics.
- **Variable Stars**: Eclipsing binaries, Cepheids, RR Lyrae — each class has distinct astrophysical applications.
- **Solar System Objects**: Asteroids, comets, near-Earth objects. Important for planetary defense.

### Tier 2: Anomaly Detection (Discovery Mode)

Flag events that resist classification or exhibit unexpected properties:

- **Unusual Light Curves**: Transients whose brightness evolution doesn't match any standard template. Could indicate new explosion mechanisms, exotic stellar end states, or foreground effects from intervening dark matter.
- **Spatial Anomalies**: Events in unexpected locations (e.g., a transient far from any cataloged galaxy that looks like a supernova — where did the progenitor star come from?).
- **Multi-Band Anomalies**: Objects whose colors (brightness ratios across different filters) don't match any known source class.
- **Temporal Anomalies**: Events that brighten or fade on timescales inconsistent with known physics (e.g., too fast for nuclear burning, too slow for relativistic processes).
- **Cross-Reference Mismatches**: Events where the host galaxy properties are inconsistent with the apparent transient type.

### Tier 3: Theory-Motivated Searches (Research Mode)

Actively search for specific phenomena predicted by theoretical frameworks:

- **Gravitational Lensing Anomalies**: Microlensing events whose light curves deviate from standard point-source models, potentially indicating planetary systems, primordial black holes, or exotic compact objects.
- **Dark Matter Signatures**: Unexplained correlations in transient rates or properties that could arise from dark matter substructure.
- **Higher-Dimensional Signatures**: Speculative but motivated by extra-dimension theories — events whose energy budgets or timescales might indicate compact extra dimensions (à la Kaluza-Klein or brane-world scenarios).

## Methodology

### Statistical Rigor

Every anomaly flag must include:

1. **Baseline comparison**: What the expected behavior is for the most likely source class
2. **Deviation quantification**: How far the observation deviates, in sigma
3. **False alarm probability**: Given the number of alerts processed, how likely is this deviation by chance?
4. **Known-systematic exclusion**: Is this "anomaly" actually a detector artifact, bad weather, satellite trail, or other instrumental effect?

### Classification Confidence Framework

Each classified event receives:
- **Primary class**: Most likely classification
- **Confidence score**: 0.0 to 1.0
- **Alternative classes**: Other plausible classifications with scores
- **Anomaly score**: How well the best classification actually fits (can be low even for high-confidence classifications)
- **Follow-up priority**: LOW / MEDIUM / HIGH / CRITICAL

### Validation Strategy

Before claiming any discovery:
1. **Internal validation**: Cross-check against multiple catalogs and detection algorithms
2. **Literature check**: Has this object been previously reported?
3. **Artifact rejection**: Can the observation be explained by instrumental effects?
4. **Independent confirmation**: Does the observation persist across multiple nights/filters?
5. **Human review**: All CRITICAL-priority events require human astronomer assessment

## Metrics

### System Performance
- Alert processing latency (time from alert receipt to classification)
- Classification accuracy on known-type test sets
- False positive rate for anomaly flags
- Catalog cross-match completeness

### Scientific Output
- Number of events correctly classified per night
- Number of genuine anomalies identified vs. false alarms
- Time-to-classification for scientifically valuable events (e.g., early supernovae)
- Correlation between anomaly scores and subsequent human-verified interest
