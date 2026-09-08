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
- Mount effects call their fetcher through an inline async wrapper, `(async () => { await fetchX(); })()`; it keeps
  the effect body synchronous and satisfies `react-hooks/set-state-in-effect`. Do not shorten it to a bare call.
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
  The conversation section has a bounded height (`h-[calc(100vh-18rem)]`, the 18rem being the shell around it)
  and the log inside it carries `min-h-0` next to `flex-1`: without both, the section grew with the history,
  the log never scrolled and the composer was pushed off the page.
  The log follows the newest message unless the reader has scrolled up (a `pinned` ref, never state, so
  scrolling does not render); `e2e/fast/chat.spec.ts` seeds `aiops.chat.dev.inst-mock` to cover it.
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
  `AppShell.waitForLoaded()`. Never render the string "Loading...", except the fine-tune logs dialog's
  "Loading logs..." button label, the one exception.
- Drill-down pages pass `breadcrumbs` (`Crumb[]` from `src/components/Breadcrumbs.tsx`) to `Dashboard`;
  list pages pass none. The trail always starts at Home.
- Copy actions use `src/components/CopyButton.tsx` (aria-label `Copy ${label}`, label passed through
  unchanged, no lowercasing): the label reads naturally after the word Copy, a lowercase phrase with
  acronyms and proper nouns kept, e.g. `endpoint`, `model id`, `API key`, `notebook URL`.
  Code examples use `src/components/CodeSnippet.tsx` (`<pre role="group" aria-label>` plus a copy button),
  including the highlighted ones -- it takes an optional `lang` (highlight with `sugar-high`) and `wrap`
  (wrap long lines and bound the height instead of scrolling sideways). Both default off, so an existing
  caller renders exactly as before. There is no second code-block component.
  Do not inline `navigator.clipboard` calls in feature components.
- Secrets (API keys, credentials, personal tokens) render through `src/components/MaskedSecret.tsx`
  (`<MaskedSecret value label testId?>`): masked by default (a fixed-width `•` run, so neither the value nor
  its length shows), a copy button that copies the real value without revealing it, and an eye that toggles it
  on screen. This keeps secrets out of screen recordings and shared screens. Used by the model instance API-key
  dialog (`InferenceEndpointDetails.tsx`), the vector-DB credential dialog (`ShowCredentialButton.tsx`) and the
  new-token dialog (`CreateTokenDialog.tsx`); never print a secret into a `code`/`Input` directly. Curl and code
  examples carry a `<api key>`/`<token>` placeholder, never the real value. The masked value is still in the DOM
  when revealed, so a test that reads it (`getByLabel(label)` / `getByTestId`) must click "Reveal `<label>`"
  first (see the tokens and vector-db page objects).
