---
status: proposed
date: 2026-09-05
---

# LiteLLM proxy is the single provider layer for chat

Chat must reach models the platform deploys and hosted APIs (OpenAI, Anthropic, Gemini, Groq, OpenRouter) through one interface,
with provider keys kept away from the browser and spend visible per organization.
We run the LiteLLM proxy (MIT core) in the cluster; the control plane registers every chat target in it
(local instances with their in-cluster URL and workload credential, hosted models with the provider key),
issues one virtual key per organization, and exposes its own `POST /v1alpha1/chat/completions` that authorizes the caller
and streams from LiteLLM.

## Considered options

- A thin adapter inside the backend: OpenAI passthrough plus translators for Anthropic and Gemini. Fewer parts,
  but retries, provider quirks, cost tracking and new providers become our code.
- Envoy AI Gateway: provider translation plus token-based rate limiting at the gateway, but a second gateway to operate
  and its compatibility with the installed Envoy Gateway is unverified; revisit for the lab.

## Consequences

- One more component with a Postgres schema (keys and spend) next to the platform database.
- The browser only ever talks to the platform API; LiteLLM and provider keys are cluster-internal.
- Phase 1 may pass through to Ollama directly with the same API shape; the endpoint does not change when LiteLLM arrives.
