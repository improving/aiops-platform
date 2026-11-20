---
status: accepted
date: 2026-09-20
---

# The platform deploys MCP servers behind a policy that admits only the proxy

Many useful MCP servers have no hosted endpoint: a team runs them next to the system they read (a Grafana, a database).
An organization admin deploys one from a catalog (a platform admin also for every organization), and the platform runs it with Helm (`charts/mcp-server`).
A deployed server is a row of the MCP registry (`source = "deployed"`, ADR 0010) plus a workload row,
so Chat, the one endpoint `/v1alpha1/mcp`, Langflow, usage, approval and the tool allow-list work with no change.
It has no gateway host: only the LiteLLM proxy calls the pod, through the in-cluster Service,
and a NetworkPolicy in the chart admits the proxy's pods and nobody else.
The proxy registration happens when the pod is first ready, in a poller, with the registry row's id as the proxy's `server_id`.
Another image enters the catalog only through import from the official MCP registry, as a draft that a platform admin reads and publishes.

## Considered options

- A gateway host for each server (`mcp-<id8>`, an ext-authz rule, a traffic policy), like the other workload kinds.
  It would be a second door next to `/v1alpha1/mcp`, with a policy shape of its own, and nobody needs it.
- A bearer that the pod checks, written to the proxy as `static_headers`.
  Most MCP server images check no credential of their own (measured: `mcp/grafana` has no such option), so the NetworkPolicy is the control that always works; the bearer stays possible for an entry that supports it.
- Registration at create. The pod does not exist then, so the connection test fails, and a registered server that is down costs every request time
  (measured: `tools/list` with one of two servers down answers after 12.4 s, not 3.2 s).
- A free-text image field. An image an admin names is code that runs in the cluster; a catalog that somebody read and pinned is the safe default, and import with a review step covers the rest.
- A stdio image behind an adapter. One more image to pin and to trust; it is a later catalog attribute, and the chart does not change when it comes.

## Consequences

- The backend must know the proxy's pods (`AIOPS_LITELLM_NAMESPACE`, `AIOPS_LITELLM_POD_LABELS`) and refuses to deploy without them; its ClusterRole may create NetworkPolicies.
  The ingress rule is one element with both selectors: two elements would admit every pod of the proxy's namespace, which on a chart install holds the backend and the database.
- A `Running` workload row is never read again by the shared status code, so the poller reads the pods of every MCP instance on every tick and stores `ready`;
  a server whose pod does not serve is left out of every request's selection.
- An entry with `egress: "cluster"` reaches every private address: the platform's own pods and other organizations' workloads that check no credential.
  Accepted for version 1: it is stricter than every other workload kind (none has a NetworkPolicy, and a notebook runs the user's own code), the image is the catalog's, and the pod has no identity in the cluster. An entry that names its targets is the refinement.
- What was reviewed is what runs: an image is pinned (never `latest`), a sync that changes what runs sends a published entry back to draft, and a running server moves to a new image only when an admin says so.
- Organization or platform scope, never one member's (every key of the organization's team reaches every server of the team in the proxy, and a deployed server has no credential of its own), and one pod for each server: an MCP server can keep sessions in memory, so replicas are not a number to turn up.
