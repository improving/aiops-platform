---
status: accepted
date: 2026-09-06
---

# The platform mints personal API tokens

ADR 0004 said the platform never mints its own user tokens and deferred personal tokens until a CLI exists.
The enterprise demo needs a person to call the API with `curl` and an SDK, with revocation and attribution in usage,
and Keycloak's offline tokens cannot be listed, named or scoped per user by the platform.
The platform now issues personal tokens `aiops_<prefix>_<secret>`:
the database stores the prefix and `sha256(secret)`, a token has a scope (`read` or `write`), an expiry (1 to 365 days) and can be revoked;
`get_current_user` resolves it into the token's user in the token's organization, so every policy and the usage attribution (`user_key`) are unchanged.
Client credentials stay the mechanism for systems, and workload credentials (per-instance keys) are untouched.
This supersedes the "never its own user tokens" rule of ADR 0004.

## Considered options

- Keycloak offline tokens: no new secret store, but no per-token name, scope or list in the platform,
  and revocation goes through Keycloak's session view rather than the organization admin.
- Platform-signed JWTs: stateless, but a second issuer to secure and rotate, and revocation would need a deny list anyway.

## Consequences

- Rotation is revoke and create; there is no in-place rotation.
- A `read` token runs as a viewer whatever the membership role; a `write` token keeps it.
- A token cannot manage tokens (403), so a leaked token cannot mint successors.
- `last_used_at` is written with the same one-minute resolution as `users.last_seen_at`.
