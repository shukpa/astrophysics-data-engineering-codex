"""Gold layer processor: catalog enrichment and derived features.

The gold layer turns silver alerts into analysis-ready records by attaching
Gaia DR3 and SIMBAD nearest-neighbour cross-matches, a star/extragalactic
discriminator, and light-curve features derived from the alert history.

It stays in the hot path and does not use LLM calls. Catalog outages degrade
gracefully: a failed cross-match yields null match columns, never a failed
batch. Provenance travels as pointers (processing IDs + raw payload hash);
raw payload JSON is intentionally not copied into gold.
"""

from __future__ import annotations

import json
import math
import statistics
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import structlog

from src.crossref.gaia_client import GaiaClient
from src.crossref.simbad_client import SimbadClient
from src.exceptions import CrossReferenceError, GoldProcessingError, WriteError
from src.models.alerts import GoldAlert, GoldBatch, SilverAlert, SilverBatch
from src.models.crossref import GaiaMatch, SimbadMatch
from src.utils.config import CrossmatchSettings, Settings, StorageSettings, get_settings

logger = structlog.get_logger(__name__)


class GoldProcessor:
    """Processes silver alerts into the gold layer.

    Args:
        settings: Full application settings (defaults to get_settings()).
        storage_settings: Storage override, mainly for tests.
        crossmatch_settings: Cross-match override, mainly for tests.
        gaia_client: Injected Gaia client (a default is built lazily).
        simbad_client: Injected SIMBAD client (a default is built lazily).
        enable_crossmatch: When False, skip catalog queries entirely and
            emit null match columns (offline mode).
    """

    def __init__(
        self,
        settings: Settings | None = None,
        storage_settings: StorageSettings | None = None,
        crossmatch_settings: CrossmatchSettings | None = None,
        gaia_client: GaiaClient | None = None,
        simbad_client: SimbadClient | None = None,
        enable_crossmatch: bool = True,
    ) -> None:
        self._settings = settings or get_settings()
        self._storage = storage_settings or self._settings.storage
        self._crossmatch = crossmatch_settings or self._settings.crossmatch
        self._enable_crossmatch = enable_crossmatch
        self._gaia = gaia_client
        self._simbad = simbad_client
        self._log = logger.bind(component="gold_processor")

    @property
    def output_path(self) -> Path:
        """Get the configured gold layer output path."""
        return self._storage.gold_full_path

    def process_batch(
        self,
        batch: SilverBatch,
        batch_id: str | None = None,
    ) -> GoldBatch:
        """Process a silver alert batch into a gold alert batch."""
        batch_id = batch_id or self._generate_batch_id()
        self._log.info(
            "gold_processing_started",
            batch_id=batch_id,
            source_batch_id=batch.batch_id,
            alert_count=batch.count,
            crossmatch_enabled=self._enable_crossmatch,
        )

        gold_alerts: list[GoldAlert] = []
        matched_gaia = 0
        matched_simbad = 0
        crossmatch_failed = 0

        for silver_alert in batch.alerts:
            gaia_match, simbad_match, failed = self._crossmatch_position(silver_alert)
            if failed:
                crossmatch_failed += 1
            if gaia_match is not None:
                matched_gaia += 1
            if simbad_match is not None:
                matched_simbad += 1

            try:
                gold_alerts.append(
                    self._to_gold_alert(
                        silver_alert=silver_alert,
                        gold_processing_id=batch_id,
                        gaia_match=gaia_match,
                        simbad_match=simbad_match,
                    )
                )
            except Exception as exc:
                raise GoldProcessingError(
                    f"Failed to build gold alert for {silver_alert.object_id}: {exc}",
                    details={"object_id": silver_alert.object_id, "error": str(exc)},
                ) from exc

        self._log.info(
            "gold_processing_completed",
            batch_id=batch_id,
            successful=len(gold_alerts),
            matched_gaia=matched_gaia,
            matched_simbad=matched_simbad,
            crossmatch_failed=crossmatch_failed,
        )

        return GoldBatch(
            alerts=gold_alerts,
            batch_id=batch_id,
            source_batch_id=batch.batch_id,
            source_count=batch.count,
            matched_gaia_count=matched_gaia,
            matched_simbad_count=matched_simbad,
            crossmatch_failed_count=crossmatch_failed,
        )

    def write_batch(
        self,
        batch: GoldBatch,
        partition_by_date: bool = True,
    ) -> Path:
        """Write a gold batch to storage."""
        if batch.count == 0:
            self._log.warning("write_gold_batch_empty", batch_id=batch.batch_id)
            return self.output_path

        try:
            self.output_path.mkdir(parents=True, exist_ok=True)
            df = pd.DataFrame([alert.to_flat_dict() for alert in batch.alerts])

            if self._storage.file_format == "json":
                output_file = self._write_json(df, batch.batch_id)
            else:
                output_file = self._write_parquet(df, batch.batch_id, partition_by_date)

            self._log.info(
                "write_gold_batch_completed",
                batch_id=batch.batch_id,
                output_file=str(output_file),
                records_written=batch.count,
            )
            return output_file
        except Exception as exc:
            raise WriteError(
                f"Failed to write gold batch {batch.batch_id}: {exc}",
                details={"batch_id": batch.batch_id, "error": str(exc)},
            ) from exc

    def read_gold_data(
        self,
        observation_date: str | None = None,
        limit: int | None = None,
    ) -> pd.DataFrame:
        """Read gold layer data back from storage."""
        if not self.output_path.exists():
            self._log.warning("gold_path_not_found", path=str(self.output_path))
            return pd.DataFrame()

        try:
            if self._storage.file_format == "json":
                json_files = list(self.output_path.glob("*.json"))
                if not json_files:
                    return pd.DataFrame()
                df = pd.concat([pd.read_json(path) for path in json_files], ignore_index=True)
                if observation_date and "observation_date" in df.columns:
                    df = df[df["observation_date"] == observation_date]
            else:
                filters = None
                if observation_date:
                    filters = [("observation_date", "=", observation_date)]
                df = pd.read_parquet(self.output_path, filters=filters, engine="pyarrow")

            if limit:
                df = df.head(limit)
            return df
        except Exception as exc:
            raise GoldProcessingError(
                f"Failed to read gold data: {exc}",
                details={"path": str(self.output_path), "error": str(exc)},
            ) from exc

    def get_statistics(self) -> dict[str, Any]:
        """Get summary statistics about the gold layer."""
        df = self.read_gold_data()
        if df.empty:
            return {
                "total_records": 0,
                "unique_objects": 0,
                "gaia_matched": 0,
                "simbad_matched": 0,
                "likely_stellar": 0,
            }

        stats: dict[str, Any] = {
            "total_records": len(df),
            "unique_objects": df["object_id"].nunique() if "object_id" in df.columns else 0,
        }
        if "gaia_source_id" in df.columns:
            stats["gaia_matched"] = int(df["gaia_source_id"].notna().sum())
        if "simbad_main_id" in df.columns:
            stats["simbad_matched"] = int(df["simbad_main_id"].notna().sum())
        if "is_likely_stellar" in df.columns:
            stats["likely_stellar"] = int((df["is_likely_stellar"] == True).sum())  # noqa: E712
        return stats

    # ------------------------------------------------------------------
    # Cross-matching
    # ------------------------------------------------------------------

    def _crossmatch_position(
        self,
        alert: SilverAlert,
    ) -> tuple[GaiaMatch | None, SimbadMatch | None, bool]:
        """Cross-match one position against Gaia and SIMBAD.

        Returns (gaia_match, simbad_match, any_query_failed). Catalog
        errors are logged and swallowed — enrichment must not sink the
        batch (architecture rule: graceful degradation off the hot path).
        """
        if not self._enable_crossmatch:
            return None, None, False

        failed = False

        gaia_match: GaiaMatch | None = None
        try:
            gaia_match = self._gaia_client().nearest(ra=alert.ra, dec=alert.dec)
        except CrossReferenceError as exc:
            failed = True
            self._log.warning(
                "gaia_crossmatch_failed",
                object_id=alert.object_id,
                error=str(exc),
            )

        simbad_match: SimbadMatch | None = None
        try:
            simbad_match = self._simbad_client().nearest(ra=alert.ra, dec=alert.dec)
        except CrossReferenceError as exc:
            failed = True
            self._log.warning(
                "simbad_crossmatch_failed",
                object_id=alert.object_id,
                error=str(exc),
            )

        return gaia_match, simbad_match, failed

    def _gaia_client(self) -> GaiaClient:
        if self._gaia is None:
            self._gaia = GaiaClient(crossmatch_settings=self._crossmatch)
        return self._gaia

    def _simbad_client(self) -> SimbadClient:
        if self._simbad is None:
            self._simbad = SimbadClient(crossmatch_settings=self._crossmatch)
        return self._simbad

    # ------------------------------------------------------------------
    # Discriminator + features
    # ------------------------------------------------------------------

    def _discriminate(self, gaia_match: GaiaMatch | None) -> tuple[bool | None, str | None]:
        """Star/extragalactic discriminator from Gaia astrometry.

        A significant positive parallax or a significant total proper
        motion marks the counterpart as stellar (galactic). Returns
        (None, None) when there is no Gaia match to judge.
        """
        if gaia_match is None:
            return None, None

        evidence: list[str] = []

        parallax_snr = gaia_match.parallax_snr
        if (
            parallax_snr is not None
            and gaia_match.parallax is not None
            and gaia_match.parallax > 0
            and parallax_snr >= self._crossmatch.parallax_snr_threshold
        ):
            evidence.append("parallax")

        pm_snr = gaia_match.pm_snr
        if pm_snr is not None and pm_snr >= self._crossmatch.pm_snr_threshold:
            evidence.append("proper_motion")

        if evidence:
            return True, "+".join(evidence)
        return False, None

    def _light_curve_features(self, alert: SilverAlert) -> dict[str, Any]:
        """Derive light-curve features from the alert history.

        Uses the current epoch plus any ``prv_candidates`` preserved in the
        silver raw payload. Only epochs with a finite magnitude count as
        detections. ``lc_mag_rate_per_day`` is the magnitude change per day
        between the two most recent detections (negative = brightening).
        """
        epochs: list[tuple[float, float]] = [(alert.jd, alert.magpsf)]

        for prv in self._extract_prv_candidates(alert):
            jd = prv.get("jd")
            mag = prv.get("magpsf")
            if jd is None or mag is None:
                continue
            try:
                jd_f = float(jd)
                mag_f = float(mag)
            except (TypeError, ValueError):
                continue
            if math.isfinite(jd_f) and math.isfinite(mag_f):
                epochs.append((jd_f, mag_f))

        epochs.sort(key=lambda pair: pair[0])
        mags = [mag for _, mag in epochs]
        jds = [jd for jd, _ in epochs]

        features: dict[str, Any] = {
            "lc_n_detections": len(epochs),
            "lc_time_span_days": jds[-1] - jds[0] if len(epochs) > 1 else 0.0,
            "lc_mag_brightest": min(mags),
            "lc_mag_faintest": max(mags),
            "lc_mag_mean": statistics.fmean(mags),
            "lc_mag_std": statistics.pstdev(mags) if len(mags) > 1 else 0.0,
            "lc_amplitude": max(mags) - min(mags),
            "lc_mag_rate_per_day": None,
        }

        if len(epochs) > 1:
            (jd_prev, mag_prev), (jd_last, mag_last) = epochs[-2], epochs[-1]
            dt = jd_last - jd_prev
            if dt > 0:
                features["lc_mag_rate_per_day"] = (mag_last - mag_prev) / dt

        return features

    def _extract_prv_candidates(self, alert: SilverAlert) -> list[dict[str, Any]]:
        """Recover prv_candidates from the silver raw payload, if present."""
        if not alert.raw_payload_json:
            return []
        try:
            payload = json.loads(alert.raw_payload_json)
        except (json.JSONDecodeError, TypeError):
            self._log.warning("raw_payload_parse_failed", object_id=alert.object_id)
            return []
        prv = payload.get("prv_candidates")
        if not isinstance(prv, list):
            return []
        return [entry for entry in prv if isinstance(entry, dict)]

    # ------------------------------------------------------------------
    # Record assembly
    # ------------------------------------------------------------------

    def _to_gold_alert(
        self,
        silver_alert: SilverAlert,
        gold_processing_id: str,
        gaia_match: GaiaMatch | None,
        simbad_match: SimbadMatch | None,
    ) -> GoldAlert:
        is_likely_stellar, stellar_evidence = self._discriminate(gaia_match)
        features = self._light_curve_features(silver_alert)

        return GoldAlert(
            object_id=silver_alert.object_id,
            candidate_id=silver_alert.candidate_id,
            ra=silver_alert.ra,
            dec=silver_alert.dec,
            magpsf=silver_alert.magpsf,
            sigmapsf=silver_alert.sigmapsf,
            filter_id=silver_alert.filter_id,
            filter_name=silver_alert.filter_name,
            jd=silver_alert.jd,
            mjd=silver_alert.mjd,
            observation_date=silver_alert.observation_date,
            fink_class=silver_alert.fink_class,
            cds_xmatch=silver_alert.cds_xmatch,
            rb_score=silver_alert.rb_score,
            drb_score=silver_alert.drb_score,
            gaia_source_id=gaia_match.source_id if gaia_match else None,
            gaia_separation_arcsec=gaia_match.separation_arcsec if gaia_match else None,
            gaia_g_mag=gaia_match.g_mag if gaia_match else None,
            gaia_parallax=gaia_match.parallax if gaia_match else None,
            gaia_parallax_error=gaia_match.parallax_error if gaia_match else None,
            gaia_parallax_snr=gaia_match.parallax_snr if gaia_match else None,
            gaia_pmra=gaia_match.pmra if gaia_match else None,
            gaia_pmdec=gaia_match.pmdec if gaia_match else None,
            gaia_pm_total=gaia_match.pm_total if gaia_match else None,
            gaia_pm_snr=gaia_match.pm_snr if gaia_match else None,
            simbad_main_id=simbad_match.main_id if simbad_match else None,
            simbad_otype=simbad_match.otype if simbad_match else None,
            simbad_separation_arcsec=simbad_match.separation_arcsec if simbad_match else None,
            is_likely_stellar=is_likely_stellar,
            stellar_evidence=stellar_evidence,
            source=silver_alert.source,
            source_version=silver_alert.source_version,
            bronze_processing_id=silver_alert.bronze_processing_id,
            silver_processing_id=silver_alert.silver_processing_id,
            gold_processing_id=gold_processing_id,
            source_object_id=silver_alert.source_object_id,
            source_candidate_id=silver_alert.source_candidate_id,
            ingestion_timestamp=silver_alert.ingestion_timestamp,
            silver_timestamp=silver_alert.silver_timestamp,
            raw_payload_hash=silver_alert.raw_payload_hash,
            **features,
        )

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def _write_parquet(
        self,
        df: pd.DataFrame,
        batch_id: str,
        partition_by_date: bool,
    ) -> Path:
        if partition_by_date and "observation_date" in df.columns:
            table = pa.Table.from_pandas(df)
            pq.write_to_dataset(
                table,
                root_path=str(self.output_path),
                partition_cols=["observation_date"],
                existing_data_behavior="overwrite_or_ignore",
            )
            return self.output_path

        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        output_file = self.output_path / f"gold_alerts_{batch_id}_{timestamp}.parquet"
        df.to_parquet(output_file, index=False, engine="pyarrow")
        return output_file

    def _write_json(self, df: pd.DataFrame, batch_id: str) -> Path:
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        output_file = self.output_path / f"gold_alerts_{batch_id}_{timestamp}.json"
        df.to_json(output_file, orient="records", indent=2)
        return output_file

    def _generate_batch_id(self) -> str:
        return f"gold_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"


def create_gold_processor(
    settings: Settings | None = None,
) -> GoldProcessor:
    """Factory function to create a configured GoldProcessor."""
    return GoldProcessor(settings=settings)
