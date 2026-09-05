import os
from dataclasses import dataclass

MODE_OIDC = "oidc"
MODE_DISABLED = "disabled"
DEFAULT_AUDIENCE = "aiops-api"


@dataclass(frozen=True)
class AuthSettings:
    mode: str
    issuer: str | None
    audience: str
    jwks_url: str | None


def auth_settings() -> AuthSettings:
    """Read the auth settings from the environment.

    Read at call time, not at import, so tests can change the environment
    between apps.
    """
    mode = os.environ.get("AUTH_MODE", MODE_OIDC).strip().lower()
    issuer = os.environ.get("OIDC_ISSUER", "").strip().rstrip("/") or None
    audience = os.environ.get("OIDC_AUDIENCE", "").strip() or DEFAULT_AUDIENCE
    jwks_url = os.environ.get("OIDC_JWKS_URL", "").strip() or None
    if jwks_url is None and issuer is not None:
        jwks_url = f"{issuer}/protocol/openid-connect/certs"
    return AuthSettings(
        mode=mode, issuer=issuer, audience=audience, jwks_url=jwks_url
    )


def check_auth_settings(test_mode: bool) -> AuthSettings:
    """Validate the settings at startup and return them.

    Raises ``RuntimeError`` with a human-readable message when the
    configuration cannot work: an unknown mode, ``disabled`` outside
    ``TEST_MODE``, or ``oidc`` without an issuer. The JWKS itself is fetched
    lazily on the first request, so an unreachable issuer does not block
    startup.
    """
    settings = auth_settings()
    if settings.mode not in (MODE_OIDC, MODE_DISABLED):
        raise RuntimeError(
            f"AUTH_MODE must be 'oidc' or 'disabled', not {settings.mode!r}"
        )
    if settings.mode == MODE_DISABLED and not test_mode:
        raise RuntimeError("AUTH_MODE=disabled requires TEST_MODE=true")
    if settings.mode == MODE_OIDC and settings.issuer is None:
        raise RuntimeError(
            "OIDC_ISSUER must be set when AUTH_MODE=oidc "
            "(for example https://auth.127.0.0.1.nip.io/realms/aiops)"
        )
    return settings
