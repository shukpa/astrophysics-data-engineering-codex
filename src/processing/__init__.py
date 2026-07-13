"""Data processing modules for the medallion architecture."""

from src.processing.bronze_processor import BronzeProcessor, create_bronze_processor
from src.processing.euclid_lens_processor import EuclidLensProcessor
from src.processing.gold_processor import GoldProcessor, create_gold_processor
from src.processing.silver_processor import SilverProcessor, create_silver_processor

__all__ = [
    "BronzeProcessor",
    "EuclidLensProcessor",
    "GoldProcessor",
    "SilverProcessor",
    "create_bronze_processor",
    "create_gold_processor",
    "create_silver_processor",
]
