---
status: proposed
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
