# Calling the API without a browser

Every route under `/v1alpha1/` needs a bearer token.
People use a personal API token; systems keep using OAuth2 client credentials from Keycloak (ADR 0004, ADR 0009).

## Personal API tokens

Create one on `/settings/tokens` (user menu, "API tokens") or with a signed-in session:

```bash
curl -X POST "$AIOPS_URL/v1alpha1/tokens" \
  -H "Authorization: Bearer $KEYCLOAK_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "laptop", "scope": "write", "expires_in_days": 90}'
```

The answer carries `token` exactly once: `aiops_<8 characters>_<32 characters>`.
The platform stores the prefix and a SHA-256 hash of the secret, never the token.
`scope` is `read` (the request runs as a viewer) or `write` (the membership role applies).
`expires_in_days` is 1 to 365, default 90.
`GET /v1alpha1/tokens` lists the caller's own tokens, or every token in the organization with `?all=true` (admins only).
Revoke a token with `DELETE /v1alpha1/tokens/{id}`; a token cannot create or revoke tokens (403).
A revoked or expired token answers 401 with `The token was revoked` or `The token has expired`.

`$AIOPS_URL` is the backend (`http://localhost:8000` locally) or the UI origin plus `/api`
(`https://<ui host>/api`): the UI proxy forwards a request that carries its own `Authorization` header unchanged.

## The active organization: `X-Org`

A user may belong to several organizations.
A personal token is bound to the organization it was created in and ignores the header.
A Keycloak token (a browser session, or client credentials) runs in the user's first membership
unless the request names another one with `X-Org: <slug>`;
naming an organization the user is not a member of answers 403 `You are not a member of this organization`.
Through the UI origin the proxy drops a client-sent `X-Org` and sets it from the signed-in browser's own cookie instead;
send `X-Org` to the backend directly.
`GET /v1alpha1/organizations` lists the caller's memberships and the active slug.

## Instance status

Inference instances, vector database instances and notebooks each carry a platform-written `status`:
`Pending`, `Running`, `Failed` or `Stopped`,
plus `last_error` (a human-readable string, at most 4000 characters), `last_error_at` and `stopped_at`.
`status` is `null` on a row the platform has not looked at yet.
A failed install or upgrade answers 500 and leaves the row `Failed` with the reason in `last_error`;
the half-created (or, on a failed upgrade, previous) Helm release is uninstalled best effort.
Inference instances also carry `replicas`, `gpu_count`, `cpu` and `memory`;
none of these nine fields can be set through a `PUT`, whatever the request body sends.

## Logs and events

```
GET /v1alpha1/{inferenceInstance|vectordb_instances|notebooks}/{id}/logs?container=&tail=200&previous=false
GET /v1alpha1/{inferenceInstance|vectordb_instances|notebooks}/{id}/events
```

`logs` answers `{"pods": [{"name": "...", "containers": [{"name": "...", "log": "..."}]}]}`;
`container` keeps only that container,
`tail` clamps to 1..5000,
`previous` reads the last terminated container.
`events` answers a list of `{at, type, reason, message, object}`,
newest first, at most 100,
covering the pods and their Deployment or StatefulSet.
Both need the read policy;
a notebook is visible to its owner only.

## Day-2 actions

```
POST /v1alpha1/{inferenceInstance|vectordb_instances}/{id}/restart
POST /v1alpha1/inferenceInstance/{id}/stop
POST /v1alpha1/inferenceInstance/{id}/resume
POST /v1alpha1/inferenceInstance/{id}/scale   {"replicas": <0-16>}
```

All four need the write policy.
`restart` rolls the pods and sets `Pending`;
409 when the row is `Stopped` (resume it first) or has no workload yet.
Notebooks have no actions.
`stop` scales the release to zero replicas and sets `Stopped`, keeping the LiteLLM registration;
`resume` scales back to the stored `replicas` (or 1);
`scale` with `0` is the same as `stop` and keeps the stored count.

## Organizations, members and invitations

