# AIOps frontend

Next.js 16 (App Router, React 19, TypeScript, Tailwind CSS 4, shadcn/ui) UI for the AIOps platform.

## Prerequisites

- Node.js 24
- pnpm 11 (`corepack enable` installs the version pinned in `package.json`)

## Develop

```bash
pnpm install
pnpm dev
```

Open <http://localhost:3000>.
The dev server and `pnpm build` both use Turbopack.

Other scripts:

```bash
pnpm lint             # ESLint (flat config, eslint-config-next)
pnpm exec tsc --noEmit
pnpm build            # standalone output in .next/standalone
pnpm start
```

## Environment variables

Copy `.env.example` to `.env.local` and adjust.
`NEXT_PUBLIC_*` variables are inlined at build time;
rebuild after you change them.
The `AUTH_*` variables are described under "Authentication".

| Variable | Default | Purpose |
| --- | --- | --- |
| `NEXT_PUBLIC_AIOPS_BACKEND_URL` | `http://localhost:8000` | Backend API base URL, inlined at build time |
| `AIOPS_BACKEND_URL` | unset | Runtime override for the proxy target, read on the server per request |
| `NEXT_PUBLIC_LANGFLOW_URL` | empty | Langflow UI embedded on the Develop page |
| `NEXT_PUBLIC_GRAFANA_URL` | empty | Grafana dashboards on inference endpoint pages |
| `NEXT_PUBLIC_JAEGER_URL` | empty | Jaeger traces on inference endpoint pages |

When an optional URL is empty the page shows a "not configured" card instead of an iframe.

## Authentication

Users sign in through Keycloak (realm `aiops`, public client `aiops-ui` with PKCE) with [Auth.js](https://authjs.dev) v5.
`src/auth.ts` configures the provider,
keeps the Keycloak tokens in the encrypted session cookie,
refreshes the access token through the token endpoint when it expires,
and exposes `session.accessToken`, `session.roles` and `session.idToken`.
`src/proxy.ts` redirects page requests without a session to `/login?callbackUrl=<path>`
and adds `Authorization: Bearer <accessToken>` to every `/api/v1alpha1/*` request it rewrites.
The user menu in the header signs out of Auth.js and then of Keycloak (`end_session_endpoint`), which returns to `/login`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `AUTH_MODE` | `oidc` | `disabled` turns the redirect and the bearer header off; the server logs a warning at startup |
| `AUTH_SECRET` | none | Encrypts the session cookie (`dev-auth-secret-change-me` locally) |
| `AUTH_URL` | none | Public URL of the UI, for example `http://localhost:3000` |
| `AUTH_KEYCLOAK_ISSUER` | none | Realm issuer, `https://auth.127.0.0.1.nip.io/realms/aiops` locally |
| `AUTH_KEYCLOAK_ID` | `aiops-ui` | Public client id |
| `NEXT_PUBLIC_AUTH_MODE` | `oidc` | Build-time mirror of `AUTH_MODE`; `disabled` hides the user menu |
| `NODE_EXTRA_CA_CERTS` | none | Path to `infra/local/ca/ca.crt`, so Node trusts the gateway certificate; shell environment only, `.env.local` has no effect on it |

`make frontend` at the repository root exports all of them.
The Playwright fast tier runs with `AUTH_MODE=disabled` because it has no Keycloak.
Sign-in starts from the client (`signIn` from `next-auth/react`), not from a server action:
Auth.js issue #13388 makes the server-action form fail on Next 16.

## How API calls reach the backend

The browser calls relative paths such as `/api/v1alpha1/models` (see `src/services/api.ts`).
`src/proxy.ts` matches `/api/v1alpha1/*` and rewrites the request to `${AIOPS_BACKEND_URL:-NEXT_PUBLIC_AIOPS_BACKEND_URL}/v1alpha1/*`,
so the backend URL never has to be reachable from the browser and no CORS setup is needed.

## Docker

```bash
docker build -t aiops-frontend:dev .
docker run --rm -p 3000:3000 aiops-frontend:dev
```

The image is a multi-stage `node:24-alpine` build that runs the standalone server on port 3000.
The `NEXT_PUBLIC_*` variables are build args, so pass non-default URLs with `--build-arg`:

```bash
docker build -t aiops-frontend:dev \
  --build-arg NEXT_PUBLIC_AIOPS_BACKEND_URL=http://backend:8000 .
```
