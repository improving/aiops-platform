"""Token validation against the realm JWKS.

The ``PyJWKClient`` is created on the first request, not at import or
startup, so the API starts even while the identity provider is down.
``PyJWKClient`` fetches with ``urllib``: a private CA (the local kind
stack) must be in ``SSL_CERT_FILE``; ``REQUESTS_CA_BUNDLE`` has no effect.
"""

import jwt
from jwt import PyJWKClient

from auth.settings import auth_settings

ALGORITHMS = ["RS256"]
# Seconds of clock skew tolerated on exp, nbf and iat.
LEEWAY_SECONDS = 60

_client: PyJWKClient | None = None
_client_url: str | None = None


def jwks_client() -> PyJWKClient:
    """The JWKS client for the configured issuer, built once."""
    global _client, _client_url
    url = auth_settings().jwks_url
    if url is None:
        raise RuntimeError("OIDC_ISSUER or OIDC_JWKS_URL must be set")
    if _client is None or _client_url != url:
        _client = PyJWKClient(url, cache_keys=True)
        _client_url = url
    return _client


def reset_jwks_client() -> None:
    """Forget the cached client and its keys (tests, key rotation)."""
    global _client, _client_url
    _client = None
    _client_url = None


def decode_token(token: str) -> dict:
    """Verify the signature, issuer, audience and lifetime; return claims.

    Raises ``jwt.exceptions.PyJWTError`` subclasses on every failure,
    ``PyJWKClientConnectionError`` when the JWKS cannot be fetched.
    """
    settings = auth_settings()
    key = jwks_client().get_signing_key_from_jwt(token).key
    return jwt.decode(
        token,
        key,
        algorithms=ALGORITHMS,
        audience=settings.audience,
        issuer=settings.issuer,
        leeway=LEEWAY_SECONDS,
    )
