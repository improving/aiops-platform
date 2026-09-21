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
GET /v1alpha1/{inferenceInstance|vectordb_instances|notebooks|mcp/instances}/{id}/logs?container=&tail=200&previous=false
GET /v1alpha1/{inferenceInstance|vectordb_instances|notebooks|mcp/instances}/{id}/events
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
POST /v1alpha1/{inferenceInstance|vectordb_instances|mcp/instances}/{id}/restart
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

The usage answer also has `tools`: the MCP tool calls of the period as `{server, tool, calls}`, most used first; a member gets their own, an admin all of them (the relay names the caller on every MCP request, `x-litellm-end-user-id`).
LiteLLM logs them like model requests with no tokens; they are not in `totals`, `by_target` or `rows`, and the listing of tools is left out.

## MCP servers and the MCP endpoint

An organization admin registers remote MCP servers; every member with a writer role uses their tools
(ADR 0010, `docs/superpowers/specs/2026-09-19-tools-and-mcp-design.md`). Needs the LiteLLM proxy: without it the writes and the endpoint answer 503.

| Route | Who | What |
| --- | --- | --- |
| `GET /v1alpha1/mcp/servers` | member | The organization's servers, with their tools from the last refresh. Never a credential. |
| `POST /v1alpha1/mcp/servers/discover` | writer | `{url, transport?, credential?}`: connect once, answer the tools (`name`, `description`, `read_only`). Nothing is stored. |
| `POST /v1alpha1/mcp/servers` | by `scope` | `{name, url, transport?, description?, credential?, allowed_tools?}`. 409 on a name the organization already has, 400 on a refused URL, 502 when the server or the proxy cannot be reached (nothing is left behind). |
| `PATCH /v1alpha1/mcp/servers/{id}` | who can change it | Any of `description`, `url`, `transport`, `enabled`, `allowed_tools` (or `allow_all_tools: true`), `credential`, `remove_credential: true`. |
| `POST /v1alpha1/mcp/servers/{id}/refresh` | who can change it | Connect again. A server that is down answers 200 with `status: "unreachable"` and keeps its last tool list. |
| `PUT /v1alpha1/mcp/servers/{id}/credential` | writer | `{value}`: the caller's own credential for a server of mode `per_user`. It is tried against the server first (400 when refused), stored in a Secret of the caller's own, and never returned. 409 on a server of another mode. |
| `DELETE /v1alpha1/mcp/servers/{id}/credential` | member | Removes the caller's own credential, or their OAuth tokens. |
| `POST /v1alpha1/mcp/servers/{id}/oauth/start` | writer, a browser session | Starts a sign-in at an OAuth server: answers `{authorization_url}` for the browser to open. 409 on a server of another kind. |
| `POST /v1alpha1/mcp/oauth/callback` | writer, a browser session | `{code, state}` from the UI's callback page. The state is the caller's own, not older than ten minutes and good for one use (400 otherwise); the code becomes the caller's tokens. Answers the server. |
| `DELETE /v1alpha1/mcp/servers/{id}` | who can change it | The proxy's registration first (it holds a copy of a shared credential): when the proxy refuses, 502 and everything stays. Then every Secret and the row. |

