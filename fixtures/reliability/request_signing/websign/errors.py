"""Malformed request errors shared by signing and verification."""


class CanonicalizationError(ValueError):
    """A request cannot be represented under the signing contract."""
