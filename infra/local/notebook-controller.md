> Notebook controller source and install command for local dev.
> Applied by `make kind-up` (see the root `Makefile`).

## What this installs

The `kf-notebooks` Helm chart (used by `backend/controller/notebooks_controller.py`)
creates `kind: Notebook` (`kubeflow.org/v1`) custom resources.
Reconciling those requires the standalone Kubeflow notebook-controller —
the CRD plus the controller deployment, not the full Kubeflow platform.

## Source used

```
kubectl apply -k "github.com/kubeflow/notebooks/components/notebook-controller/config/overlays/standalone?ref=v1.11.0"
```

This is the **preferred** path from the task brief, and it works: verified with

```
gh api "repos/kubeflow/notebooks/contents/components/notebook-controller/config/overlays/standalone?ref=v1.11.0"
```

which returns the overlay's `kustomization.yaml` at that tag.
The kubeflow/manifests fallback path was not needed.

Tag `v1.11.0` was chosen because it is the latest stable release tag on
`kubeflow/notebooks` at the time this was written
(`gh api repos/kubeflow/notebooks/tags` — `v2.0.0-*` are pre-release alphas/betas,
skipped in favor of the latest stable `v1.x`).

The overlay creates namespace `notebook-controller-system` and a Deployment named
`notebook-controller-deployment`.
It installs:

- CRD `notebooks.kubeflow.org` (versions `v1`, `v1alpha1`, `v1beta1`)
- ServiceAccount, Role/RoleBinding, ClusterRole/ClusterRoleBinding
- ConfigMap `notebook-controller-config-*`
- Service `notebook-controller-service`
- Deployment `notebook-controller-deployment`

Image: `ghcr.io/kubeflow/notebooks/notebook-controller:v1.11.0` — confirmed
multi-arch (`amd64`, `arm64`, `ppc64le`) via
`docker manifest inspect ghcr.io/kubeflow/notebooks/notebook-controller:v1.11.0`,
so it runs natively on Apple Silicon under colima.

## Waiting for it to be ready

```
kubectl -n notebook-controller-system wait --for=condition=Available \
  deployment/notebook-controller-deployment --timeout=180s
```

## Known local-machine gotcha: fsnotify / inotify limits

On a fresh colima VM the manager container crash-loops with:

```
failed to create fsnotify watcher: too many open files
```

This is the colima Linux VM's `fs.inotify.max_user_instances` default (128),
not a cluster or chart problem — the controller-runtime manager watches many
resources and exhausts it quickly alongside kubelet/containerd's own watchers.
Fixed once, for the life of the colima VM, with:

```
colima ssh -- sudo sysctl -w fs.inotify.max_user_instances=8192
colima ssh -- sudo sysctl -w fs.inotify.max_user_watches=1048576
```

`make kind-up` runs this automatically before applying the controller.
The setting does not persist across a `colima stop`/`colima start` — re-run
`make kind-up` (idempotent) after restarting colima and it will re-apply it.

## Verifying

```
kubectl -n notebook-controller-system get deploy,pods
kubectl get crd notebooks.kubeflow.org
```
