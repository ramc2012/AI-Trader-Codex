"""Data processors for cleaning, validation, and transformation.

Provides reusable data processing components for cleaning raw market data,
validating integrity, and transforming into analysis-ready formats.
"""

from src.data.processors.base import DataProcessor
from src.data.processors.cleaners import (
    DuplicateRemover,
    GapFiller,
    OutlierRemover,
)
from src.data.processors.transformers import (
    CandleResampler,
    TimeAligner,
    VolumeNormalizer,
)
from src.data.processors.validators import (
    OHLCValidator,
    TimeSequenceValidator,
    VolumeValidator,
)

__all__ = [
    # Base
    "DataProcessor",
    # Cleaners
    "DuplicateRemover",
    "OutlierRemover",
    "GapFiller",
    # Validators
    "OHLCValidator",
    "TimeSequenceValidator",
    "VolumeValidator",
    # Transformers
    "CandleResampler",
    "TimeAligner",
    "VolumeNormalizer",
]
