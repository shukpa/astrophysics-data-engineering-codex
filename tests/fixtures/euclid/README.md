# Euclid Q1 test fixtures

Small, deterministic, **representative** samples used by unit tests and
offline smoke runs so CI never depends on ESA archive availability.

- `slde_q1_sample.json` — 20 lens candidates shaped like the SLDE Q1
  catalogue rows (grades A/B/C, scores, optional Einstein radii), with
  positions scattered over the three Q1 Deep Fields. **Synthetic sample,
  not the published catalogue** — point the ingest script at the real
  SLDE table (arXiv:2503.15324 + companions) for science use.
- `mer_q1_sample.json` — 20 rows with the nine MER final-catalogue
  columns AGD ingests (verified against the live ESA `tap_schema`,
  2026-07-12).