`scope` on create says who can use the server: `organization` (the default; an organization admin adds it, every member uses it),
`personal` (any member with a writer role adds it for themselves; nobody else sees it, an admin included; it goes when the member is removed)
or `platform` (a platform admin adds it; every organization uses it, none of them can change it).
A server answers with its `scope` and with `can_change` for the caller. A server the caller cannot see answers 404.
A name is unique among the shared servers a caller sees (the organization's and the platform's) and among one member's own;
a member's personal server neither blocks a name for an admin nor shows that it exists, and where a caller sees two servers of one name, `X-Mcp-Servers` means the nearer one (their own, then the organization's, then the platform's).
A personal server never has a shared credential: a `credential` on it is stored as its owner's own (`credential_mode: "per_user"`), so it travels with the owner's calls only and the proxy never holds it
(the server is in the organization's LiteLLM team, and a credential the proxy held would go out with any key of that team).
`name` is lower case letters, digits and `_` (it starts with a letter, 32 characters at most).
`approval` (`never`, the default; `writes`; `always`) is when the chat playground asks the member before a tool of the server runs:
`writes` means every tool that does not say it only reads (`read_only: true`). It is the admin's floor; a member's own "Ask before each call" adds to it.
It binds the playground, which the platform runs; a client of `/v1alpha1/mcp` (an IDE, an SDK) decides about approval itself.
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
With `oauth` on the create (`{client_id?, client_secret?, scopes?, allow_hosts?}`, and no `credential`) each member signs in at the server itself (the MCP authorization specification: OAuth 2.1 with PKCE,
the server's protected-resource and authorization-server metadata, dynamic client registration when `client_id` is absent, the `resource` parameter).
The create reads the metadata and registers the client (400 with the reason when the server publishes none or registers no clients); it cannot list tools, because nobody has a token yet:
the first member's sign-in fills the list. Such a server is `credential_mode: "per_user"` with `oauth: true`; the platform keeps each member's access and refresh token in that member's Secret,
renews the access token before it ends, and drops the tokens (`my_credential` goes back to `missing`) when the authorization server refuses the refresh token.
The authorization and the token endpoint must be on the issuer's origin, or on a host named in `allow_hosts` (400 otherwise, with the host):
metadata could else show a member the consent page of an honest authorization server and send the code to a token endpoint of somebody else.
The callback takes an optional `iss` (RFC 9207) and refuses one that is not the issuer, or a missing one where the metadata promised it. The server answers with `sign_in_host`, which the sign-in dialog shows.
Every answer of those hosts is read as a stream, at most 256 KiB and 15 s in all.
The redirect URI is `<AIOPS_UI_URL>/mcp-servers/oauth/callback`, a page of the UI: register it when you create the OAuth application by hand. Without `AIOPS_UI_URL` the create answers 400.
A `PUT .../credential` on such a server answers 409, and so does a `PATCH` of its `url`, `credential`, `credential_mode` or `remove_credential`:
the client and every member's tokens belong to that URL, so delete the server and add it again.
`refresh` on a `per_user` server uses the caller's own credential and answers 409 when they have none (an OAuth server: "Sign in to this server first"), so such a check never marks the server unreachable.
The URL must be `https` and public: loopback, private, link-local, metadata and cluster-internal addresses are refused.
A server answers with `credential_mode` (`none`, `shared` or `per_user`), `my_credential` (`not_needed`, or `set` or `missing` on a `per_user` server), `credential_header`, `credential_help_url`,
`oauth`, `status` (`connected` or `unreachable`), `checked_at`, `tools` (each with `name`, `description`, `read_only` and `size`, the characters of the whole definition with its input schema, from which Chat says how much of a model's window the tools take), and `tool_prefix`: a model sees each tool as `<tool_prefix><tool>`.

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

### Import from the MCP registry

`GET /v1alpha1/mcp/registry/search?q=&limit=` (every writer; `limit` 1 to 50, `q` at most 100 characters) searches the official MCP registry
(`AIOPS_MCP_REGISTRY_URL`, by default `https://registry.modelcontextprotocol.io`) through the backend and answers previews:
`name`, `title`, `publisher`, `version`, `suggested_name` (a valid server name), `remote` (`url`, `transport`, `auth_type`, `auth_header`) or `remote_reason`,
`deployable` or `deployable_reason`, `already_added` (a server the caller sees has that URL) and, for a platform admin, `already_imported`.
An entry only fills the add dialog: the URL rule and the connection test come after it, as for a typed URL.
A remote URL with placeholders, or more than one credential header, is "not usable yet".
Answers are cached for 60 s; a 429 of the registry is passed on with `retry-after` in the detail; an empty `AIOPS_MCP_REGISTRY_URL` turns import off (404 "Import is turned off", and `mcpRegistry: false` in `GET /v1alpha1/config/ui`).
`POST /v1alpha1/mcp/servers/oauth-probe {url}` (every writer) answers `{oauth: bool}`: whether the server offers an OAuth sign-in, asked by the add dialog after a connection test that was refused.
It reads the two metadata documents under one deadline of 5 s and never answers an error.

### Servers the platform deploys

An organization admin deploys an MCP server from a catalog; the platform runs it with Helm (`charts/mcp-server`) and makes it a server of the list above
(`source: "deployed"`, scope `organization`), so Chat, `/v1alpha1/mcp`, Langflow, the approval setting and the tool allow-list work with no change (ADR 0011).
There is no gateway host: only the LiteLLM proxy calls the pod, and the chart's NetworkPolicy admits nobody else.

| Route | Who | What |
| --- | --- | --- |
| `GET /v1alpha1/mcp/catalog` | member | The published entries: `name`, `title`, `image`, `tag`, `port`, `path`, `settings` (`name`, `label`, `help`, `secret`, `required`, `flag`, `default`), `egress`, `source`, `status`. A platform admin also gets drafts and deprecated entries. |
| `POST /v1alpha1/mcp/instances` | organization admin; platform admin for `scope: "platform"` | `{catalog, name, description?, settings, allowed_tools?, approval?, scope?}`. `scope` is `organization` (the default) or `platform` (every organization uses it; 403 for anybody but a platform admin); `personal` is a 422, because every key of the organization's team reaches a deployed server in the proxy. 404 for an entry that is not published, 422 for a setting the entry does not have, a missing required one or a line break, 409 for a taken name, 503 without the proxy, without a cluster, or when the backend does not know the proxy's pods (`AIOPS_LITELLM_NAMESPACE`, `AIOPS_LITELLM_POD_LABELS`). Answers the server (201), `status: "unreachable"`, no tools yet. |
| `GET /v1alpha1/mcp/instances/{id}` | member | The `deploy` block, the plain settings, which secret settings have a value (`secret_settings`), and the entry's `schema`. Never a secret value. |
| `PUT /v1alpha1/mcp/instances/{id}/settings` | organization admin; platform admin for a platform server | Replace the settings and roll the pod. A secret that is left out keeps its value. Also the way to repair a `Failed` server. |
| `POST /v1alpha1/mcp/instances/{id}/upgrade` | organization admin; platform admin for a platform server | Move to the catalog entry's current image, arguments and settings (`upgrade_available` says when they differ). A running server keeps a copy of what it was deployed with and never moves by itself; 409 when the entry is not published, or when its port or path changed (delete and deploy again). |
| `GET .../logs`, `GET .../events`, `POST .../restart` | logs and restart: who may change the server (organization admin, or platform admin for a platform server); events: who sees it | See "Logs and events" and "Day-2 actions". The logs are for an admin only (403 for a member): an MCP server can log the arguments of the calls it gets, so a member could read there what another member asked. |
| `DELETE /v1alpha1/mcp/servers/{id}` | organization admin | The proxy's registration first (502 and everything stays when it refuses), then the release and the Secret, then the rows. When the uninstall fails (500) the server stays, disabled and unknown to the proxy; a second delete finishes. A `Failed` server is always deletable. |

A deployed server carries `deploy` in the list: `instance_id`, `catalog`, `image`, `tag`, `status` (`Pending`, `Running`, `Failed`), `ready`, `launch`, `last_error`, `upgrade_available` and `usable`.
`usable` is the one answer to "does it take requests": its pod serves, the proxy knows it, and the last connection test worked.
The platform registers the server in the proxy when its pod is first ready and lists its tools then; until then, and whenever the pod does not serve,
the server is left out of `/v1alpha1/mcp` (a request that names it answers 409), because one registered server that is down adds seconds to every `tools/list` of the proxy.
A `PATCH` of `url`, `transport`, `credential`, `credential_mode` or `remove_credential` answers 409, and `refresh` answers 409 while the pod does not serve.
A setting is an environment variable of the pod, or, with `flag`, a switch that adds one argument; names come from the catalog entry only.
The pod gets no service-account token, no root, no capability and a read-only file system. `egress` of the entry says what it may call:
`none`, `public` (port 443 outside the private ranges) or `cluster` (also every private address, for a Grafana or a database of the cluster or the site); never the link-local range.

The catalog, for a platform admin: `POST /v1alpha1/mcp/catalog/import {name, version?, slug?}` imports an image entry of the MCP registry as a `draft` with `egress: "public"`
(422 with the reason for a stdio package, an image without a registry host or with the tag `latest`, docker run options, or a header the server checks itself;
409 "imported already", and another 409 when the catalog name is taken: send `slug`);
`GET`, `PATCH` (`title`, `description`, `args`, `port`, `path`, `settings`, `egress`, `status`, and `name` while it is a draft) and `DELETE /v1alpha1/mcp/catalog/{id}` (409 while a server uses it);
`POST .../sync` reads the source again, and when that changes what runs (`image`, `tag`, `args`, `port`, `path`, `settings`) the entry goes back to `draft`: what was reviewed is what runs.
Only a platform admin sees a draft, unlike the model registry, because a draft is an image nobody has read.

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
