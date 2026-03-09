"""Pydantic models for ZTF and Fink alert data structures.

These models define the schema for astronomical transient alerts as received
from the Fink broker. They support validation, serialization, and type safety
throughout the processing pipeline.

Key astronomical measures:
- Magnitude: Logarithmic brightness scale (lower = brighter)
- Julian Date (JD): Continuous day count used in astronomy
- RA/Dec: Celestial coordinates in degrees
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FilterID(int, Enum):
    """ZTF filter identifiers.

    ZTF uses three photometric filters:
    - g-band (green): ~400-550nm wavelength
    - r-band (red): ~550-700nm wavelength
    - i-band (infrared): ~700-850nm wavelength
    """

    G_BAND = 1
    R_BAND = 2
    I_BAND = 3


class FinkClassification(str, Enum):
    """Fink machine-learning classification labels.

    These classifications are assigned by Fink's ML pipeline based on
    alert features and light curve characteristics.
    """

    SN_CANDIDATE = "SN candidate"
    EARLY_SN_IA = "Early SN Ia candidate"
    KILONOVA = "Kilonova candidate"
    MICROLENSING = "Microlensing candidate"
    SOLAR_SYSTEM = "Solar System MPC"
    VARIABLE_STAR = "Variable Star"
    AGN = "AGN"
    UNKNOWN = "Unknown"

    @classmethod
    def from_string(cls, value: str) -> "FinkClassification":
        """Convert string to FinkClassification, defaulting to UNKNOWN."""
        for member in cls:
            if member.value == value:
                return member
        return cls.UNKNOWN


class PreviousCandidate(BaseModel):
    """Historical detection from the alert's light curve history.

    ZTF alerts include up to 30 days of previous detections, enabling
    light curve analysis without additional API calls.

    Attributes:
        jd: Julian date of detection.
        fid: Filter ID (1=g, 2=r, 3=i).
        magpsf: PSF-fit magnitude (brightness).
        sigmapsf: Magnitude uncertainty.
        diffmaglim: Limiting magnitude of difference image.
        isdiffpos: Whether the source is positive in the difference image.
    """

    model_config = ConfigDict(extra="allow")

    jd: float = Field(..., description="Julian date of detection")
    fid: int = Field(..., ge=1, le=3, description="Filter ID")
    magpsf: float | None = Field(None, description="PSF magnitude")
    sigmapsf: float | None = Field(None, ge=0, description="Magnitude uncertainty")
    diffmaglim: float | None = Field(None, description="Limiting magnitude")
    isdiffpos: str | None = Field(None, description="Positive difference (t/f)")

    @property
    def mjd(self) -> float:
        """Convert Julian Date to Modified Julian Date."""
        return self.jd - 2400000.5

    @property
    def is_detection(self) -> bool:
        """Check if this is a real detection (has measured magnitude)."""
        return self.magpsf is not None


class ZTFAlert(BaseModel):
    """Raw ZTF alert structure as received from Fink API.

    This model represents the core alert data from the Zwicky Transient
    Facility, as processed and enriched by the Fink broker.

    Attributes:
        objectId: ZTF object identifier (e.g., 'ZTF21aaxtctv').
        candid: Unique candidate/alert identifier.
        ra: Right ascension in degrees (0-360).
        dec: Declination in degrees (-90 to +90).
        magpsf: PSF-fit magnitude of the detection.
        sigmapsf: Magnitude uncertainty.
        fid: Filter ID (1=g, 2=r, 3=i).
        jd: Julian date of observation.
        diffmaglim: Limiting magnitude of difference image.
        prv_candidates: Previous 30 days of detections.
    """

    model_config = ConfigDict(extra="allow")

    # Core identifiers
    objectId: str = Field(..., description="ZTF object identifier", min_length=3)
    candid: int | None = Field(None, description="Unique candidate identifier")

    # Celestial coordinates
    ra: float = Field(..., ge=0, lt=360, description="Right ascension (degrees)")
    dec: float = Field(..., ge=-90, le=90, description="Declination (degrees)")

    # Photometric measurements
    magpsf: float = Field(..., description="PSF magnitude")
    sigmapsf: float = Field(..., ge=0, description="Magnitude uncertainty")
    fid: int = Field(..., ge=1, le=3, description="Filter ID")

    # Temporal information
    jd: float = Field(..., gt=2400000, description="Julian date of observation")

    # Detection quality
    diffmaglim: float | None = Field(None, description="Limiting magnitude")
    rb: float | None = Field(None, ge=0, le=1, description="Real/bogus score")
    drb: float | None = Field(None, ge=0, le=1, description="Deep learning real/bogus")

    # Light curve history
    prv_candidates: list[dict[str, Any]] | None = Field(
        None, description="Previous detections (up to 30 days)"
    )

    # Fink classifications (added by broker)
    v__fink_class: str | None = Field(None, alias="v:fink_class")
    d__cdsxmatch: str | None = Field(None, alias="d:cdsxmatch")

    @property
    def mjd(self) -> float:
        """Convert Julian Date to Modified Julian Date."""
        return self.jd - 2400000.5

    @property
    def filter_name(self) -> str:
        """Get human-readable filter name."""
        return {1: "g", 2: "r", 3: "i"}.get(self.fid, "unknown")

    @property
    def fink_class(self) -> FinkClassification:
        """Get Fink classification as enum."""
        if self.v__fink_class:
            return FinkClassification.from_string(self.v__fink_class)
        return FinkClassification.UNKNOWN

    @field_validator("objectId")
    @classmethod
    def validate_object_id(cls, v: str) -> str:
        """Validate ZTF object ID format."""
        # ZTF IDs typically start with 'ZTF' followed by year and random chars
        if not v.startswith("ZTF"):
            # Allow non-ZTF IDs but log a warning in practice
            pass
        return v

    def get_previous_candidates(self) -> list[PreviousCandidate]:
        """Parse previous candidates into validated models."""
        if not self.prv_candidates:
            return []
        result = []
        for prv in self.prv_candidates:
            try:
                result.append(PreviousCandidate(**prv))
            except Exception:
                # Skip invalid previous candidates
                continue
        return result


class BronzeAlert(BaseModel):
    """Bronze layer alert with metadata for storage and tracking.

    This model wraps the raw ZTF alert with additional metadata needed
    for data management: ingestion timestamps, source tracking, and
    processing state.

    Attributes:
        alert: The original ZTF alert data.
        ingestion_timestamp: When the alert was ingested into our system.
        source: Data source identifier (e.g., 'fink_api').
        source_version: API or schema version from source.
        raw_payload: Complete original payload for audit purposes.
        processing_id: Unique ID for this processing batch.
    """

    model_config = ConfigDict(extra="forbid")

    # Core alert data
    alert: ZTFAlert

    # Ingestion metadata
    ingestion_timestamp: datetime = Field(
        default_factory=datetime.utcnow, description="When alert was ingested"
    )
    source: str = Field(default="fink_api", description="Data source identifier")
    source_version: str | None = Field(None, description="Source API version")

    # Audit trail
    raw_payload: dict[str, Any] | None = Field(
        None, description="Original unmodified payload"
    )
    processing_id: str | None = Field(None, description="Batch processing identifier")

    # Derived fields for partitioning
    observation_date: str | None = Field(
        None, description="Date of observation (YYYY-MM-DD) for partitioning"
    )

    @model_validator(mode="after")
    def compute_derived_fields(self) -> "BronzeAlert":
        """Compute derived fields from alert data."""
        if self.observation_date is None and self.alert:
            # Convert JD to date string for partitioning
            from astropy.time import Time

            try:
                t = Time(self.alert.jd, format="jd")
                self.observation_date = t.datetime.strftime("%Y-%m-%d")
            except Exception:
                # Fallback to ingestion date if conversion fails
                self.observation_date = self.ingestion_timestamp.strftime("%Y-%m-%d")
        return self

    @property
    def object_id(self) -> str:
        """Shortcut to the ZTF object ID."""
        return self.alert.objectId

    @property
    def candidate_id(self) -> int | None:
        """Shortcut to the candidate ID."""
        return self.alert.candid

    def to_flat_dict(self) -> dict[str, Any]:
        """Convert to flat dictionary for Parquet storage.

        Flattens nested alert data for efficient columnar storage while
        preserving the full payload in a JSON column.
        """
        import json

        flat = {
            # Identifiers
            "object_id": self.alert.objectId,
            "candidate_id": self.alert.candid,
            # Coordinates
            "ra": self.alert.ra,
            "dec": self.alert.dec,
            # Photometry
            "magpsf": self.alert.magpsf,
            "sigmapsf": self.alert.sigmapsf,
            "filter_id": self.alert.fid,
            "filter_name": self.alert.filter_name,
            # Temporal
            "jd": self.alert.jd,
            "mjd": self.alert.mjd,
            "observation_date": self.observation_date,
            # Quality
            "diffmaglim": self.alert.diffmaglim,
            "rb_score": self.alert.rb,
            "drb_score": self.alert.drb,
            # Classification
            "fink_class": self.alert.v__fink_class,
            "cds_xmatch": self.alert.d__cdsxmatch,
            # Metadata
            "ingestion_timestamp": self.ingestion_timestamp.isoformat(),
            "source": self.source,
            "source_version": self.source_version,
            "processing_id": self.processing_id,
            # Full payload for audit
            "raw_payload_json": json.dumps(self.raw_payload) if self.raw_payload else None,
            # Light curve summary
            "num_previous_detections": len(self.alert.prv_candidates or []),
        }
        return flat


class AlertBatch(BaseModel):
    """A batch of alerts for bulk processing.

    Attributes:
        alerts: List of bronze alerts in this batch.
        batch_id: Unique identifier for this batch.
        created_at: When the batch was created.
        source_query: Query parameters used to fetch this batch.
    """

    model_config = ConfigDict(extra="forbid")

    alerts: list[BronzeAlert]
    batch_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    source_query: dict[str, Any] | None = None

    @property
    def count(self) -> int:
        """Number of alerts in the batch."""
        return len(self.alerts)

    @property
    def object_ids(self) -> list[str]:
        """List of unique object IDs in the batch."""
        return list({alert.object_id for alert in self.alerts})
