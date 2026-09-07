---
status: accepted
date: 2026-09-06
---

# Platform tables own tenancy

ADR 0003 mirrored organizations and memberships from Keycloak Organizations and made Keycloak the source of truth for tenancy.
The enterprise demo needs several organizations, per-organization roles, invitations by email and an organization switcher in days,
and the realm role written back to the membership on every request made an organization role impossible.
Organizations, memberships and invitations now live in the platform database and are managed through `/v1alpha1/organizations`.
Keycloak authenticates and marks platform admins (realm role `admin`); the role inside an organization lives on the membership,
is set once when the membership is created (invitation role, or the realm role on a first login), and is changed by an organization admin.
This supersedes the deferred direction in ADR 0003.

## Considered options

- Keycloak Organizations as the source of truth: no second model, but the platform would depend on a Keycloak feature
  that is still preview in the version the lab runs, the invitation flow would live in Keycloak's UI, and every role change would need a sync.
- Organization membership as realm groups: one group per organization and role; simple to read from the token,
  but self-service invitations and an organization admin who is not a realm admin cannot be expressed.

## Consequences

- A user promoted in Keycloak after first login is not promoted in an organization automatically; the organization admin does it (`docs/local-dev.md`).
- `organizations.idp_org_id` stays; Keycloak Organizations can be mirrored into it later without a schema change.
- `X-Org` selects the active organization per request; a personal token is bound to one organization (ADR 0009).
- Existing memberships keep their role; nothing changes for the running lab.
- The gateway's ext-authz call (`GET /v1alpha1/authz/route`) receives `authorization` and the Keycloak `cookie` only, never `X-Org`
  (the UI's `aiops_org` cookie is host-only), so the route re-scopes the caller to the resource's organization when they are a member of it (`as_member_of`).
