"""Versioned JSON message exchange."""

from .decoder import decode
from .encoder import encode
from .model import Message, MessageError

__all__ = ["Message", "MessageError", "encode", "decode"]
