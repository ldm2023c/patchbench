"""HMAC signing over the shared request representation."""
import hashlib
import hmac

from .canonical import canonical_request


def sign(request, key, signed_headers=("host",)):
    return hmac.new(key, canonical_request(request, signed_headers), hashlib.sha256).hexdigest()
