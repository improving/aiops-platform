---
status: accepted
date: 2026-09-04
---

# Every resource belongs to an organization and an owner from day one

The first users are one team, but the platform should become multi-tenant without a data migration under load.
Every resource table (`notebooks`, `vectordb_instances`, `inference_instances`, `finetunes`, `model_adapters`)
gains `org_id` and `owner_id` now; a single default organization is created and existing rows are backfilled to it,
and the API filters every list and checks every mutation by organization and role (`admin`, `member`, `viewer`).
Organizations and memberships mirror Keycloak Organizations, which stays the source of truth for tenancy.

## Considered options

- Owner only, organizations later: cheaper now, but every query and the authorization endpoint would be rewritten
  when the second tenant arrives.
- Kubernetes namespace per user or tenant now: Kubeflow's model, but it multiplies Helm releases and quotas before
  anyone needs isolation; deferred to Phase 4 as a per-organization namespace.

## Consequences

- Alembic replaces the runtime schema sync in `db/db.py` for this and future migrations, because a backfill cannot be expressed there.
- Catalog tables (models, engines, vector databases) stay global; sharing catalogs per organization is deliberately not modelled.
- Explicitly deferred: self-signup, invitations, quotas, billing, per-organization namespaces, sharing a resource with another user.

## Implementation notes

Alembic landed as a baseline migration
(`0001_baseline`, generated with `alembic revision --autogenerate` against an empty database and reviewed)
plus the tenancy migration (`0002_tenancy`) that adds the three new tables,
batch-adds `org_id`/`owner_id` to every resource table,
and inserts the one `default` organization existing rows are backfilled to, exactly as designed.
`db/migrate.py::upgrade_to_head` stamps a pre-Alembic database at `0001` first,
so the home-grown schema sync it replaces does not have to be run again by hand.
