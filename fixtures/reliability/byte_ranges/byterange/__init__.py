"""Bounded byte-range resolution."""

from .ranges import RangeSyntaxError, ResolvedRange, UnsatisfiableRange, resolve_ranges

__all__ = ["RangeSyntaxError", "ResolvedRange", "UnsatisfiableRange", "resolve_ranges"]
