"""Constraint & lensing science harness (AGD Phase 3).

This package is the *analysis* layer. It sits strictly downstream of the
medallion pipeline (bronze -> silver -> gold): analysis may read gold
products, but the pipeline must never import ``src.analysis`` (architecture
rule — keep the hot path free of science-notebook dependencies).

Two tracks, ordered by constraining power (AGD_FORWARD_PLAN Phase 3):

* ``cosmology`` + ``constraints`` — the combined-probe fit (3a). CPL dark
  energy, flat w0waCDM distances, growth index, and the published
  DESI/CMB/SN/weak-lensing numbers a braneworld/DGP model is judged against.
* ``lensing`` — the strong-lens statistics harness (3b). SIS/SIE relations
  between Einstein radius, velocity dispersion and projected mass, plus the
  survey sensitivity floor.

Every published number carries its arXiv provenance in :mod:`constraints`;
no narrative without a number.
"""

from __future__ import annotations
