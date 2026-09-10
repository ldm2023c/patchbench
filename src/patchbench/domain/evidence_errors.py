"""Errors at the pure raw-artifact evidence parsing boundary."""


class EvidenceParsingError(ValueError):
    """Raw evidence cannot be interpreted safely in its canonical format."""
