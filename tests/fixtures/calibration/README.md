# ZTF BTS replay manifest

`ztf_bts_replay_manifest.json` contains a small set of ZTF object identifiers,
TNS identifiers, and spectroscopic classifications visible in the public ZTF
Bright Transient Survey Sample Explorer. It intentionally contains no copied
alert photometry: the replay script fetches the corresponding Fink/ZTF alert
history at run time.

`truth_is_rare` is a routing-review label for uncommon BTS classes such as TDE,
SLSN-II, and LBV. It is not ground truth for instrumental anomalies, and it is
not evidence of new physics. Results should be reported separately for the
pre/post temporal split and treated as calibration diagnostics only.

Replay runs default to 100 total alerts and enforce a hard cap of 1,000. Fink
object-history rows are passed through the medallion together so Gold can build
per-filter features from earlier detections without using future observations.
If a long-lived object crosses the temporal split, the replay retains only its
post-split predictions and reports the excluded rows, keeping evaluation
cohorts object-disjoint while preserving legitimate pre-split photometry.

Sources:

- https://sites.astro.caltech.edu/ztf/bts/explorer.php
- https://arxiv.org/abs/2009.01242
- https://doc.ztf.fink-broker.org/en/latest/broker/classification/
