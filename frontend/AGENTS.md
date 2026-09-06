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
- Model registry (Phase 3): `/models/registry` (`RegistryPage.tsx`, `src/services/registryService.ts`) is the admin
  surface over `GET/POST/PATCH/DELETE /v1alpha1/registry` (members get the same page read-only, gated the same way
  as `ProvidersPage.tsx`). `ImportFromHuggingFaceDialog.tsx`/`AddOllamaModelDialog.tsx`/`AddHostedModelDialog.tsx`
  call `registryService.search(source, q)` then `registryService.importEntry({source, source_id, status: "draft"})`;
  `AddManuallyDialog.tsx` replaces the old "Import Model" dialog, now `registryService.manualCreate(...)` with a
  list of `{engine, reference}` serving options and optional (not required) description/subcategory/size. Ollama
  and "Add manually" close their dialog on a successful import (one entry per open); Hugging Face and hosted stay
  open so an admin can import several results in a row, and close only through their own "Done" button. Publish/
  Deprecate flip `status` through `registryService.update`; Sync calls `POST /{id}/sync`; `EditEntryDialog.tsx`
  edits metadata and replaces serving options.
- The launch wizard (`LaunchModel.tsx`) fetches `modelService.getModelServingOptions(id)`
  (`GET /v1alpha1/models/{id}/serving-options`) and keeps only the options with a non-null `engine_id` (a hosted
  option such as `openrouter` has none and no chart to launch); the engine `Select` lists those options by their
  `engine` name, and submitting sends `serving_option_id` alongside `engine.id` (`InferenceInstanceCreateSchema`).
  `cpuOnly` (inlined in `LaunchModel.tsx`) makes the accelerator step optional when every launchable option's
  `cpu` is `true`. `src/lib/engines.ts` (the Phase 1 `enginesForModel`/`isOllamaTag` stopgap) is gone.
- `src/lib/backend.ts` `backendUrl()` is the one place that resolves the backend URL on the server
  (`AIOPS_BACKEND_URL`, else the inlined `NEXT_PUBLIC_AIOPS_BACKEND_URL`); `src/proxy.ts` and the chat route use it.
- Chat: `modelService.getChatTargets()` calls `GET /api/v1alpha1/chat/targets`, which lists what the caller may
  chat, embed or rerank against (`ChatTarget`: `name` is `inst-<id8>`, `capability`, `ready`, `via`).
  `src/app/api/chat/route.ts` is a Node route handler on the Vercel AI SDK (`createOpenAICompatible` pointed at
  `<backend>/v1alpha1`, `streamText`, `toUIMessageStream`, `createUIMessageStreamResponse`). The body is
  `{ messages, model, system, temperature }`, `model` being the target name; the handler reads the session itself
  (`auth()`, 401 without one unless `AUTH_MODE=disabled`), forwards the bearer to
  `POST /v1alpha1/chat/completions`, and is excluded from the proxy matcher so it answers JSON instead of a login
  redirect. `src/components/chat/ChatPanel.tsx` (`/chat`, `?target=<name>` preselects) fetches the targets, keeps
  those with `capability === "chat"` and `ready`, uses `useChat` with a `DefaultChatTransport` whose
  `prepareSendMessagesRequest` sends the target name as `model`, and keeps one conversation per target in
  `localStorage` (per user and target, `src/lib/chatStorage.ts`, cleared on sign-out; `aiops.chat.<target name>`). The endpoint details page links to it with a "Chat" button using
  `inferenceInstance.litellm_model_name` (falling back to `inst-<id8>` derived from the instance id).
  Since Phase 2b, `ChatTarget.provider_id` (`null` for instances and the mock target) tells the two apart;
  `ChatPanel.tsx` splits the target `Select` into two `SelectGroup`s, "Deployed" and "Hosted".
- Hosted providers (Phase 2b): `/providers` (`ProvidersPage.tsx`, `src/services/providerService.ts`) lists an
  organization's hosted providers (`GET /v1alpha1/providers`) with an expandable model table per provider
  (display name, model id, capability, context, per-token prices) and a `BudgetCard` for the LiteLLM team budget
  (`GET`/`PUT /v1alpha1/organizations/current/{spend,budget}`). `AddProviderDialog.tsx` calls the preflight
  `POST /v1alpha1/providers/discover` before the row exists, then `POST /v1alpha1/providers` with the picked
  model ids and their discovered display names. Every write (add, enable toggle, discover-and-add, remove a
  model, delete) is admin-only; `src/lib/roles.ts` `isAdmin(session)` is the one place that decides whether the
  page renders those controls (`AUTH_MODE=disabled` -> true, else `session.roles` needs `"admin"`) -- a UI hint
  only, like `session.roles` itself, since the backend enforces `require_admin` regardless.
  The "Monthly budget (USD)" field is a plain `type="text"` input (not `type="number"`), so it keeps the
  `textbox` accessible role the fast tier targets; the same is true of nothing else here, but keep it in mind
  when adding a numeric field a Playwright spec will locate by role.
