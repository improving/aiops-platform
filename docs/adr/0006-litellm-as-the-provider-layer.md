---
status: accepted
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

## Consequences observed (2026-09-05, Phase 2a on kind)

- The open-source proxy image (v1.99.1) serves Prometheus metrics at `/metrics/` labelled by key alias, team and model,
  so per-organization usage needs no enterprise licence.
- Inside the cluster LiteLLM calls the instance Service directly and bypasses the gateway's API-key policy;
  the workload credential travels as a bearer, which vLLM validates and Ollama, TGI and TEI ignore.
- The arm64 kind node cannot run the amd64-only TEI image, so TEI embeddings and rerank are proven on the lab;
  on kind the embeddings proof uses an Ollama embedding model.
- NVIDIA NIM's reranker is not Cohere-style and has no LiteLLM route yet; OPEA guardrails are not chat targets.
- Hosted providers are rows per organization with the key in a Secret; LiteLLM keeps a copy encrypted with the salt,
  which is why the salt Secret of `make litellm-up` is created once and never rotated.
