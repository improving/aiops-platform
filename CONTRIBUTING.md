# Contributing

Thanks for taking the time to contribute.
This document covers how to get a development stack running, what to check
before you open a pull request, and the conventions this repository holds to.

## Before you start

- For a bug, open an issue with the steps to reproduce and what you expected.
- For anything larger than a small fix, open an issue first so we can agree on
  the approach before you write code.
- Security problems go to [SECURITY.md](SECURITY.md), never to a public issue.

## Getting a stack running

Prerequisites: colima (or another Docker daemon), kind, Helm, kubectl, uv and pnpm.
`make prereqs` reports what is missing.

```bash
colima start --cpu 4 --memory 8
make kind-up gateway-up ca-export auth-up db-up langflow-up
make backend     # terminal 1: API on http://localhost:8000
make frontend    # terminal 2: UI on http://localhost:3000
make e2e-smoke   # terminal 3: creates a Qdrant instance and a notebook, then deletes them
```

The UI signs users in through Keycloak with the development users
`alice`/`alice`, `bob`/`bob` and `admin`/`admin`.
curl, Node and Python need to trust the gateway's local CA:
run `make trust-ca` for the command, or point `SSL_CERT_FILE` and
`NODE_EXTRA_CA_CERTS` at `infra/local/ca/ca.crt` for one shell.
`docs/local-dev.md` has the full walkthrough and the troubleshooting.

## Checks to run

Run what your change touches.
All of these run in CI, so a green local run is the fastest path to a merged
pull request.

```bash
# backend
cd backend
uv sync --group dev
./hack/runtest.sh        # all tests, TEST_MODE=true
./hack/lint.sh           # ruff check + format --check
./hack/format.sh         # ruff format
./hack/sort-imports.sh   # ruff check --select I --fix

# frontend
cd frontend
pnpm install --frozen-lockfile
pnpm lint
pnpm build
pnpm e2e                 # Playwright fast tier, no cluster

# charts
make chart-lint          # lint and render every fixture, with assertions
```

`docs/testing.md` explains the two end-to-end tiers and how to add a scenario.

## Conventions

- **Markdown uses semantic line breaks**: one sentence or clause per line.
  Rendered output is unchanged, and every diff shows one thought per line.
- **Backend** uses `uv` for everything and `ruff` for lint and format.
  Schema changes are Alembic migrations under `backend/alembic/versions/`,
  never edits to the baseline and never `create_all`.
  `backend/snapshots/` holds golden output: regenerate it with
  `./hack/runtest.sh -u` only when the change to the output is intended, and
  read the diff before you commit it.
- **Frontend** uses `pnpm` only; the version is pinned in `packageManager`.
  `next dev` writes a managed block into `frontend/AGENTS.md`; keep it.
- **Charts** bump `version` in `Chart.yaml` whenever templates or `appVersion`
  change. Umbrella charts depend on their siblings with `file://` references,
  so a sibling bump needs the pin and the `Chart.lock` updated too.
- **Never commit a credential.** Secrets live in a git-ignored `config.yaml`
  copied from `backend/manifests/config.example.yaml`, or in a Kubernetes
  Secret. `.env` files, `infra/local/ca/` and
  `frontend/playwright/.auth/` are git-ignored on purpose.
- **`AUTH_MODE=disabled` is a security bypass**, not a convenience flag.
  The backend refuses it unless `TEST_MODE=true` is also set, and it must never
  be set that way anywhere a real stack runs.

## Commits and pull requests

- Keep each commit to one logical change, and write the message for the reason
  rather than the mechanics.
- Open the pull request against `main` and fill in the template: what changed,
  why, and how you tested it.
- CI runs per directory on pull requests.
  A pull request that touches `backend/` or `frontend/` also publishes
  untagged images to check that they build.

## License

By contributing you agree that your contribution is licensed under the
Apache License 2.0, as described in [LICENSE](LICENSE).
There is no separate contributor license agreement to sign.
