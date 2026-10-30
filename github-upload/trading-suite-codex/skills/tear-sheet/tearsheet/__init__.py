"""tear-sheet: QuantStats performance tear-sheet from a trade log or equity curve."""

from .tearsheet import (
    LoadResult,
    TearSheetError,
    build_report,
    load_returns,
)

__all__ = ["LoadResult", "TearSheetError", "build_report", "load_returns"]
