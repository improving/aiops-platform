"""Signed test tokens for the oidc-mode tests: the ``oidc_client``
fixture in conftest.py serves the matching JWKS."""

import time

import jwt

ISSUER = "https://issuer.invalid/realms/test"
AUDIENCE = "aiops-api"
KID = "test-key"


def make_token(
    key,
    sub="alice",
    email="alice@example.test",
    name="Alice",
    roles=("member",),
    azp="aiops-ui",
    aud=AUDIENCE,
    iss=ISSUER,
    expires_in=300,
    kid=KID,
    # None omits the claim entirely, as a real unverified-by-default token
    # would; True/False sends the literal claim.
    email_verified: bool | None = True,
):
    now = int(time.time())
    claims = {
        "iss": iss,
        "aud": aud,
        "sub": sub,
        "azp": azp,
        "iat": now,
        "exp": now + expires_in,
        "realm_access": {"roles": list(roles)},
    }
    if email is not None:
        claims["email"] = email
    if name is not None:
        claims["name"] = name
    if email_verified is not None:
        claims["email_verified"] = email_verified
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}