```
GET/POST      /v1alpha1/organizations                        (POST: platform admin; slug ^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$)
GET           /v1alpha1/organizations/current                (adds member_count, is_platform_admin)
GET           /v1alpha1/organizations/current/members         (admin)
PUT/DELETE    /v1alpha1/organizations/current/members/{id}    (admin; last admin and removing yourself both answer 409; DELETE rotates the organization's LiteLLM key first, 502 and no removal when that fails)
GET/POST      /v1alpha1/organizations/current/invitations     (admin)
DELETE        /v1alpha1/organizations/current/invitations/{id} (admin; withdraw)
```

An invitation is accepted automatically on the invited email's next sign-in,
once Keycloak reports the email verified.

## Audit log

```
GET /v1alpha1/organizations/current/audit?from=&to=&actor=&action=&resource_kind=&limit=100&cursor=&format=json&include_anonymous=false
```

Admin only.
`from`/`to` are naive ISO 8601 timestamps;
`limit` is 1 to 1000, default 100;
paging is a keyset `cursor` returned as `next_cursor` once more rows match.
`format=csv` ignores `limit` and streams every matching row, up to 100000,
with a `# truncated` trailer if it hit the cap.
`include_anonymous=true` (rows with no attributed actor) is platform-admin only, 403 otherwise.

## Spend, budget and usage

```
GET /v1alpha1/organizations/current/spend
PUT /v1alpha1/organizations/current/budget   {"budget_usd": <number or null>}   (admin)
GET /v1alpha1/organizations/current/usage?days=30
```

`spend`/`budget` answer the organization's LiteLLM team spend and cap;
`PUT` with `null` clears the cap.
`usage` aggregates spend log rows for the last `days` (1 to 90, 422 outside that range) by target and by day;
a member sees only their own rows, an admin every row including ones with no attributed user.
Every route answers 503 without LiteLLM configured, 502 on a LiteLLM error.

## Langflow

`POST /v1alpha1/langflow/provision` writes the caller's Langflow "OpenAI Compatible" provider variables
for the active organization and reports what Langflow now lists.
It runs as the caller: the request's own Keycloak bearer is forwarded to Langflow,
so it needs a browser session (the Develop page calls it on load), and it is idempotent.

```json
{
  "langflow_user": "alice",
  "organization": "Acme",
  "models": [{"name": "inst-68ed7110", "label": "Qwen3 0.6B · Ollama"}]
}
```

The variables it writes are `OPENAI_COMPATIBLE_BASE_URL` (the in-cluster LiteLLM address plus `/v1`)
and `OPENAI_COMPATIBLE_API_KEY` (the organization's virtual key), Langflow global variables on the caller's account.
`models` are the organization's chat targets by the names Langflow's pickers list live from LiteLLM,
read from the database without a readiness probe.
503 when `LANGFLOW_API_URL` or LiteLLM is not configured;
409 for a personal token or a service account (`detail` says a browser session is needed);
502 with Langflow's or LiteLLM's own detail when the write fails.

## Examples

List the inference instances of the token's organization:

```bash
curl "$AIOPS_URL/v1alpha1/inferenceInstance" \
  -H "Authorization: Bearer aiops_xxxxxxxx_yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy"
```

One chat completion through the control plane and LiteLLM
(`model` is a target name from `GET /v1alpha1/chat/targets`, `inst-<id8>` for a deployed instance):

```bash
curl -X POST "$AIOPS_URL/v1alpha1/chat/completions" \
  -H "Authorization: Bearer aiops_xxxxxxxx_yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy" \
  -H "Content-Type: application/json" \
  -d '{"model": "inst-0000abcd", "messages": [{"role": "user", "content": "Say hello"}]}'
```

Create an instance (a `write` token; ids from `GET /v1alpha1/models` and `GET /v1alpha1/engines`):

```bash
curl -X POST "$AIOPS_URL/v1alpha1/inferenceInstance" \
  -H "Authorization: Bearer aiops_xxxxxxxx_yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy" \
  -H "Content-Type: application/json" \
  -d '{"model": {"id": "<model id>"}, "engine": {"id": "<engine id>"}, "config": {}}'
```

Every response carries `X-Request-ID`, an unhandled 500 included; send your own to correlate a call with its audit event
(`GET /v1alpha1/organizations/current/audit`, admins).