- `/vector-databases/endpoints/[id]` (`VectorDBInstanceDetails.tsx`) follows the same layout as the model
  instance detail page: status, endpoints with copy, a curl example, credential reveal and delete; the list
  card title links to it. The header name there is `api-key` (the model instance page's is `x-api-key`).
- Card lists (`InferenceEndpoints`, `VectorDBEndpoints`, `NotebookList`) share `src/components/ListControls.tsx`:
  `useListState` + `applyListControls` (status filter, name/status sort, 12 per page with "Show more").
  `applyListControls`'s `ready` filter is optional -- a caller that omits it (`MembersTable`) also passes
  `showStatusFilter={false}` to `ListControls` so the Status combobox does not render; `sortKey`/`direction`
  let a caller replace the default name sort while `state.sort` is still at its default.
  The empty-state call to action is keyed on the raw list, not the filtered one.
- Instance operations (#15, #16): `src/components/instances/` holds the pieces shared by the three instance kinds --
  `StatusBadge` (`Ready` when `ready`, else the persisted `status`, else `Pending`), `ErrorBanner` (`role="alert"`, `last_error`
  with a `Copy error` button), `LogsPanel` (Container and Lines comboboxes, Previous switch, `role="group"` "Log output"),
  `EventsPanel` (table captioned "Events") and `InstanceActions` (an "Actions" menu whose items open confirmation dialogs;
  a kind passes only the callbacks it supports, vector databases `onRestart` only, notebooks none).
  The three detail pages mount Logs and Events as tabs (the inference page keeps `?tab=`), the cards show the badge, the
  banner and, for inference, the replica count. `usePolling` treats `Stopped` as terminal. The launch wizard's Deploy Config
  tab has GPU count (hidden for a `cpu` serving option), Replicas, CPU and Memory (`type="text"` inputs, so they keep the
  `textbox` role); they are sent as top-level `gpu_count`, `replicas`, `cpu`, `memory`. The fast tier stubs every instance
  route with `page.route` (`e2e/fast/instance-operations.spec.ts`); `e2e/cluster/day2-ops.spec.ts` runs the real flow on kind.
- `components/instances/InstanceAccess.tsx` (#36, #29) is the model instance page's Access block: two sub-tabs,
  "API access" (the gateway host as a copyable Base URL, the model, the `x-api-key` reveal, and a "Code examples"
  button) and "Langflow" (the instance's `litellm_model_name`, the name Langflow lists under its "OpenAI
  Compatible" provider once the Develop page has synced the organization, and nothing to paste). The Langflow
  tab is disabled while `litellm_model_name` is null (not registered in LiteLLM), and its "Open Langflow" link
  needs a `langflowUrl` from `useRuntimeConfig()`, which the fast tier has to stub. Each field table is a
  `role="group"` with an accessible name ("API access fields", "Langflow fields"): scope specs to those, because
  the code examples contain the same URL. `clusterEndpoint` and `workloadChecksApiKey` stay in the API for
  other callers; the tab stopped showing the in-cluster Service address when LiteLLM became the way in.
  The reveal button lives here, not in a detail row; the page has no separate "Endpoint" detail row either
  (Access shows the same host as a copyable Base URL on the tab that opens by default, and Ready and Status
  carry the readiness its red/green text repeated).
- `components/develop/Develop.tsx` (#29) calls `POST /v1alpha1/langflow/provision` once per page load
  (`services/langflowService.ts`, idempotent) and renders an `OrganizationPanel`, a `region` named
  "Langflow for <organization>": one line with who the caller is in Langflow, the provider slot the platform
  manages, a "Models (N)" `Combobox` (the search matches the name and the label, selecting an `option` copies
  the name through `useCopy()` from `CopyButton.tsx`), a "Sync again" button and an "Open in a new tab" link,
  plus the failure detail in a `role="alert"`; the names stay behind the picker so the editor keeps the page
  (`h-[calc(100vh-18rem)]` like the chat page, the iframe `flex-1 min-h-0`). The sync keeps an in-flight ref:
  strict mode in `next dev` mounts twice, and two concurrent creates of one Langflow variable fail.
- `src/components/ui/combobox.tsx` `Combobox` is the one searchable dropdown (a `role="combobox"` trigger with
  `aria-expanded`, a `Popover` holding a `Command` list that closes on select; `items` carry `value`,
  `keywords`, an optional `node` and `onSelect`; `footer` renders under the list). The endpoint page's two
  time-range pickers and the Develop page's model picker use it; do not hand-roll a fourth Popover + Command.
  Under `AIOPS_CHAT_MOCK` the endpoint answers with `inst-mock`, which `e2e/fast/runtime-config.spec.ts` asserts.
- `components/instances/CodeExamplesDialog.tsx` holds the worked examples: curl, Python and TypeScript, one at a
  time, rendered by `CodeSnippet` with `lang` and `wrap` set. Always pass the `lang` (`highlight(code, { lang })`,
  typed `LanguageName`): the default is JavaScript, whose comment rule reads the `//` in an `https://` URL as the
  start of a line comment and greys out the rest of the curl command. Each `CodeExample` carries its own
  `lang`, so this cannot be forgotten per snippet.
  Its token colours are CSS variables (`--sh-*`) defined for both themes in `globals.css`, and each one must be
  a complete colour: the highlighter writes `style="color:var(--sh-string)"` inline, so a variable whose value
  is another `var(--sh-*)` reference resolves to nothing and the token silently inherits the surrounding text
  colour. `e2e/fast/instance-operations.spec.ts` compares every token's computed colour against the inherited
  one and fails when any of them match, which catches a broken variable that a colour count would not.
  Two layout traps, both fixed and pinned by the same test: `DialogContent` ships `sm:max-w-lg`, so a wider
  dialog needs `sm:max-w-3xl`, not `max-w-3xl`; and it is a grid, whose items default to their content width,
  so the code needs `min-w-0` down the chain plus wrapping, or one long curl line pushes the dialog past the
  viewport.
- `src/lib/runtimeConfig.ts` fetches `GET /api/v1alpha1/config/ui` once (`RuntimeConfigProvider` in `app/layout.tsx`)
  and `useRuntimeConfig()` gives `GrafanaEmbed`, `JaegerEmbed`, `NotConfigured` and `Develop` the Grafana, Langflow and Jaeger URLs,
  each falling back to its `NEXT_PUBLIC_*` value; consumers render nothing until `loaded` is true.
  `e2e/fast/runtime-config.spec.ts` stubs the endpoint with `page.route`.

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
  (set in `playwright.config.ts`), so specs must not depend on the session; the header renders `DevUserMenu`
  (the organization block without sign-out) in that mode; its managed backend also has
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

## Organizations, audit and tokens

- `src/lib/orgCookie.ts`: the switcher writes `aiops_org` (path `/`, SameSite Lax, one year); `src/proxy.ts` and `src/app/api/chat/route.ts`
  turn it into `X-Org`, and in `AUTH_MODE=disabled` only turn `aiops_dev_user` into `X-Dev-User`.
  `services/api.ts` clears the cookie and reloads once (a `sessionStorage` guard) when the backend answers 403 `You are not a member of this organization`.
- `src/hooks/useOrg.ts` `useOrg()` reads `GET /v1alpha1/organizations/current` and exposes `org`, `role`, `isAdmin`, `isPlatformAdmin`;
  the new pages and `UserMenu.tsx` gate on it, so menu visibility follows the membership role. `src/lib/roles.ts` `isAdmin(session)` still serves
  `/providers` and `/models/registry` (follow-up: move them to `useOrg()`).
- `UserMenu.tsx` exports `UserMenu` (oidc), `DevUserMenu` (disabled) and the shared `OrganizationMenuItems`: the active organization,
  a "Switch organization" submenu (`menuitemradio` per membership, `<name> · <role>`), "Manage organization" and "Audit log" (admins), "API tokens".
- Pages: `/organization` (`components/organization/`: summary, members with a `Role for <email>` select and `Remove`, invitations with `Copy sign-in URL` and `Withdraw`,
  `Invite a member` and `Create organization` dialogs), `/audit` (`components/audit/AuditPage.tsx`: filters, the `Audit events` table, `Export CSV` through `format=csv`),
  `/settings/tokens` (`components/tokens/`: the `API tokens` table with `Revoke`, the `Create token` dialog whose second face shows the token once with `Copy API token` and a `curl example`).
  Types live in `src/types/organization.ts`, calls in `services/{orgService,auditService,tokenService}.ts`.
  Every table uses `ListControls`; the audit page keeps `useListState`/`applyListControls`/`ShowMore` but renders its own filters and sorts newest first through `applyListControls`'s `sortKey`/`direction` option (`Date.parse(e.at)`, `"desc"`), passing no `ready`.
- Fast tier: `asUser(name)` in `e2e/fixtures.ts` opens a context with the `aiops_dev_user` cookie for `dev`, `alice`, `bob`, `viewer` or `outsider`
  (the cluster tier keeps the saved Keycloak states); `BackendApi.withHeaders({...})` adds `X-Org` or a token bearer to every call --
  through `userApi` the proxy replaces it with the `aiops_org` cookie, so pinning an organization there needs a cookie-scoped context instead (see `orgScopedApi` in `e2e/cluster/tenancy-isolation.spec.ts`).

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
