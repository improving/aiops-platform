---
status: accepted
date: 2026-09-04
---

# A Gateway API gateway enforces access to every deployed workload

Notebooks, Langflow, Jaeger, vector databases and inference endpoints have no usable authentication of their own
and must not be patched one by one.
Every deployed workload gets a hostname under one parent domain and an `HTTPRoute` behind Envoy Gateway,
whose `SecurityPolicy` first performs OIDC login against the `aiops` realm and then asks the control plane's
authorization endpoint whether this user may open this host; the workload only ever sees identity headers.
The control plane UI and API authenticate at the application level instead (OIDC in the app, JWT on the API),
so local development runs without the gateway.

## Considered options

- oauth2-proxy per hostname with `auth-url` on an ingress controller: proven, but one instance and cookie secret per host,
  no per-resource policy, and the usual controller, ingress-nginx, was retired in March 2026 and is not deployed on the lab.
- Istio `RequestAuthentication` plus CUSTOM ext-authz: the lab's Istio is owned by the Kubeflow distribution,
  and CUSTOM policies cannot read JWT claims without a second policy layer.
- Gateway-level OIDC for the UI as well: one mechanism everywhere, but no login when the UI runs on a host port,
  and no access token in the UI for direct API calls.

## Consequences

- Phase 0 work is unavoidable: stable hostnames, cert-manager, ClusterIP defaults in the value templates,
  and endpoints stored as URLs instead of `http://<ip>:<port>`.
- Controllers create an `HTTPRoute` for every instance; deleting the instance deletes the route.
- The authorization endpoint becomes part of the request path for every workload page load; it must be fast and cache ownership lookups.
- WebSocket behaviour of the ext-authz step, inferred from Envoy's design,
  was verified with a Jupyter kernel in Phase 2:
  a session stayed connected for eleven minutes through the gateway with no reconnect
  (gateway notes, "Spike results").

## Implementation notes

Every browser route shares one `SecurityPolicy`, `aiops-workloads-oidc`,
with `targetRefs` the controllers patch per instance, rather than one policy per instance as first designed.
Two facts found during implementation forced this:
Keycloak 26.7 does not glob-match a `*` placed before a literal path in a redirect URI,
so a distinct `redirectURL` per instance host cannot be registered on one client;
and Envoy Gateway derives its OIDC cookie names from the policy's identity,
so only the policy that started a login can complete it,
which rules out several per-instance policies sharing one callback host too.
Every login instead completes on one shared callback host, `sso.<parent domain>`,
registered as the client's only redirect URI, with cookies set for the whole parent domain
so one login covers every instance
(gateway notes, "Spike results"; `infra/local/auth/README.md`, "Redirect URIs and the shared OIDC policy").
A consequence not in the original design:
a browser route in any namespace other than the one holding the `sso` callback host is left unprotected,
with a warning logged, until that namespace gets a callback host of its own.
