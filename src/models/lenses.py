"""Pydantic models for Euclid strong-lens candidates (SLDE catalogue).

The Q1 Strong Lens Discovery Engine (SLDE) catalogue (arXiv:2503.15324 and
the SLDE B-E companion papers) provides ~497 galaxy-galaxy lens candidates
with expert grades. It is published with the papers rather than exposed via
the ESA TAP service (verified against ``tap_schema`` 2026-07-12), so AGD
ingests it from a local file/URL with full provenance.

Grade convention (SLDE): "A" = confident lens, "B" = probable, "C" = possible.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.models.alerts import _utcnow

#: Recognised SLDE expert grades, best first.
LENS_GRADES = ("A", "B", "C")


class EuclidLensCandidate(BaseModel):
    """A single Euclid strong-lens candidate.

    Attributes:
        name: Candidate designation (e.g. an EUCL Jhhmmss.s±ddmmss name).
        ra: Right ascension in degrees (ICRS).
        dec: Declination in degrees (ICRS).
        grade: Expert grade ("A" confident, "B" probable, "C" possible).
        score: Discovery-engine score in [0, 1], when published.
        theta_e_arcsec: Einstein radius estimate in arcsec, where available.
        discovery_engine: Pipeline/method that surfaced the candidate
            (e.g. "SLDE", "citizen-science", "expert").
        dr_tag: Euclid data-release tag ("Q1" now, "DR1F" after swap-in).
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=3)
    ra: float = Field(..., ge=0, lt=360)
    dec: float = Field(..., ge=-90, le=90)
    grade: str
    score: float | None = Field(None, ge=0, le=1)
    theta_e_arcsec: float | None = Field(None, gt=0, le=60)
    discovery_engine: str = "SLDE"
    dr_tag: str = "Q1"

    @field_validator("grade")
    @classmethod
    def normalise_grade(cls, v: str) -> str:
        """Upper-case the grade and require a recognised value."""
        grade = v.strip().upper()
        if grade not in LENS_GRADES:
            raise ValueError(f"Unknown lens grade {v!r}; expected one of {LENS_GRADES}")
        return grade

    def to_flat_dict(self) -> dict[str, Any]:
        """Convert to a flat dictionary for Parquet-compatible storage."""
        return self.model_dump(mode="json")


class EuclidLensCatalog(BaseModel):
    """A batch of lens candidates plus ingestion provenance.

    Attributes:
        candidates: Validated lens candidates.
        source: Where the catalogue came from (file path or URL).
        source_reference: Literature reference for the catalogue.
        dr_tag: Euclid data-release tag for every row in this batch.
        retrieved_at: When the catalogue was loaded.
        catalog_version: Optional upstream version string.
    """

    model_config = ConfigDict(extra="forbid")

    candidates: list[EuclidLensCandidate]
    source: str
    source_reference: str = "arXiv:2503.15324 (SLDE-A) + companions"
    dr_tag: str = "Q1"
    retrieved_at: datetime = Field(default_factory=_utcnow)
    catalog_version: str | None = None

    @property
    def count(self) -> int:
        """Number of candidates in the catalogue."""
        return len(self.candidates)

    def by_grade(self) -> dict[str, int]:
        """Candidate counts per grade."""
        counts: dict[str, int] = {}
        for candidate in self.candidates:
            counts[candidate.grade] = counts.get(candidate.grade, 0) + 1
        return counts
