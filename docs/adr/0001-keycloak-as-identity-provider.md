---
status: accepted
date: 2026-09-04
---

# Keycloak is the single identity provider

The platform needs Google and GitHub login for the team, local accounts that work when the lab is offline,
and organizations later for tenants.
We run Keycloak 26.x in the cluster (operator on the lab, compose profile locally) with one realm, `aiops`,
that brokers Google and GitHub and holds local users;
the UI, the API and the gateway all trust only this realm.
Keycloak is Apache 2.0, has Organizations generally available since 26.0, and runs on the Postgres we already operate.

## Considered options

- Dex: a broker without a user store, so nothing can log in while the lab has no internet.
- Zitadel: organizations are a native primitive and a better SaaS fit, but the core has been AGPL-3.0 since v3;
  revisit if the platform is sold as a hosted service and the license is acceptable.
- Hosted providers (Auth0, Clerk, WorkOS, Okta, Entra ID): every login depends on their cloud, which the offline lab cannot meet.
- Authentik, Casdoor, Logto, Ory: capable, but smaller ecosystems or several services to assemble for the same result.

## Consequences

- Application code validates JWTs against the realm's JWKS and never talks to Keycloak directly,
  so the provider can be swapped without touching routers or pages.
- Keycloak needs about 2 GB of memory per replica on the lab; the compose profile uses less with the dev realm.
- Group and organization claims must be mapped into tokens by realm protocol mappers; that mapping is part of the realm import.

## Implementation notes

Keycloak runs in the kind cluster itself (`start-dev --import-realm`, `infra/local/auth/keycloak.yaml`),
not a docker-compose profile as first assumed;
the "compose locally" line above did not survive contact with the gateway-fronted design,
since every client needs one stable, gateway-reachable issuer URL.
`realm-aiops.json` has to define Keycloak's own built-in default client scopes
(`roles`, `profile`, `email`, `web-origins`, `basic`, `acr`) explicitly, with their standard mappers,
because a full `--import-realm` does not auto-seed them the way creating a realm through the Admin Console does;
any `defaultClientScopes` reference to a scope the file does not also define is silently dropped,
and a token loses that claim.
The `basic` scope's `sub` mapper needs its `config` spelled out the same way,
or access tokens carry no `sub` claim at all
and the API rejects them with "The token has no subject"
(`infra/local/auth/README.md`, "Why the realm defines the built-in scopes").
