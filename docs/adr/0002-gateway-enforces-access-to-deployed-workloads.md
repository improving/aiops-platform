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
Amended 2026-09-07:
the shared policy is per namespace (the umbrella chart renders one in its release namespace),
`add_oidc_target` patches the policy of the route's own namespace
(and builds it from scratch only where the `sso` callback route exists, since nothing else could complete a login),
and a browser route that cannot join it is deleted again and the launch fails,
so no route is ever left unprotected.

Amended again 2026-09-07 (#27): the SDK routes follow the same rule.
`vdb-<id8>-api` and `inf-<id8>` are created and given their API-key policy as one strict unit
(`protect_sdk_route`, the twin of `protect_browser_route`),
and a route that cannot get its policy is deleted again and the launch fails.
They were best effort until now, on the reasoning that the workload also checks the key,
which holds for only three of them:
Qdrant, Milvus and vLLM check it themselves,
while ChromaDB is enforced by the gateway alone
and the TGI/TEI, NIM, OPEA and Ollama inference engines check nothing.
A missing credential Secret counts as a failure rather than a reason to skip the policy,
since both create endpoints store the credential before they install.
`GatewayPolicyError` is the shared base of both failures,
so neither is ever relabelled as a Helm failure.

Each route is created and protected as a pair, in turn,
rather than both routes being created and then both protected:
the second form leaves a published host unprotected for as long as the first pair takes,
and strands it if that step fails.
A failure therefore never needs a sweep of the other route,
and must not do one: on an upgrade the instance keeps running,
so tearing down a dashboard that is protected and fine,
because the SDK route failed, would be a self-inflicted outage.

The same reasoning bounds the removal itself.
A route is deleted only when it is actually unprotected:
if the policy already lists the route, the attach failure is reported but the route stays up,
because on every upgrade after the first the route and its policy already exist,
and an apiserver blip re-confirming them must not take a running workload off the air.

What a failed attach cannot do is record itself on the row.
Marking the instance `Failed` does not survive:
the workload is healthy, since Helm succeeded before the gateway step,
so the 5 s poller sees Ready pods and writes `Running` back within one tick.
An upgrade that loses its route therefore reports a 500 and logs the reason,
while the row still reads Running with an endpoint that no longer resolves.
Fixing that needs a status that is not derived purely from the pods, which is left as follow-up work.

One consequence is deliberate and one-way.
An instance whose credential Secret is absent
(created before per-instance credentials existed)
now fails its next upgrade, scale, stop or resume, and loses its SDK route,
where it previously logged and carried on.
That route was serving with nothing checking the key,
so the failure makes an existing exposure visible rather than creating a new one.
The fix for such a row is to delete and relaunch it.

Amended 2026-09-07 (#30): Langflow is decided by the control plane too.
It keeps a `SecurityPolicy` of its own rather than joining the shared one,
because its host is also its callback host,
which is exactly the constraint that forced one shared policy on the instance routes
and does not apply to a policy whose own route is the callback.
What it lacked was `extAuth`:
the OIDC block alone proves only that the realm authenticated somebody,
the backend never saw the request, and nothing was logged,
so "Gateway OIDC, any member" was written down but never enforced.
It now calls `GET /v1alpha1/authz/route` like every instance route.
There is no row to own, so the rule is that any signed-in member may open it,
and script identities may not:
a personal token and a client-credentials service account both belong to callers of the API,
and neither should open a browser application.
The value is that the decision belongs to the platform, is attributable in the log,
and now has one place to narrow when a tighter rule is wanted.
