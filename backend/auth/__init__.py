"""Bearer-token authentication and ownership checks for the API.

``settings`` reads the ``AUTH_MODE`` and ``OIDC_*`` environment,
``jwt`` validates tokens against the realm JWKS, ``current_user`` is the
FastAPI dependency that maps a token to a user and organization, and
``policy`` answers who may read or write a resource.
"""
