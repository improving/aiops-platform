# Local Gateway and TLS

Manifests applied by `make gateway-up` (see the repository `Makefile`).
Together they give the kind stack one Gateway,
`aiops` in `envoy-gateway-system`,
that terminates TLS for `*.127.0.0.1.nip.io` and is reachable on the Mac at
`http://*.127.0.0.1.nip.io/` and `https://*.127.0.0.1.nip.io/` through the
NodePort mapping in `infra/local/kind-config.yaml` (30080 to host 80,
30443 to host 443).

## Files

- `envoyproxy.yaml` -- `EnvoyProxy` `aiops-kind`.
  Pins the managed Envoy Service to NodePort 30080/30443 via a
  StrategicMerge `patch` (Envoy Gateway has no direct `nodePorts` field),
  sets `externalTrafficPolicy: Cluster`,
  and reorders the OIDC filter (`envoy.filters.http.oauth2`) ahead of
  `envoy.filters.http.ext_authz` -- the default chain runs ext-authz first,
  which would see no bearer token on a user's first request.
- `gatewayclass.yaml` -- `GatewayClass` `aiops`, pointing at the `EnvoyProxy`
  above via `parametersRef`.
- `gateway.yaml` -- `Gateway` `aiops` with an `http` (80) and an `https`
  (443, `tls.mode: Terminate`) listener for `*.127.0.0.1.nip.io`,
  `allowedRoutes.namespaces.from: All` so any namespace can attach an
  `HTTPRoute`.
- `cert-manager-ca.yaml` -- a self-signed local CA (`ClusterIssuer`
  `aiops-selfsigned` to `Certificate` `aiops-ca`, secret `aiops-ca` in
  namespace `cert-manager`) and a CA-backed `ClusterIssuer` `aiops-ca` that
  signs `Certificate` `aiops-wildcard` (secret `aiops-wildcard-tls` in
  `envoy-gateway-system`), which the Gateway's `https` listener uses.
- `backend-host-service.yaml` -- the ext-authz backend: a selector-less
  Service `aiops-backend` in `ai-stack` plus an `EndpointSlice` whose
  address `make gateway-up` substitutes for `__HOST_IP__`
  (`docker exec aiops-control-plane getent hosts host.docker.internal`,
  or `make gateway-up HOST_IP=...`), and the `ReferenceGrant` that lets
  `SecurityPolicy`s from other namespaces reference it.
- `sso.yaml` -- the shared OIDC callback host `sso.127.0.0.1.nip.io`:
  a tiny nginx Deployment/Service and its `HTTPRoute`, the first target of
  the shared `SecurityPolicy` in `infra/local/auth/workloads-oidc-policy.yaml`.
  See `docs/local-dev.md` section "Workload access" for why one callback
  host and one policy.

## Why explicit `Certificate` resources, not the Gateway annotation

cert-manager 1.15+ can auto-provision a per-listener `Certificate` from a
`cert-manager.io/cluster-issuer` annotation on the `Gateway`.
This stack uses one fixed wildcard host instead: auto-provisioning buys
nothing here, and an explicit, versioned `Certificate` is easier to read
and debug.

## Trusting the CA

`make ca-export` writes the CA certificate to `infra/local/ca/ca.crt`
(git-ignored -- it is a local, throwaway CA, but keeping generated material
out of version control is the norm here regardless).
`make trust-ca` prints, but does not run, the macOS command to trust it
system-wide.
See `docs/local-dev.md` section "Gateway and TLS" for the full sequence
and the environment variables that point tooling (curl, Node, Python) at
the CA without a system-wide trust change.

## Recreating the CA

`aiops-ca` and `aiops-wildcard-tls` are not deleted by `make gateway-down`
-- only the `Certificate`/`ClusterIssuer` objects that produced them are.
This means the CA (and anything that trusted it) survives a
`gateway-down` followed by `gateway-up`, so you don't need to re-run
`make trust-ca` after a routine reset.
Delete the `aiops-ca` secret in `cert-manager` and the `aiops-wildcard-tls`
secret in `envoy-gateway-system` yourself if you need a fresh CA.
