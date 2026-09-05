# Monitoring on the local stack

`make monitoring-up` installs kube-prometheus-stack (Prometheus, the operator, kube-state-metrics, Grafana; no alertmanager, no node exporter)
in namespace `monitoring`, publishes Grafana at `https://grafana.127.0.0.1.nip.io` through the gateway,
scrapes LiteLLM's `/metrics/` with a `ServiceMonitor` that carries the master key,
and installs `charts/infracloud-dashboards` (the TGI, TEI, vLLM, DCGM and LiteLLM dashboards) for the Grafana sidecar.

Grafana is dev-only here: anonymous viewers, embedding allowed, no gateway policy, admin password `admin`.
The UI embeds panels when `NEXT_PUBLIC_GRAFANA_URL` is set (`make frontend` sets it);
the browser must trust the local CA (`make trust-ca`) for the frames to load.

```bash
curl --cacert infra/local/ca/ca.crt https://grafana.127.0.0.1.nip.io/api/health
kubectl -n monitoring port-forward svc/monitoring-kube-prometheus-prometheus 9090   # then http://localhost:9090/targets
```

`make monitoring-down` removes both releases and the route.
