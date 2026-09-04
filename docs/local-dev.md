# Local dev stack

Runs the aiops-platform control plane (`backend/`) against a real local
Kubernetes cluster, so `backend/api/vectordb_instance.py` and
`backend/api/notebooks.py` actually install Helm charts and reconcile
`kind: Notebook` custom resources -- not mocks.

## Prerequisites

- macOS with [colima](https://github.com/abiosoft/colima) (Docker runtime).
- [kind](https://kind.sigs.k8s.io/), [Helm](https://helm.sh/) 3+,
  [kubectl](https://kubernetes.io/docs/tasks/tools/), [uv](https://docs.astral.sh/uv/),
  [pnpm](https://pnpm.io/), `docker` CLI with the `compose` plugin.
- `gh` (only needed if you re-pin the notebook-controller tag or kind node image).

Run `make prereqs` to check what's installed.
Anything missing can be installed with `brew install <name>` --
this stack does not install machine-wide tools for you (other than the one
colima sysctl tweak in `make kind-up`, see below).

## Bring the stack up

```
colima start                     # if not already running; ~4 CPU / 8 GiB is enough
make kind-up                     # kind cluster "aiops" + notebook-controller + ns "ai-stack"
make db-up                       # postgres:17-alpine on :5432
make backend                     # separate terminal: FastAPI on :8000
make frontend                    # separate terminal, optional: Next.js on :3000
make e2e-smoke                   # exercises the backend API end to end
```

`make dev` prints this same sequence.

Tear down with `make db-down` and `make kind-down`
(stop the `backend`/`frontend` processes yourself, e.g. Ctrl-C or
`pkill -f "uvicorn app:app"`).

## What `make kind-up` does

1. Creates a one-node kind cluster named `aiops`
   (`infra/local/kind-config.yaml`, node image pinned to the kind v0.32.0 default).
2. Switches `kubectl`'s current context to `kind-aiops`.
3. Creates namespace `ai-stack` (idempotent).
4. Raises `fs.inotify.max_user_instances` inside the colima VM
   (see "colima inotify limit" below).
5. Installs the standalone Kubeflow notebook-controller
   (see `infra/local/notebook-controller.md` for the exact source and why).

All of this is idempotent -- re-running `make kind-up` against an existing
cluster is safe and is how you recover after `colima stop`/`colima start`.

## What LoadBalancer support adds

By default, kind Services of type `LoadBalancer` stay `Pending` forever --
kind does not ship a cloud-controller-manager.
The backend's `get_service_endpoint()`
(`backend/utils/kubernetes_utils.py`) falls back to the Service's
`ClusterIP` when there is no `LoadBalancer` ingress IP, so the stack works
without one; `hack/e2e-smoke.sh` deliberately requests `ClusterIP` via
`configParams.serviceType` / `service_type` so it never depends on a
LoadBalancer IP existing.

If you want real `LoadBalancer` IPs locally (e.g. to match how the platform
behaves in a real cluster), install and run
[cloud-provider-kind](https://github.com/kubernetes-sigs/cloud-provider-kind).
It needs a privileged process on the host, so this Makefile will not run it
for you -- `make lb` prints the exact command:

```
brew install cloud-provider-kind
DOCKER_HOST=unix://$HOME/.colima/default/docker.sock sudo cloud-provider-kind
```

Leave that running in its own terminal while you use the stack.

## Troubleshooting

### colima not running

`colima status` reports `colima is not running`.
Run `colima start`. `make kind-up` and `make prereqs` both check for this
and warn, but do not start it for you.

### colima inotify limit / notebook-controller crash-loops

Symptom: `kubectl -n notebook-controller-system logs deploy/notebook-controller-deployment`
shows `failed to create fsnotify watcher: too many open files` and the pod
restarts repeatedly.

Cause: the default colima Lima VM ships `fs.inotify.max_user_instances=128`,
which kubelet + containerd + the controller-runtime manager exhaust between
them. `make kind-up` raises it to 8192 every time it runs, but the setting
does not persist across `colima stop`/`colima start` -- just re-run
`make kind-up` (it is idempotent, including this step).

### Image pulls are slow

The Jupyter notebook images (`kubeflownotebookswg/jupyter-*-full`) are
several GB. First pull inside the kind node can take minutes depending on
your network. Accelerate it by pre-pulling on the host and loading it
straight into the kind node's containerd, skipping the pull entirely for
that image:

```
docker pull kubeflownotebookswg/jupyter-pytorch-full:v1.9.2
kind load docker-image kubeflownotebookswg/jupyter-pytorch-full:v1.9.2 --name aiops
```

(If `kind load docker-image` errors with a content-digest mismatch on a
multi-arch image, it's a known kind/containerd quirk with `--all-platforms`
import -- the pod will still pull the image directly from the registry via
containerd inside the node, which works, just without the local-load
shortcut.)

### Notebook instances stay Pending forever ("Insufficient nvidia.com/gpu")

`hack/e2e-smoke.sh` defaults to `--skip-notebook`-free runs, but on a kind
cluster without a GPU device plugin the notebook step currently cannot pass.

Root cause (confirmed by running it end to end): the `kf-notebooks` chart's
own `values.yaml` default sets
`notebooks.jupyter.resources.limits."nvidia.com/gpu": "1"` unconditionally.
`backend/templates/kf-notebooks-values.yaml.jinja` only *adds* that key when
`nvidia_gpu` is true (`{% if nvidia_gpu %}`);
it never emits an explicit override to remove/null it when `nvidia_gpu` is
false.
Helm merges supplied values on top of chart defaults without deleting keys
the caller omitted, so a `POST /v1alpha1/notebooks` with
`"nvidia_gpu": false` still produces a Notebook CR whose pod requests
`nvidia.com/gpu: "1"`, e.g.:

```
$ kubectl -n ai-stack get notebook <name> -o yaml
  ...
  resources:
    limits:
      cpu: "0.5"
      memory: 1Gi
      nvidia.com/gpu: "1"      # <- present despite nvidia_gpu: false
    requests:
      cpu: "0.5"
      memory: 1Gi

$ kubectl -n ai-stack describe pod <name>-0
Events:
  Warning  FailedScheduling  0/1 nodes are available: 1 Insufficient nvidia.com/gpu.
```

This is a `backend/` + chart-template gap, not something this worktree can
fix (`backend/` is owned by another worktree/agent).
Until it's fixed, notebook creation only succeeds on a cluster with a GPU
(or a fake GPU device plugin).
Run the smoke test with `make e2e-smoke ARGS="--skip-notebook"`
or `BACKEND_URL=... ./hack/e2e-smoke.sh --skip-notebook` on a GPU-less
cluster like this one.

### Notebook CRD missing

Symptom: creating a notebook instance 500s with a Helm error mentioning
`Notebook CRD is not installed in the cluster`.
Run `make kind-up` again -- it installs the CRD as part of the
notebook-controller install -- and confirm with:

```
kubectl get crd notebooks.kubeflow.org
```

### Seeing what's actually running

```
helm -n ai-stack list                       # Helm releases the backend created
kubectl -n ai-stack get pods,svc,notebooks  # workloads + the Notebook CRs
kubectl -n notebook-controller-system get pods,deploy
```

### Helm installs take minutes the first time

The first `POST /v1alpha1/vectordb_instances` or `/v1alpha1/notebooks` in a
fresh session takes 2-3 minutes even though the pod itself starts in
seconds -- `backend/controller/vectordb_controller.py` and
`notebooks_controller.py` call `helm.get_chart(..., repo=...)` /
`install_or_upgrade_release(...)` with a bare `--repo` URL rather than a
named local repo, so Helm re-fetches the repo index over the network on
every install.
Once Helm's local chart cache is warm (after the first install of a given
chart+version), subsequent installs are fast (seconds, confirmed by
re-running `hack/e2e-smoke.sh`: 176s cold vs. 25s warm for the same Qdrant
install).
This is expected Helm/pyhelm3 behavior, not a bug --
just budget for it the first time you run the stack.

## Known backend findings from running this end to end

These are observations about `backend/` behavior discovered while building
and running this stack, not something this worktree is allowed to fix
(backend/ is owned by another worktree) -- see the task report for the
authoritative list with file:line references. The GPU-scheduling issue
above is the one that actually blocks `hack/e2e-smoke.sh`'s notebook step
on a GPU-less cluster; the others are non-blocking but worth fixing
upstream.
