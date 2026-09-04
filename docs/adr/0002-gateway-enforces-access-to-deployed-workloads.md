---
status: proposed
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
  no per-resource policy, and ingress-nginx, the Kubespray default, was retired in March 2026.
- Istio `RequestAuthentication` plus CUSTOM ext-authz: the lab's Istio is owned by the Kubeflow distribution,
  and CUSTOM policies cannot read JWT claims without a second policy layer.
- Gateway-level OIDC for the UI as well: one mechanism everywhere, but no login when the UI runs on a host port,
  and no access token in the UI for direct API calls.

## Consequences

- Phase 0 work is unavoidable: stable hostnames, cert-manager, ClusterIP defaults in the value templates,
  and endpoints stored as URLs instead of `http://<ip>:<port>`.
- Controllers create an `HTTPRoute` for every instance; deleting the instance deletes the route.
- The authorization endpoint becomes part of the request path for every workload page load; it must be fast and cache ownership lookups.
- WebSocket behaviour of the ext-authz step is inferred from Envoy's design and must be verified with a Jupyter kernel in Phase 2.
