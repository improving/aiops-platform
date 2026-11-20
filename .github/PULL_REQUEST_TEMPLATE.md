## What and why

<!-- What changes, and the reason for it. Link the issue it closes. -->

Closes #

## How it was tested

<!-- The commands you ran, and what they showed. -->

- [ ] `cd backend && ./hack/runtest.sh`
- [ ] `cd backend && ./hack/lint.sh`
- [ ] `cd frontend && pnpm lint && pnpm build`
- [ ] `make chart-lint`

## Checklist

- [ ] One logical change, and the commits say why
- [ ] A chart change bumps `version` in its `Chart.yaml`
- [ ] Snapshots under `backend/snapshots/` are regenerated only for an intended change
- [ ] No credential, token or private address is added
- [ ] Markdown uses semantic line breaks
