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
All variables are `NEXT_PUBLIC_*`, so they are inlined at build time;
rebuild after you change them.

| Variable | Default | Purpose |
| --- | --- | --- |
| `NEXT_PUBLIC_AIOPS_BACKEND_URL` | `http://localhost:8000` | Backend API base URL |
| `NEXT_PUBLIC_LANGFLOW_URL` | empty | Langflow UI embedded on the Develop page |
| `NEXT_PUBLIC_GRAFANA_URL` | empty | Grafana dashboards on inference endpoint pages |
| `NEXT_PUBLIC_JAEGER_URL` | empty | Jaeger traces on inference endpoint pages |

When an optional URL is empty the page shows a "not configured" card instead of an iframe.

## How API calls reach the backend

The browser calls relative paths such as `/api/v1alpha1/models` (see `src/services/api.ts`).
`src/proxy.ts` matches `/api/v1alpha1/*` and rewrites the request to `${NEXT_PUBLIC_AIOPS_BACKEND_URL}/v1alpha1/*`,
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
