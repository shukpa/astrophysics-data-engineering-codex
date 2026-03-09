"""Agentic Galactic Discovery - Real-time astronomical transient discovery using AI.

This package provides tools for ingesting, processing, and analyzing astronomical
transient alerts from survey telescopes like ZTF and LSST/Rubin.
"""

__version__ = "0.1.0"

from src.exceptions import AGDError
from src.utils.config import Settings, get_settings

__all__ = [
    "AGDError",
    "Settings",
    "get_settings",
    "__version__",
]
