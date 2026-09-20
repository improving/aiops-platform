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
`scope` is `read` (the request runs as a viewer), `write` (the membership role applies)
or `mcp` (the membership role applies, on `/v1alpha1/mcp` only and 403 elsewhere: the scope for an IDE or an agent that needs the tools and nothing else).
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

While an instance is not ready, the list and detail responses of all three kinds also carry `launch`,
what the instance is waiting for, derived from its pods on every read and never stored:

```json
{
  "phase": "Scheduling",
  "message": "Unschedulable: 0/1 nodes are available: 1 Insufficient nvidia.com/gpu.",
  "since": "2026-09-18T11:39:42+00:00",
  "needs_attention": true,
  "restart_count": 0,
  "replicas_total": 1,
  "downloaded_bytes": null,
  "total_bytes": null
}
```

`phase` is one of `Scheduling` (no node yet; `message` carries the scheduler's reason when there is one),
`Blocked` (a container cannot be created, for example `CreateContainerConfigError` for a missing Secret; `message` carries the kubelet's reason),
`Pulling image`, `Starting` (the container runs and is not ready: a model server downloads and loads its model here),
`Restarting` (the container restarted; `message` names the last exit and `restart_count` the number)
and `Terminating`.
`since` is when that step began, so a client can show the elapsed time.
`needs_attention` is true when only a person can move the launch on (an unschedulable pod, `Blocked`, `Restarting`); style by it, not by the wording of `message`.
A `Failed` or `Succeeded` pod (an evicted one) does not count.
For an inference instance in phase `Starting`, `downloaded_bytes` and `total_bytes` say how far the model download is,
when the API pod can see the model cache (`backend.hfCache.mount`); `message` then reads "Downloading the model: 8.0 of 10.0 GB".
Both are equal once the download is complete and the model loads, and both are `null` when that is not known
(no mount, a model that is not a Hugging Face id, a registry entry without a size gives `total_bytes: null`).
`launch` is `null` once the instance is ready, on a stopped instance, and on a failed one, where `last_error` has the reason.
It never changes `status`, which stays one of the four words above, and a `PUT` cannot set it.

## Hosts

`GET /v1alpha1/hosts` lists the Ready nodes (`includeNotReady=true` adds the others) for the launch form.
The GPU fields come from the GPU operator's node labels: `gpu_count`, `gpu_memory` (MiB for each GPU), `gpu_model`,
`gpu_replicas` (time slices of a GPU; 1 without time-slicing) and `gpu_sharing_strategy`.
What the node offers and what is asked of it come from the node and its pods:
`allocatable_cpu` (cores), `allocatable_memory` (MiB) and `allocatable_gpu` are the node's `status.allocatable`;
`requested_cpu`, `requested_memory` and `gpu_usage` sum the container requests of the Pending and Running pods on the node,
so a finished pod counts for nothing.
Free is allocatable minus requested. A pod without requests takes what it needs and is not in these numbers,
so they are what the scheduler works with, not the node's real load.
`cpu_cores` and `cpu_memory` read two node labels that NFD does not publish and are 0 on a real cluster; use the allocatable fields.

## Logs and events

```
GET /v1alpha1/{inferenceInstance|vectordb_instances|notebooks}/{id}/logs?container=&tail=200&previous=false
GET /v1alpha1/{inferenceInstance|vectordb_instances|notebooks}/{id}/events
```

`logs` answers `{"pods": [{"name": "...", "containers": [{"name": "...", "log": "..."}]}]}`;
`container` keeps only that container,
`tail` clamps to 1..5000,
`previous` reads the last terminated container.
`events` answers a list of `{at, count, first_at, type, reason, message, object}`,
newest first, at most 100,
covering the pods and their Deployment or StatefulSet.
Kubernetes folds a repeated event into one: `at` is the last time, `count` how often (1 for a single event) and `first_at` the first time (`null` for a single event).
It writes no event when a problem ends, so a readiness warning from the start of an instance that is ready now is history, not its state.
Both need the read policy;
a notebook is visible to its owner only.

## Day-2 actions

```
POST /v1alpha1/{inferenceInstance|vectordb_instances}/{id}/restart
POST /v1alpha1/inferenceInstance/{id}/stop
POST /v1alpha1/inferenceInstance/{id}/resume
POST /v1alpha1/inferenceInstance/{id}/scale   {"replicas": <0-16>}
PUT  /v1alpha1/inferenceInstance/{id}/settings  {"args": {...}, "env_vars": {...}}
```

All five need the write policy.
`restart` rolls the pods and sets `Pending`;
409 when the row is `Stopped` (resume it first) or has no workload yet.
Notebooks have no actions.
`stop` scales the release to zero replicas and sets `Stopped`, keeping the LiteLLM registration;
`resume` scales back to the stored `replicas` (or 1);
`scale` with `0` is the same as `stop` and keeps the stored count.
`settings` replaces the instance's own CLI arguments and environment variables (what differs from the engine defaults;
a flag is an argument with an empty value, for example `{"--enable-auto-tool-choice": "", "--tool-call-parser": "hermes"}`)
and upgrades the release, so the pods restart and the row is `Pending`; a `Stopped` instance stays stopped and starts from them on resume.
The instance payload's `settingsRead` (`"args"`, `"env_vars"`, both or none) says what the engine takes; anything else is 422, as on NIM and OPEA, which read neither.
Also 422, here and on create: a name that is not one, another value of a default the platform fixes,
a name the platform owns (`VLLM_API_KEY`, `HF_TOKEN`, `HF_API_TOKEN`, `--api-key`),
and `max_model_len` or `port` under another spelling or with a value that is not a whole number.
When only the gateway step fails (500), the values are kept, because the pods already run with them.

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

## MCP servers and the MCP endpoint

An organization admin registers remote MCP servers; every member with a writer role uses their tools
(ADR 0010, `docs/superpowers/specs/2026-09-19-tools-and-mcp-design.md`). Needs the LiteLLM proxy: without it the writes and the endpoint answer 503.

| Route | Who | What |
| --- | --- | --- |
| `GET /v1alpha1/mcp/servers` | member | The organization's servers, with their tools from the last refresh. Never a credential. |
| `POST /v1alpha1/mcp/servers/discover` | admin | `{url, transport?, credential?}`: connect once, answer the tools (`name`, `description`, `read_only`). Nothing is stored. |
| `POST /v1alpha1/mcp/servers` | admin | `{name, url, transport?, description?, credential?, allowed_tools?}`. 409 on a name the organization already has, 400 on a refused URL, 502 when the server or the proxy cannot be reached (nothing is left behind). |
| `PATCH /v1alpha1/mcp/servers/{id}` | admin | Any of `description`, `url`, `transport`, `enabled`, `allowed_tools` (or `allow_all_tools: true`), `credential`, `remove_credential: true`. |
| `POST /v1alpha1/mcp/servers/{id}/refresh` | admin | Connect again. A server that is down answers 200 with `status: "unreachable"` and keeps its last tool list. |
| `PUT /v1alpha1/mcp/servers/{id}/credential` | writer | `{value}`: the caller's own credential for a server of mode `per_user`. It is tried against the server first (400 when refused), stored in a Secret of the caller's own, and never returned. 409 on a server of another mode. |
| `DELETE /v1alpha1/mcp/servers/{id}/credential` | member | Removes the caller's own credential. |
| `DELETE /v1alpha1/mcp/servers/{id}` | admin | The proxy's registration first (it holds a copy of a shared credential): when the proxy refuses, 502 and everything stays. Then every Secret and the row. |

`name` is lower case letters, digits and `_` (it starts with a letter, 32 characters at most).
`transport` is `http` (streamable HTTP, the default) or `sse`.
`credential` is `{auth_type: "bearer", value}` or `{auth_type: "header", auth_header, value}`; it lives in a Kubernetes Secret and is shared by the organization.
With `credential_mode: "per_user"` each member brings their own instead (a GitHub token, say, so the model works in that member's repositories):
the `credential` of the create is then the admin's own (it tests the connection and sets the header shape), `credential_help_url` says where to get one,
the proxy is registered with none, and each call carries the caller's value. A member without one does not get that server among "all servers",
and a request that names it in `X-Mcp-Servers` answers 409. A removed member's credentials are deleted first; when that fails the member stays (502).
A `PATCH` with `credential_mode` and a `credential` changes the mode and leaves no credential of the other mode behind.
On a `per_user` server a credential change must name `credential_mode` (400 otherwise), because `shared` and `none` delete every member's credential;
`per_user` with the admin's own credential in the same header shape replaces only theirs. The proxy is updated first, so a failure (502) leaves every credential as it was.
`credential_help_url` must be an `http(s)` URL (422).
The URL must be `https` and public: loopback, private, link-local, metadata and cluster-internal addresses are refused.
A server answers with `credential_mode` (`none`, `shared` or `per_user`), `my_credential` (`not_needed`, or `set` or `missing` on a `per_user` server), `credential_header`, `credential_help_url`,
`status` (`connected` or `unreachable`), `checked_at`, `tools`, and `tool_prefix`: a model sees each tool as `<tool_prefix><tool>`.

`/v1alpha1/mcp` is one MCP server (streamable HTTP; `POST` and `DELETE`) with the tools of every enabled server of the caller's organization.
`GET` answers 405, which the protocol allows: there is no server-to-client stream, because each open one would hold a worker thread of the API for as long as an IDE stays connected.
It takes a session token or a personal token; a token of scope `mcp` is valid here and nowhere else. A viewer gets 403, because a tool can change data.
`X-Mcp-Servers: <name>,<name>` limits the request to those servers (400 for a name that is unknown or disabled).
A client outside the browser uses the API host, not the UI's `/api/` path, which is a session proxy and sends a caller without a session to the login page.

```bash
curl -N -X POST https://api.<domain>/v1alpha1/mcp \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

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

With `AIOPS_BACKEND_CLUSTER_URL` set and a writer role, the same call also writes `AIOPS_MCP_URL` (the platform's MCP endpoint as a pod reaches it)
and `AIOPS_MCP_TOKEN` (a personal token of scope `mcp`, named `langflow` on the API tokens page and renewed by the platform) for Langflow's MCP Tools component.

## Examples

List the inference instances of the token's organization:

```bash
curl "$AIOPS_URL/v1alpha1/inferenceInstance" \
  -H "Authorization: Bearer aiops_xxxxxxxx_yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy"
```

One chat completion through the control plane and LiteLLM
(`model` is a target name from `GET /v1alpha1/chat/targets`, `inst-<id8>` for a deployed instance;
each target also carries `context_length`, the window it serves in tokens, or `null` when the platform does not set it,
and `tools`: `true` or `false` when the platform knows whether the target answers a request with `tools`
(a vLLM instance's tool-calling flag, a hosted model's entry in the price catalog), `null` when it does not know.
The request body goes to the model as it is, `tools` and `tool_choice` included):

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
