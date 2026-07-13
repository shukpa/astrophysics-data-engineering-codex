"""Bronze/silver processing for the Euclid SLDE strong-lens catalogue.

Mirrors the alert medallion treatment for a batch catalogue:

- **Bronze** preserves the raw catalogue rows exactly as loaded, alongside a
  provenance record (source path/URL, retrieval time, DR tag).
- **Silver** validates rows into :class:`EuclidLensCandidate`, standardises
  coordinates/column names, and applies the configured grade filter.

The SLDE catalogue is published with the discovery papers rather than via
the ESA TAP service (verified against ``tap_schema`` 2026-07-12), so rows
are loaded from a local JSON/CSV file. The bundled test fixture is a small
representative sample; point ``load_lens_rows`` at the full published table
for science use.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import structlog

from src.exceptions import GoldProcessingError, WriteError
from src.models.lenses import EuclidLensCandidate, EuclidLensCatalog
from src.utils.config import EuclidSettings, Settings, StorageSettings, get_settings

logger = structlog.get_logger(__name__)

#: Accepted raw column spellings -> canonical EuclidLensCandidate fields.
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("name", "designation", "object_name", "candidate_name", "id"),
    "ra": ("ra", "right_ascension", "ra_deg"),
    "dec": ("dec", "declination", "dec_deg"),
    "grade": ("grade", "expert_grade", "classification"),
    "score": ("score", "slde_score", "probability"),
    "theta_e_arcsec": ("theta_e_arcsec", "theta_e", "einstein_radius_arcsec"),
    "discovery_engine": ("discovery_engine", "engine", "method"),
}


def load_lens_rows(path: Path) -> list[dict[str, Any]]:
    """Load raw lens-catalogue rows from a JSON or CSV file.

    JSON must be a list of row objects; CSV must have a header row.
    """
    if path.suffix.lower() == ".json":
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise ValueError(f"Expected a JSON list of rows in {path}")
        return rows
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path).to_dict(orient="records")
    raise ValueError(f"Unsupported lens catalogue format: {path.suffix!r} ({path})")


class EuclidLensProcessor:
    """Processes raw SLDE catalogue rows through bronze and silver."""

    def __init__(
        self,
        settings: Settings | None = None,
        storage_settings: StorageSettings | None = None,
        euclid_settings: EuclidSettings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._storage = storage_settings or self._settings.storage
        self._euclid = euclid_settings or self._settings.euclid
        self._log = logger.bind(component="euclid_lens_processor")

    @property
    def bronze_path(self) -> Path:
        """Euclid bronze layer directory."""
        return self._storage.euclid_bronze_full_path

    @property
    def silver_path(self) -> Path:
        """Euclid silver layer directory."""
        return self._storage.euclid_silver_full_path

    # ------------------------------------------------------------------
    # Bronze
    # ------------------------------------------------------------------

    def write_bronze(
        self,
        raw_rows: list[dict[str, Any]],
        source: str,
    ) -> Path:
        """Persist raw catalogue rows + provenance columns to bronze."""
        if not raw_rows:
            self._log.warning("euclid_lens_bronze_empty", source=source)
            return self.bronze_path

        batch_id = self._generate_batch_id("lens_bronze")
        retrieved_at = datetime.now(UTC).isoformat()
        try:
            df = pd.DataFrame(raw_rows)
            # Provenance travels with every raw row.
            df["_ingest_source"] = source
            df["_ingest_dr_tag"] = self._euclid.dr_tag
            df["_ingest_retrieved_at"] = retrieved_at
            df["_ingest_batch_id"] = batch_id

            self.bronze_path.mkdir(parents=True, exist_ok=True)
            output = self.bronze_path / f"slde_lenses_{batch_id}.parquet"
            df.to_parquet(output, index=False)
            self._log.info(
                "euclid_lens_bronze_written",
                rows=len(df),
                output=str(output),
                dr_tag=self._euclid.dr_tag,
            )
            return output
        except Exception as exc:
            raise WriteError(
                f"Failed to write Euclid lens bronze batch: {exc}",
                details={"source": source, "error": str(exc)},
            ) from exc

    # ------------------------------------------------------------------
    # Silver
    # ------------------------------------------------------------------

    def process_catalog(
        self,
        raw_rows: list[dict[str, Any]],
        source: str,
    ) -> tuple[EuclidLensCatalog, dict[str, int]]:
        """Validate + grade-filter raw rows into a silver lens catalogue.

        Returns:
            (catalog, counters) where counters reports input/kept/
            rejected_invalid/rejected_grade.
        """
        allowed = {grade.upper() for grade in self._euclid.lens_allowed_grades}
        candidates: list[EuclidLensCandidate] = []
        rejected_invalid = 0
        rejected_grade = 0

        for raw in raw_rows:
            canonical = self._canonicalise(raw)
            try:
                candidate = EuclidLensCandidate(dr_tag=self._euclid.dr_tag, **canonical)
            except Exception as exc:
                rejected_invalid += 1
                self._log.warning(
                    "euclid_lens_row_invalid",
                    row_name=canonical.get("name"),
                    error=str(exc),
                )
                continue

            if candidate.grade not in allowed:
                rejected_grade += 1
                continue
            candidates.append(candidate)

        counters = {
            "input": len(raw_rows),
            "kept": len(candidates),
            "rejected_invalid": rejected_invalid,
            "rejected_grade": rejected_grade,
        }
        self._log.info("euclid_lens_silver_processed", source=source, **counters)

        catalog = EuclidLensCatalog(
            candidates=candidates,
            source=source,
            dr_tag=self._euclid.dr_tag,
        )
        return catalog, counters

    def write_silver(self, catalog: EuclidLensCatalog) -> Path:
        """Persist a validated lens catalogue to the silver layer."""
        if catalog.count == 0:
            self._log.warning("euclid_lens_silver_empty", source=catalog.source)
            return self.silver_path

        batch_id = self._generate_batch_id("lens_silver")
        try:
            df = pd.DataFrame([c.to_flat_dict() for c in catalog.candidates])
            df["_source"] = catalog.source
            df["_retrieved_at"] = catalog.retrieved_at.isoformat()

            self.silver_path.mkdir(parents=True, exist_ok=True)
            output = self.silver_path / f"slde_lenses_{batch_id}.parquet"
            df.to_parquet(output, index=False)
            self._log.info(
                "euclid_lens_silver_written",
                rows=len(df),
                output=str(output),
            )
            return output
        except Exception as exc:
            raise WriteError(
                f"Failed to write Euclid lens silver batch: {exc}",
                details={"source": catalog.source, "error": str(exc)},
            ) from exc

    def read_silver_lenses(self) -> list[EuclidLensCandidate]:
        """Load all validated lens candidates back from the silver layer."""
        if not self.silver_path.exists():
            return []
        files = sorted(self.silver_path.glob("slde_lenses_*.parquet"))
        if not files:
            return []
        try:
            df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
            fields = set(EuclidLensCandidate.model_fields)
            records = df[[c for c in df.columns if c in fields]].to_dict(orient="records")
            # Parquet round-trips missing optionals (theta_e, score) as NaN;
            # the models expect None.
            cleaned = [
                {
                    key: (None if isinstance(val, float) and val != val else val)
                    for key, val in record.items()
                }
                for record in records
            ]
            return [EuclidLensCandidate(**record) for record in cleaned]
        except Exception as exc:
            raise GoldProcessingError(
                f"Failed to read Euclid silver lenses: {exc}",
                details={"path": str(self.silver_path), "error": str(exc)},
            ) from exc

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _canonicalise(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Map raw column spellings onto EuclidLensCandidate fields."""
        lowered = {str(k).strip().lower(): v for k, v in raw.items()}
        canonical: dict[str, Any] = {}
        for field, aliases in COLUMN_ALIASES.items():
            for alias in aliases:
                if alias in lowered and lowered[alias] is not None:
                    value = lowered[alias]
                    # Treat NaN as missing (CSV loads produce NaN floats).
                    if isinstance(value, float) and value != value:
                        continue
                    canonical[field] = value
                    break
        return canonical

    def _generate_batch_id(self, prefix: str) -> str:
        return f"{prefix}_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
