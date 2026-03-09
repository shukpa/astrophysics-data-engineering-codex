"""Shared pytest fixtures for testing Agentic Galactic Discovery."""

from pathlib import Path
from typing import Any

import pytest

from src.utils.config import (
    ProcessingSettings,
    Settings,
    StorageSettings,
    clear_settings_cache,
)


@pytest.fixture(autouse=True)
def reset_settings() -> None:
    """Clear settings cache before each test."""
    clear_settings_cache()


@pytest.fixture
def temp_storage(tmp_path: Path) -> StorageSettings:
    """Create a StorageSettings instance with temporary paths."""
    return StorageSettings(base_path=tmp_path)


@pytest.fixture
def temp_settings(temp_storage: StorageSettings) -> Settings:
    """Create a Settings instance with temporary storage."""
    return Settings(storage=temp_storage)


@pytest.fixture
def sample_ztf_alert() -> dict[str, Any]:
    """Create a sample ZTF alert dictionary.

    This represents a typical alert from the Fink API with all
    standard fields populated.
    """
    return {
        "objectId": "ZTF21aaxtctv",
        "candid": 1234567890123,
        "ra": 193.822,
        "dec": 2.896,
        "magpsf": 18.5,
        "sigmapsf": 0.05,
        "fid": 1,
        "jd": 2460000.5,
        "diffmaglim": 20.5,
        "rb": 0.95,
        "drb": 0.98,
        "v:fink_class": "SN candidate",
        "d:cdsxmatch": "Unknown",
        "prv_candidates": [
            {
                "jd": 2459999.5,
                "fid": 1,
                "magpsf": 18.7,
                "sigmapsf": 0.06,
                "diffmaglim": 20.3,
                "isdiffpos": "t",
            },
            {
                "jd": 2459998.5,
                "fid": 2,
                "magpsf": 18.9,
                "sigmapsf": 0.07,
                "diffmaglim": 20.1,
                "isdiffpos": "t",
            },
        ],
    }


@pytest.fixture
def sample_alert_batch() -> list[dict[str, Any]]:
    """Create a batch of sample ZTF alerts."""
    base_alert = {
        "candid": 1234567890123,
        "ra": 193.822,
        "dec": 2.896,
        "magpsf": 18.5,
        "sigmapsf": 0.05,
        "fid": 1,
        "jd": 2460000.5,
        "diffmaglim": 20.5,
        "rb": 0.95,
        "drb": 0.98,
        "v:fink_class": "SN candidate",
    }

    alerts = []
    for i in range(10):
        alert = base_alert.copy()
        alert["objectId"] = f"ZTF21test{i:03d}"
        alert["ra"] = 100.0 + i * 10
        alert["candid"] = 1234567890123 + i
        alerts.append(alert)

    return alerts


@pytest.fixture
def strict_processing() -> ProcessingSettings:
    """Create ProcessingSettings with strict validation."""
    return ProcessingSettings(schema_validation_mode="strict")


@pytest.fixture
def lenient_processing() -> ProcessingSettings:
    """Create ProcessingSettings with lenient validation."""
    return ProcessingSettings(schema_validation_mode="warn")
