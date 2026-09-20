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
- The launch wizard helps before the launch, inline and never as a toast or a gate (`e2e/fast/launch-form-hints.spec.ts`):
  the host cards and a `ResourceHint` (`components/instances/`) under GPU count, CPU and Memory show what is free on the picked host
  from the hosts API's `allocatable_*` and `requested_*` fields, and warn (`role="alert"`) when the form asks for more;
  a GPU-fit line (`lib/launchHints.ts` `estimateGpuFit`: the registry's `size` against the GPU memory, vLLM's 0.9 utilisation and a measured runtime overhead)
  says what stays for the KV cache or that the weights do not fit, and that slices of a time-sliced GPU add no memory;
  `ArgHelp` (`components/models/`) puts an info popover next to a CLI argument or environment variable that `lib/engineArgs.ts` knows
  (summary, the engine's default, range, a platform note, a doc link; lookup ignores a leading `--` and `_` versus `-`).
  Add an entry there when a new default argument is seeded. State a default only where the engine documents one.
  Rules the page objects impose: nothing inside a `<Label>` (the inputs are found by their exact label), no second button named `Delete` or `Next`,
  no new input with the placeholders `Argument Name` or `Variable Name`, and `type="button"` on every button inside the form.
  Without a picked host (the Skip path, and the whole fast tier of `launch-form.spec.ts`, where `/hosts` answers 500) the hints render nothing.
- The launch wizard (`LaunchModel.tsx`) fetches `modelService.getModelServingOptions(id)`
  (`GET /v1alpha1/models/{id}/serving-options`) and keeps only the options with a non-null `engine_id` (a hosted
  option such as `openrouter` has none and no chart to launch); the engine `Select` lists those options by their
  `engine` name, and submitting sends `serving_option_id` alongside `engine.id` (`InferenceInstanceCreateSchema`).
  `cpuOnly` (inlined in `LaunchModel.tsx`) makes the accelerator step optional when every launchable option's
  `cpu` is `true`. `src/lib/engines.ts` (the Phase 1 `enginesForModel`/`isOllamaTag` stopgap) is gone.
- `src/lib/backend.ts` `backendUrl()` is the one place that resolves the backend URL on the server
  (`AIOPS_BACKEND_URL`, else the inlined `NEXT_PUBLIC_AIOPS_BACKEND_URL`); `src/proxy.ts` and the chat route use it.
- Chat: `modelService.getChatTargets()` calls `GET /api/v1alpha1/chat/targets`, which lists what the caller may
  chat, embed or rerank against (`ChatTarget`: `name` is `inst-<id8>`, `capability`, `ready`, `via`, and an optional `context_length`).
  `src/app/api/chat/route.ts` is a Node route handler on the Vercel AI SDK (`createOpenAICompatible` pointed at
  `<backend>/v1alpha1`, `streamText`, `toUIMessageStream`, `createUIMessageStreamResponse`). The body is
  `{ messages, model, system, temperature, maxOutputTokens }`, `model` being the target name and the last two left out for "model default"; the handler reads the session itself
  (`auth()`, 401 without one unless `AUTH_MODE=disabled`), forwards the bearer to
  `POST /v1alpha1/chat/completions`, and is excluded from the proxy matcher so it answers JSON instead of a login
  redirect. The handler sets `includeUsage` and attaches `ChatMetadata` (`src/lib/chatMetadata.ts`) to a finished answer:
  the SDK's own `finish-step.performance` timings, kept by a `TransformStream` tap because `messageMetadata` sees only `start` and `finish`,
  and the token counts of the usage chunk. No timer of our own: a reasoning model's first output is not a `text-delta`.
  `src/lib/stepMetrics.ts` makes one answer's figures from several steps (a tool loop): the first step's time to first output, all output tokens over all generating time,
  `steps`, and `contextTokens` from the last step alone, because the usage total counts the prompt once for every step and would overstate the window meter.
  `convertToModelMessages` runs with `ignoreIncompleteToolCalls`, since a stopped answer leaves a tool call without its result in `localStorage`.
  `ChatTarget.tools` (`true`, `false`, or null for unknown) says whether the target answers a request with tools.
  Tools: the body also carries `toolSources` (`[{ type: "mcp", server: "<name>" }]`), resolved in `src/lib/toolSources.ts`, one resolver for each `type`
  (a tool typed in the playground or a built-in one is a new member of the union, not a change to the route).
  The MCP resolver opens one `@ai-sdk/mcp` client (streamable HTTP) on the backend's `/v1alpha1/mcp` with the caller's bearer and `X-Mcp-Servers`; this process holds no credential.
  With tools, `streamText` gets them and `stopWhen: stepCountIs(MAX_TOOL_STEPS)` (8), and the client closes on finish, error and abort.
  With tools on and an empty system prompt the route sends `DEFAULT_TOOL_INSTRUCTIONS` (`toolSources.ts`): measured on Qwen2.5 14B, a model with tool definitions and no system message sometimes wrote text in another language or JSON "plans" before the real call;
  a user's own system prompt is sent as it is. The chat mock answers `system?` with the system message it got, which is how `chat-tools.spec.ts` checks this.
  A resolver failure answers 502 `Could not reach the tools: ...` before anything goes to the model, never a silent answer without tools;
  the page maps it and offers "Send without tools", which is `regenerate({ body: { toolSources: [] } })` (`prepareSendMessagesRequest` spreads the request's own `body` last).
  One tool result gives the model at most `MAX_TOOL_RESULT_CHARS` (16,000, about 4,000 tokens) of text: `capToolResult` wraps each tool's `execute`, cuts the text parts in order and appends a note that says how much was left out, so the model and the reader both know (a documentation tool can fill a 16k window with one answer).
  "Ask before each tool call" (a switch in the Settings sheet, kept per user like the server choice): the body carries `approveTools`, the route gives `streamText` `toolApproval: () => "user-approval"`,
  the step then ends with the tool part in state `approval-requested`, `ToolCallBlock` shows it open as `data-state="asking"` with the input and Approve / Deny (last turn only),
  `addToolApprovalResponse` records the answer, and `sendAutomaticallyWhen: lastAssistantMessageIsCompleteWithApprovalResponses` sends the conversation back: an approved call runs, a denied one (`output-denied`, shown as failed, "not approved") is told to the model.
  The admin's floor is `McpServer.approval` (`never`, `writes`, `always`; `ApprovalField.tsx` in the Edit tools dialog): `resolveMcp` reads `/v1alpha1/mcp/servers` from the backend with the caller's headers (never from the browser's request)
  and `needsApproval(toolName)` finds the server by `tool_prefix`; `writes` asks for every tool that does not say `read_only: true`; a tool of no known server, or a policy that cannot be read, asks. The member's switch can only add to it.
  The Tools popover says "asks first" or "asks before changes" next to such a server, and a denied call reads "not approved".
  `lib/toolBudget.ts` estimates what the definitions of the tools that are on take of the target's window (`McpTool.size` / 3.5 characters a token, 600 characters for a tool listed before sizes were kept), and the Tools section says it (`data-testid="tools-budget"`), as a `role="alert"` from 40% on: the definitions go with every step, and Linear's 66 tools filled a 16k window on the lab.
  Compaction (`lib/compaction.ts`, pure functions; `CompactionMarker.tsx`): a long conversation fills the window, so a compaction asks the target for a summary of the older turns (`POST /api/chat/compact`, one call with no tools and no stream, the platform's own instruction at temperature 0)
  and puts a marker message (`role: "system"`, `metadata.compaction`) in front of the turns that stay. The turns above the last marker stay in the browser, collapsed (`data-testid="chat-compacted"`), and Undo removes the marker;
  `forRequest(messages)` in `prepareSendMessagesRequest` sends the summary as `summary` and only the turns after the marker, and the route puts the summary into the ONE system message (`withSummary`: after the user's prompt or the default tool instructions; several chat templates accept no second system message).
  The cut is always in front of a user message and keeps the last two user turns word for word (`planCompaction`), so a tool call and its result are never parted; the transcript cuts each tool result to 2,000 characters and drops the oldest lines to fit half the window.
  "Compact" is next to the window meter in the composer (only when there is something to compact); "Compact automatically" (settings, kept per user in `aiops.chat.compact.<user>`) compacts before a send from 75% of a KNOWN window on (`shouldAutoCompact`),
  and not again for the same answer: after a compaction the newest answer still carries the old count, so the marker keeps `atMessageId` and the meter shows nothing until the next answer. A summary that fails changes nothing: the message goes with the whole history, and a toast says so.
  Measured on the lab with a reasoning model (Qwen3.8 27B): with a limit of 700 output tokens it used them all for thinking and wrote no summary (`finish_reason: length`), and a non-streamed call of a minute hit the backend's 60 s read limit for the proxy.
  So the route streams from the model and answers one JSON document, and `summaryTokens(window)` gives a quarter of the window (700 to 4,000; the summary itself is about 400).
  A summary call takes up to two minutes, and everything `compact()` reads comes from the render of the click: so the conversation is locked while it runs (`locked = busy || compacting` gates Send, Clear, Edit, Regenerate, Continue, approvals and typed results),
  a switch of target or an unmount aborts the call, the result is dropped when `targetRef` moved (`setMessages` and `sendMessage` act on the chat of the moment they RUN, which after a switch is another target's: the old conversation would go into the new target's chat, its storage and its model), and the marker is applied with `setMessages((now) => ...)` only when `now` still holds the summarized turns in front of the same user turn.
  `lib/chatBackend.ts` is what both chat route handlers share (the caller's headers, the provider); both are under `api/chat`, which the proxy matcher leaves out. The mock model writes "Mock summary of <n> user turns." for the compaction instruction; `e2e/fast/chat-compaction.spec.ts`.
||||||| a229f3e
  Functions typed in the playground are a second tool source (`{ type: "function", name, description, parameters }`, `usePlaygroundFunctions.ts`, `FunctionDialog.tsx`, the "Functions" group of the Tools section; kept per user in the browser):
  the route gives the model a tool with no executor, the loop stops at the call, and `ToolCallBlock` (`data-state="yours"`, "waiting for your result") takes the result the user types, as a result or as an error (`addToolOutput`).
  The conversation then goes back by itself, but only when the last step calls a typed function (`lastStepCallsATypedFunction`): for every finished tool step it would restart a loop the route cut at its step limit.
  A function name has no `-`, so it can never be the name of a platform tool (`<alias>-<tool>`); `e2e/fast/chat-functions.spec.ts`.
  The approver is the user whose session sends the request, so the approval is not signed (`experimental_toolApprovalSecret` is for a server that must not trust its client).
  An answer cut at the step limit carries `toolLimit` in its metadata and shows "Stopped after N tool steps" with Continue.
  Layout (the conversation first, each option where it is used; `e2e/fast/chat-layout.spec.ts`): there is NO side panel and NO bar above: the page starts with the conversation, and everything else is in the row under the message field (`Composer`'s `tools` and `actions` slots; the row wraps on a narrow screen).
  On the left: the target picker in a compact form (`TargetPicker` `className`, a fixed width, so a long name is cut), then the tools. On the right: the window meter with "Compact", then three icon buttons with their names as `aria-label` and `title`: "View code" (`CodeExamplesDialog` takes a `trigger`), "Settings" (a dot, `data-testid="chat-settings-changed"`, when something is not at its default; its title says when a system prompt is active) and "Clear conversation".
  The Settings sheet (`ChatSettings.tsx` is its content) has what is needed now and then: system prompt (first, the one used most), temperature, max tokens, "Compact automatically" and "Ask before each tool call".
  The tools are in the composer's row, where a message is written (`Composer`'s `tools` slot): `ChatTools.tsx` is a button "Tools" with a count (amber while the window warning is on), chips of what is on (`list` "Tools that are on", a "Turn off <name>" button each, "+N" after three), and a popover that holds the `role="group"` "Tools":
  the window estimate, a search field from six entries on, the servers grouped as On, Available and Needs attention, the Functions group, and "Manage MCP servers". "Connect" and the function dialogs close the popover first. The window meter is a small ring with the numbers, next to "Compact".
  The conversation's height is `100vh - 18.5rem`: the 18rem shell plus the composer's taller row; an existing spec ("a long conversation scrolls inside the log, not the page") fails when a change of the layout makes the page scroll.
  Page object: the Tools group and the settings fields are NOT on the page until opened: `chat.openTools()` / `closeTools()`, `chat.openSettings()` / `closeSettings()` (`send()` closes both itself; the sheet is modal, so `openTools()` closes it first). A locator saved from `chat.tools` still needs the popover open at the moment of the click.
  `components/chat/useToolServers.ts` keeps the user's choice in `localStorage` (`aiops.chat.tools.<user>`, across targets; `?tools=a,b` adds to it, which is what "Try in chat" links use),
  and `ChatTools.tsx` holds the Tools group (`role="group"` "Tools", a switch `Use <name>` per server): blocked with the reason when `ChatTarget.tools` is false
  (a vLLM instance links to its page for Tool calling) or the role is viewer, with the choice kept; `null` allows use with a note. the count of servers that are on is said for a screen reader (`data-testid="chat-tools-on"`, "N tool servers on").
  `ToolCallBlock` shows a platform tool name `<server><id8>-<tool>` as `server · tool`. "View code" adds a "Tools (MCP)" example for the API host.
  `e2e/fast/chat-tools.spec.ts` runs the whole loop against the backend mocks (registry, MCP endpoint, a model that calls the first tool on `call ...`).
  `src/components/chat/ChatPanel.tsx` (`/chat`, `?target=<name>` preselects) fetches the targets, lists
  those with `capability === "chat"` (one that is not `ready` is listed disabled as "Starting"), uses `useChat` with a `DefaultChatTransport` whose
  `prepareSendMessagesRequest` sends the target name as `model`, and keeps one conversation per target in
  `localStorage` (per user and target, `src/lib/chatStorage.ts`, cleared on sign-out; `aiops.chat.<target name>`). The endpoint details page links to it with a "Chat" button using
  `inferenceInstance.litellm_model_name` (falling back to `inst-<id8>` derived from the instance id).
  Since Phase 2b, `ChatTarget.provider_id` (`null` for instances and the mock target) tells the two apart;
  `TargetPicker.tsx` groups them as "Deployed" and "Hosted" in the shared `Combobox`
  (which takes a per-item `group` and `disabled` for this; an organization with a hosted provider has tens of targets, so the list is searchable).
  `ChatPanel.tsx` keeps the state, the transport, the storage and the scroll; the parts are
  `ChatMessage.tsx` (memoized; an answer is Markdown without a bubble, a user turn plain text in one; Copy, Regenerate and Edit only on the last turn of each side;
  an answer with nothing to show yet renders nothing, so "the message is not empty" still means content for the specs, and the `role="status"` waiting row stands in;
  an answer's parts render in the order they arrived, because with tools a turn is several steps: thinking, a `ToolCallBlock.tsx` per tool part
  (`data-testid="chat-tool-call"`, `data-state` `running`, `done` or `failed`; a `<details>` that is open only while the call runs; input and result as plain, never highlighted, `CodeSnippet`s,
  since a tool's result comes from outside the platform; an MCP result shows its text parts, not the envelope), then the text.
  `hasContent` (exported next to `messageText`) counts a tool part as content, so the waiting row gives way to the tool line),
  `Markdown.tsx` (`react-markdown` + `remark-gfm`, no `rehype-raw`, so HTML in an answer stays text; a fenced block is a `CodeSnippet`, an unknown language is not highlighted),
  `Composer.tsx` (one box, a field that grows, the `Message` label kept `sr-only` for the page object, and the window meter from the last answer's counts against `context_length`),
  `ChatSettings.tsx` (temperature slider behind a "Model default" switch, `Max tokens`, "View code" from `src/lib/playgroundExamples.ts`, which shows the platform API with a personal token, not the instance host)
  and `EmptyConversation.tsx` (starter prompts that fill the field and do not send).
  "Clear conversation" clears at once and offers Undo in the toast. The log is `aria-live="off"`; a hidden status announces a finished answer once.
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
- MCP servers: `/mcp-servers` (`components/mcp/McpServersPage.tsx`, `src/services/mcpService.ts`, types and the `allowedTools`/`usable` helpers in `src/types/mcp.ts`)
  lists the organization's remote MCP servers (`GET /v1alpha1/mcp/servers`), gated through `useOrg()`:
  an admin gets "Add MCP server", a "Try one" prefill (DeepWiki, Context7) on the empty state and a row menu `Actions for <name>`
  (Try in chat, Refresh tools, Edit tools, Change credential, Disable or Enable, Delete); a member gets the table read-only (Try in chat, View tools).
  `AddMcpServerDialog.tsx` has two steps: "Test connection" calls `mcpService.discover` and shows a refused URL or a failed connection inline (`role="alert"`, never a toast);
  step 2's `ToolPicker.tsx` (shared with `EditToolsDialog.tsx`) is "All tools, also new ones" (`allowed_tools: null`) or a checked selection, with a "changes data" badge only where the server says `read_only: false`.
  `CredentialFields.tsx` (shared with `ChangeCredentialDialog.tsx`) is None, Bearer token or Custom header; a stored credential is never shown again.
  `McpServerSheet.tsx` is the detail sheet of a row (a click on the name). `ConnectClientDialog.tsx` shows the platform's MCP endpoint for IDEs and SDKs:
  `${platformApiUrl(origin)}/v1alpha1/mcp`, the API host and never the UI's `/api/...` path, which is a session proxy and sends a token client to the login page; the token scope to use is `mcp` ("MCP tools only" in `CreateTokenDialog.tsx`).
  A server where each member brings their own credential (`credential_mode: "per_user"`, the "Each member brings their own" choice of the add dialog, with "Where to get a credential"):
  `ConnectCredentialDialog.tsx` ("Connect <name>", "Test and save"; a refusal shows inline, the value is never shown again) opens from the row menu
  ("Connect my credential", "Replace my credential", "Disconnect my credential") and from the Tools section of Chat, where such a server reads "needs your credential" with a `Connect <name>` button and turns on once connected.
  Scopes: the add dialog's "Who can use it" lists what the user may add (`addScopes` on the page: an admin the organization first, every non-viewer "Only me", a platform admin the platform), a member sees no choice and the note "Only you can use this server";
  a row shows "only me" or "platform", and its menu follows `server.can_change`, not the role. The MCP dialogs scroll inside the viewport (`max-h-[90vh] overflow-y-auto`): the add form grew past 720 px and its button could not be reached.
  OAuth sign-in: the add dialog's fourth Authentication choice, "OAuth: each member signs in" (optional client id, client secret and scopes), has no "Test connection" and no step 2, because nobody has a token yet; its button is "Add server".
  Such a server (`server.oauth`) reads "Sign in" / "Sign in again" / "Sign out of this server" in the row menu and "needs your sign-in" in Chat; `ConnectCredentialDialog` then shows "Sign in to <name>",
  which asks the backend for the authorization URL, keeps the current path in `sessionStorage` (`OAUTH_RETURN_KEY`) and leaves the page.
  The dialog names the host the member signs in at (`server.sign_in_host`). For a personal server the add dialog offers no credential mode: the credential is the owner's own.
  `/mcp-servers/oauth/callback` (`app/mcp-servers/oauth/callback/page.tsx`) is the redirect URI (it passes `iss` on when the authorization server sent it, and resolves the kept path against its own origin): a page, so a lost session goes through the login and comes back; it posts `code` and `state` once (a ref guards strict mode, a code is good once),
  returns to the kept path (same-origin paths only) with `?connected=<name>`, which the MCP page and the chat page turn into a toast and remove (Chat also turns the server on); an OAuth server has no "Change credential"; and shows a refusal as text in a `role="alert"`. `e2e/fast/mcp-oauth.spec.ts` makes the whole round trip against the mock.
  Import: the add dialog has two tabs, "Enter a URL" (the default, so the page object's locators hold) and "From the MCP registry" (`RegistrySearch.tsx`, hidden when `useRuntimeConfig().mcpRegistry` is false);
  "Use" calls the setters and returns to the form (`initial` is read by `useState` initializers only, and `reset()` also resets the tab), and the footer has no "Test connection" while the search shows. After a test whose error matches `401|Unauthorized` the dialog asks `offersOAuth` and offers "Use OAuth sign-in".
  Deploy: for an organization admin "Add MCP server" is a menu ("Connect a remote server", "Deploy from the catalog"); the trigger keeps the button's name, every other writer keeps the plain button, and the page object's `openAddDialog` selects the first item when a menu opened. The locator of the Name field is exact: "Header name" also contains "Name".
  `DeployMcpServerDialog.tsx` is choose, then settings (`SettingsFields.tsx` renders the entry's schema: text, password for a secret, a switch for a `flag`; `missingSettings` gates the button) and closes at once; a platform admin also imports an image entry as a draft there and opens `CatalogReviewDialog.tsx` (what would run, the importer's notes, arguments, port, path, egress, Publish or Deprecate, Sync, Remove).
  A deployed row says "deployed" and "runs on the platform", shows Starting with `LaunchProgress` or Failed with `ErrorBanner`, and the page polls (`usePolling`) while `isStarting(server)`; the sheet gets `McpInstancePanels.tsx` (Tools, Settings, Logs, Events; a kept secret shows "set; leave empty to keep it") and takes the row from the list again, because it changes while the sheet is open.
  The Logs tab of a deployed server shows for an admin only (the backend answers a member 403).
  `usable()` also needs `deploy.usable`, so Chat shows such a server as "starting" or "failed" and keeps it off. `e2e/fast/mcp-import.spec.ts`, `e2e/fast/mcp-deploy.spec.ts` (logs are stubbed), `e2e/cluster/mcp-deploy.spec.ts` (real Helm and poller on kind, the closed Service).
  A `Link` inside a `DropdownMenuItem asChild` needs `prefetch={false}`, as in `UserMenu.tsx`.
  The nav label is "MCP", short on purpose: one more long label wraps the header to a second line at 1280 px, and the chat page's bounded height (`100vh-18rem`) counts on one line.
  The page object's `openActions` waits until the previous menu has left the DOM: a click on the trigger while a menu animates out opens one that closes at once.
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
  a kind passes only the callbacks it supports, vector databases `onRestart` only, notebooks none;
  `onEditSettings` is the one item that opens a form, `EditSettingsDialog`, not a confirmation, so the page object has `openEditSettings()` next to `runAction`).
  `EditSettingsDialog` edits a deployed inference instance's CLI arguments and environment variables: the engine defaults of the instance payload (filtered by `chart_type`) overlaid with its own values
  (`lib/instanceSettings.ts` `rowsFromDefaults`; every own name stays own, so `max_model_len` is always sent back), only the kinds the engine reads (the payload's `settingsRead`, set by the backend from the controller; an empty list means no menu item, as on NIM and OPEA; never decide it from the engine name),
  saved through `PUT .../settings`. The rows are `components/models/SettingRows.tsx`, shared with the launch wizard: keep its `div.flex` per row, its placeholders and its button names, the launch page object finds rows by them, and never wrap the rows in another `div.flex`.
  `ToolCallingSwitch.tsx` (vLLM only, in both places) adds and removes `--enable-auto-tool-choice` and `--tool-call-parser <parser>` as ordinary rows, the parser guessed from the model reference (`guessToolParser`);
  a Langflow agent gets a 400 from vLLM without them.
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