- Usage: `/usage` (`UsagePage.tsx`, `src/services/usageService.ts`) reads
  `GET /v1alpha1/organizations/current/usage?days=` (a "Period" combobox, "Last 7 days"/"Last 30 days") and
  renders four totals cards (Requests, Input tokens, Output tokens, Spend USD), a "By target" table and a "By
  user and day" table (both located by their `<caption>`, the accessible table name); a member sees the note
  "You see your own usage" when the response's `scope` is `"user"` (an admin's is `"organization"`), and a 503
  or 502 from the endpoint replaces the tables with a card showing the detail. No session is needed on the
  page: the backend scopes the response from the caller's bearer token. Linked from the header (after
  "Providers"), the Providers page, and every inference endpoint's details page.
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
- Loading placeholders come from `src/components/LoadingState.tsx` (`CardGridSkeleton`, `DetailSkeleton`,
  `TableSkeleton`), each wrapped in `role="status" aria-label="Loading"`; specs wait with
  `AppShell.waitForLoaded()`. Never render the string "Loading...".
- Drill-down pages pass `breadcrumbs` (`Crumb[]` from `src/components/Breadcrumbs.tsx`) to `Dashboard`;
  list pages pass none. The trail always starts at Home.
- Copy actions use `src/components/CopyButton.tsx` (aria-label "Copy <label>", toast "Copied");
  code examples use `src/components/CodeSnippet.tsx` (`<pre aria-label>` plus a copy button). Do not inline
  `navigator.clipboard` calls in feature components.

## Authentication

- Auth.js v5 (`next-auth@5.0.0-beta.32`) with the Keycloak provider in `src/auth.ts`: public client `aiops-ui`, PKCE,
  `trustHost: true`, tokens kept in the JWT session and refreshed in the `jwt` callback; the `session` callback exposes
  `accessToken`, `roles` (decoded from the access token, UI hints only), `idToken` and `endSessionUrl`.
- `src/proxy.ts` matches everything except `_next/`, `api/auth/` and `favicon.ico`: it rewrites `/api/v1alpha1/*` with
  `Authorization: Bearer <accessToken>`, lets `/login` and files with a suffix through, and redirects other page requests
  without a session to `/login?callbackUrl=<path>`. `AUTH_MODE=disabled` (server env) skips Auth.js entirely, and
  `src/instrumentation.ts` logs `AUTH_MODE=disabled: the UI is unauthenticated` once at startup.
- `NEXT_PUBLIC_AUTH_MODE` mirrors `AUTH_MODE` at build time and only decides whether `AuthProvider` mounts the
  `SessionProvider` and whether `Header.tsx` renders `UserMenu`; never use it for access decisions.
- Sign-in happens in the client component `src/app/login/page.tsx` with `signIn("keycloak", { redirectTo })`; do not
  move it into a server action (Auth.js issue #13388 on Next 16). Sign-out is `signOut({ redirect: false })` followed by
  a navigation to `session.endSessionUrl` so the Keycloak SSO session ends too.
- The Playwright fast tier runs with `AUTH_MODE=disabled` and `NEXT_PUBLIC_AUTH_MODE=disabled`
  (set in `playwright.config.ts`), so specs must not depend on the user menu; its managed backend also has
  `AIOPS_CHAT_MOCK=true`, so `chat.spec.ts` gets a canned streamed echo through the real route handler.
- The `cluster` tier logs in for real:
  the `setup` project (`e2e/auth.setup.ts`) signs alice, bob and admin into Keycloak through its own login form
  and saves each session to `playwright/.auth/<user>.json` (git-ignored);
  the `cluster` project depends on `setup`, gets `ignoreHTTPSErrors: true` for the local CA,
  and defaults its `storageState` to alice's.
  The `asUser(name)` fixture opens a second `BrowserContext` with another saved user's storage state
  for ownership/permission checks within one test;
  `BackendApi` (the `api` fixture) instead fetches a client-credentials token from `aiops-automation`
  when `AUTH_MODE` is not `disabled`, for calls made directly against the backend rather than through a
  logged-in page.

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
