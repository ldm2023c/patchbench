"""Verification retains constant-time digest comparison."""
import hmac

from .signer import sign


def verify(request, key, signature, signed_headers=("host",)):
    expected = sign(request, key, signed_headers)
    if not isinstance(signature, str) or len(signature) != 64 or any(c not in "0123456789abcdef" for c in signature):
        return False
    return hmac.compare_digest(expected, signature)
