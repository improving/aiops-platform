---
status: proposed
date: 2026-09-19
---

# MCP servers are registered per organization and reached through one platform endpoint

Models need tools, and the Model Context Protocol (MCP) is how tools are supplied:
to the chat playground, to Langflow flows, and to IDE and SDK clients.
Organization admins register remote MCP servers in the control plane (the hosted-provider pattern: a row per organization, the credential in a Secret);
the control plane registers each server in the LiteLLM proxy's MCP gateway and scopes it to the organization's LiteLLM team.
Every client reaches the tools through one endpoint, `/v1alpha1/mcp` on the platform API,
which authenticates the caller (session or personal token), applies the role and organization rules,
resolves the credential for that caller, and relays to LiteLLM `/mcp` with the organization key.
LiteLLM `/mcp` is cluster-internal, as its model endpoints already are (ADR 0006).
The tool loop of the chat playground runs in the UI's route handler with the Vercel AI SDK, which is an MCP client of that endpoint.

## Considered options

- The tool loop in the backend (`chat.py` with the Python MCP SDK).
  The answer then has several assistant steps and is no longer an OpenAI chat-completions stream, which the UI's provider adapter reads.
- The tool loop inside LiteLLM (`type: "mcp"` tools with `require_approval: "never"`).
  The steps are hidden from the UI, and it depends on LiteLLM translating that contract for vLLM and Ollama.
- Clients talk to LiteLLM `/mcp` directly with per-user virtual keys.
  Less code, but the viewer rule, the server selection and a member's own credential would each need a LiteLLM feature;
  with one platform endpoint they are our code in one place.
- MCP servers written into the LiteLLM Helm values. Static, per cluster and not per organization (same argument as the guardrails assessment of 2026-09-07).

## Consequences

- The credential is resolved per request and per user behind one interface.
  The first version has an organization credential; a member's own token (for example a GitHub token) and OAuth are later modes of the same interface,
  stored in a separate `mcp_credentials` table so they are additive.
- A new personal-token scope, `mcp`, is valid only on `/v1alpha1/mcp`.
  Langflow gets such a token at provision time, so a flow never holds a token that can change platform resources.
- The platform API route needs the stream timeouts that the inference routes already have; Envoy's 15 s default cuts an MCP session.
- Admin-supplied URLs are an SSRF surface: `https` only, and private, loopback, link-local and cluster-internal addresses are refused.
  Cluster-deployed MCP servers are a later workload kind with their own gateway policy.
- The design depends on the MCP API of the pinned LiteLLM (v1.99.1), which is measured before the registry is built.
  If registration or team scoping is missing, the endpoint connects to one selected server directly; the public contract stays the same.

## Consequences observed (2026-09-19, LiteLLM v1.99.1 on kind)

- The proxy has the whole surface the design needs: `/v1/mcp/server` for registration (not listed in its OpenAPI document),
  `object_permission.mcp_servers` on a team for scope, `/mcp` over streamable HTTP with sessions, `x-mcp-servers` to select servers,
  and `/mcp-rest/test/tools/list` to list the tools of a server that is not saved yet. The direct-connection fallback is not necessary.
- Tool names reach the model as `<alias>-<tool>`, so the alias must be unique across organizations and short.
- Forwarding a member's own credential through the proxy is not measured yet; it decides only how Phase 5 reaches the upstream server.
