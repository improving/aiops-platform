# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
`AGENTS.md` is the canonical file and `CLAUDE.md` is a symlink to it.
Read the repository root `AGENTS.md` first; this file covers only `frontend/`.
The block at the end is written by `next dev`; keep it committed.

## Commands

```bash
pnpm install --frozen-lockfile            # Node 24, pnpm 11 (pinned in packageManager)
pnpm dev                                  # Turbopack dev server on :3000
pnpm lint                                 # ESLint flat config (eslint.config.mjs); 0 errors required, warnings tolerated
pnpm exec tsc --noEmit
pnpm build                                # standalone output in .next/standalone
pnpm exec prettier --write <files>
pnpm e2e                                  # Playwright fast tier (E2E_START_SERVERS=1 to have it start servers)
pnpm e2e:cluster                          # Playwright cluster tier (@cluster), workers=1, needs the live stack
pnpm exec playwright test e2e/fast/models-catalog.spec.ts --project=fast          # one spec
pnpm exec playwright test e2e/fast/theme.spec.ts:12 --project=fast                # one test by line
E2E_BASE_URL=http://localhost:3000 E2E_BACKEND_URL=http://localhost:8000 pnpm e2e  # against running servers
pnpm e2e:ui                               # Playwright UI mode
```

`docs/testing.md` at the repository root documents the tiers, fixtures and how to add a scenario.

## Architecture

- App Router under `src/app`; every page is a client component that renders a feature component from
  `src/components/<area>/` inside the shared `Dashboard` shell (`Header`, `Footer`, `Toaster`). Dynamic routes read
  `useParams()`; components that call `useSearchParams` are wrapped in `Suspense` so `next build` can prerender.
- API access goes through `src/services/*.ts` (axios instance in `services/api.ts`) using relative
  `/api/v1alpha1/...` URLs; `src/proxy.ts` rewrites them to the backend, preferring the server-side
  `AIOPS_BACKEND_URL` over the inlined `NEXT_PUBLIC_AIOPS_BACKEND_URL`. Errors go through `parseApiError` in
  `src/lib/utils.ts`, which understands FastAPI `detail` as a string, a list of `{msg}` or an object; show it with
  `toast(parseApiError(error))`.
- Lists that wait on Kubernetes (`InferenceEndpoints`, `VectorDBEndpoints`, `NotebookList`, notebook details) refresh
  through `src/hooks/usePolling.ts` every 5 s while any item is non-terminal; refreshes are silent (no spinner, no toast).
- Forms use react-hook-form with zod (`@hookform/resolvers`). Gate submit buttons on reported errors, not on
  `formState.isValid`, which does not turn true reliably with coerced number fields. The notebook name rule
  mirrors the backend: DNS-1123 label, max 32 characters.
- `src/constants/index.ts` holds the optional tool URLs (Langflow, Grafana, Jaeger); an empty value renders a
  "not configured" card instead of an iframe. `NEXT_PUBLIC_*` values are inlined at build time.
- shadcn/ui components live in `src/components/ui/` (style `new-york`, Tailwind 4 via `@theme` in
  `src/app/globals.css`). `button.tsx` carries local `loading`, `loadingIcon` and `icon` props and passes a single
  child through when `asChild` is set; re-apply that after a `shadcn add --overwrite`. The `toast` component is
  deprecated upstream but still used.
- `Header.tsx` builds the navigation from one `menuItems` array shared with `MobileNav.tsx` (a `Sheet` below `md`).
  Top-level links use `NavigationMenuLink asChild` with `flex-row`, never `Link legacyBehavior`.

## Conventions

- Prefer accessible names in tests (`getByRole`, `getByLabel`); the Playwright fixtures fail on any console error,
  so expected 4xx responses need `test.use({ allowedConsoleErrors: [FAILED_RESOURCE] })`.
- Keep `next/image` on the current API (`fill` + `sizes`, or width/height); the old `layout`/`objectFit` props warn.
- `.env.example` documents every variable; never commit `.env.local`.

<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->
