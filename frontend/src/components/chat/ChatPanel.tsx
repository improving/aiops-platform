"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useChat } from "@ai-sdk/react";
import {
  DefaultChatTransport,
  getToolOrDynamicToolName,
  isToolUIPart,
  lastAssistantMessageIsCompleteWithApprovalResponses,
  lastAssistantMessageIsCompleteWithToolCalls,
} from "ai";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { ToastAction } from "@/components/ui/toast";
import {
  ChatMessage,
  hasContent,
  messageText,
} from "@/components/chat/ChatMessage";
import { ChatSettings } from "@/components/chat/ChatSettings";
import { Composer } from "@/components/chat/Composer";
import { EmptyConversation } from "@/components/chat/EmptyConversation";
import { TargetPicker } from "@/components/chat/TargetPicker";
import { contextUsed, type ChatUIMessage } from "@/lib/chatMetadata";
import { platformApiUrl, playgroundExamples } from "@/lib/playgroundExamples";
import { ChatTools } from "@/components/chat/ChatTools";
import { ConnectCredentialDialog } from "@/components/mcp/ConnectCredentialDialog";
import type { McpServer } from "@/types/mcp";
import { useToolServers } from "@/components/chat/useToolServers";
import { toolBudget } from "@/lib/toolBudget";
import { usePlaygroundFunctions } from "@/components/chat/usePlaygroundFunctions";
import { FunctionDialog } from "@/components/chat/FunctionDialog";
import { useOrg } from "@/hooks/useOrg";
import { modelService } from "@/services/modelService";
import { loadMessages, saveMessages } from "@/lib/chatStorage";
import {
  applyCompaction,
  forRequest,
  isMarker,
  lastMarkerIndex,
  markerInfo,
  markerMessage,
  planCompaction,
  shouldAutoCompact,
  transcript,
  transcriptBudget,
  undoCompaction,
} from "@/lib/compaction";
import { CompactionMarker } from "@/components/chat/CompactionMarker";
import type { ChatTarget } from "@/types/models";
import { useToast } from "@/components/hooks/use-toast";
import { parseApiError } from "@/lib/utils";

/** Turn the raw stream error into something a user can act on. */
function describeChatError(message: string): string {
  const text = message || "";
  if (/no endpoint yet|503/.test(text)) {
    return "The instance is still starting. Wait until it is Ready and retry.";
  }
  if (/Could not reach the tools/.test(text)) {
    return "The tools could not be reached, so nothing was sent to the model. Retry, or send the message without tools.";
  }
  if (/not reach|502|Connection error/.test(text)) {
    return "The model did not answer: the instance or the provider is unreachable. Check the instance page and retry.";
  }
  if (/interrupted|terminated|network|Failed to process/.test(text)) {
    return "The answer stream was interrupted before it finished. Retry; a cold model needs a moment to load.";
  }
  if (/401|Not signed in/.test(text)) {
    return "Your session has expired. Sign in again.";
  }
  return text;
}

const COMPACT_TIMEOUT_MS = 120_000;

export default function ChatPanel({ userKey }: { userKey: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { toast } = useToast();
  const [allTargets, setAllTargets] = useState<ChatTarget[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [target, setTarget] = useState(searchParams.get("target") ?? "");
  const [system, setSystem] = useState("");
  // Empty means the model's default: some hosted models reject any
  // other value, so nothing is sent unless the user sets one.
  const [temperature, setTemperature] = useState("");
  const [maxTokens, setMaxTokens] = useState("");
  const [input, setInput] = useState("");
  const [announcement, setAnnouncement] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    modelService
      .getChatTargets()
      .then(setAllTargets)
      .catch((error) => toast(parseApiError(error)))
      .finally(() => setLoaded(true));
  }, [toast]);

  // Listed: everything one can chat with. Pickable: what is ready. A
  // hosted model is always ready, so "not ready" is an instance starting.
  const chatTargets = useMemo(
    () => allTargets.filter((t) => t.capability === "chat"),
    [allTargets]
  );
  // The target of the URL, ready or not: a link from an instance that is
  // still starting must say so, not read as "no target".
  const requested = chatTargets.find((t) => t.name === target);
  const selected = requested?.ready ? requested : undefined;

  // Tools: the servers this user turned on, as far as this target and
  // this role can use them.
  const { role, isAdmin } = useOrg();
  const isViewer = role === "viewer";
  // `connected` is set by the OAuth callback page after a sign-in that
  // started here: the server the member just signed in to turns on, like
  // one connected with a pasted credential.
  const connected = searchParams.get("connected");
  const preselect = useMemo(
    () =>
      [...(searchParams.get("tools") ?? "").split(","), connected ?? ""].filter(
        Boolean
      ),
    [searchParams, connected]
  );
  useEffect(() => {
    if (!connected) return;
    toast({ title: `Signed in to ${connected}` });
    const rest = new URLSearchParams(searchParams.toString());
    rest.delete("connected");
    const query = rest.toString();
    router.replace(query ? `/chat?${query}` : "/chat");
  }, [connected, searchParams, router, toast]);
  const toolServers = useToolServers(userKey, preselect);
  const [connecting, setConnecting] = useState<McpServer | null>(null);
  const toolsBlocked = isViewer || selected?.tools === false;
  const activeTools = useMemo(
    () => (toolsBlocked ? [] : toolServers.active),
    [toolsBlocked, toolServers.active]
  );
  // Functions typed in the playground; `editing` is the name in the
  // dialog, "" for a new one, undefined when it is closed.
  const typed = usePlaygroundFunctions(userKey);
  // What the tools that are on take of this target's window, before a
  // message is sent: a server with many tools can leave a small model no
  // room for the conversation.
  const budget = useMemo(
    () =>
      toolBudget(
        toolServers.servers,
        activeTools,
        toolsBlocked ? [] : typed.functions.filter((f) => f.enabled),
        selected?.context_length
      ),
    [
      toolServers.servers,
      activeTools,
      toolsBlocked,
      typed.functions,
      selected?.context_length,
    ]
  );
  const [editing, setEditing] = useState<string | undefined>(undefined);
  const typedSources = useMemo(
    () => (toolsBlocked ? [] : typed.sources),
    [toolsBlocked, typed.sources]
  );
  const typedNames = useMemo(
    () => new Set(typed.functions.map((f) => f.name)),
    [typed.functions]
  );
  // `useChat` keeps the first `sendAutomaticallyWhen` it gets, so that
  // callback reads the names through a ref, kept current by an effect.
  const typedNamesRef = useRef<ReadonlySet<string>>(typedNames);
  useEffect(() => {
    typedNamesRef.current = typedNames;
  }, [typedNames]);
  const temperatureValue = temperature === "" ? undefined : Number(temperature);
  const maxOutputTokens =
    Number(maxTokens) >= 1 ? Math.floor(Number(maxTokens)) : undefined;

  const transport = useMemo(
    () =>
      new DefaultChatTransport<ChatUIMessage>({
        api: "/api/chat",
        prepareSendMessagesRequest: ({ messages, body }) => ({
          body: {
            // A compacted conversation: the summary of the last marker,
            // and the turns after it. The turns above the marker stay in
            // the browser and do not go to the model.
            ...forRequest(messages),
            model: target,
            system,
            temperature: temperatureValue,
            maxOutputTokens,
            toolSources: [
              ...activeTools.map((server) => ({ type: "mcp", server })),
              ...typedSources,
            ],
            approveTools: toolServers.askFirst,
            // One request's own fields last: "Send without tools" sends
            // an empty `toolSources` through `regenerate({ body })`.
            ...body,
          },
        }),
      }),
    [
      target,
      system,
      temperatureValue,
      maxOutputTokens,
      activeTools,
      typedSources,
      toolServers.askFirst,
    ]
  );

  const {
    messages,
    sendMessage,
    setMessages,
    status,
    error,
    stop,
    regenerate,
    clearError,
    addToolApprovalResponse,
    addToolOutput,
  } = useChat<ChatUIMessage>({
    id: `${userKey}:${target || "no-target"}`,
    transport,
    // The conversation goes back by itself in two cases: every waiting
    // tool call has its yes or no, or the user gave the result of a
    // function they typed. Not for every finished tool step: a loop the
    // route cut at its step limit would go on without end.
    sendAutomaticallyWhen: (options) =>
      lastAssistantMessageIsCompleteWithApprovalResponses(options) ||
      (lastStepCallsATypedFunction(options.messages, typedNamesRef.current) &&
        lastAssistantMessageIsCompleteWithToolCalls(options)),
    // The log is not a live region (it would read every token aloud);
    // a finished answer is announced once instead.
    onFinish: () => setAnnouncement(`Answer received at ${timeNow()}`),
  });

  // History per target, in this browser only (design section 3.4).
  useEffect(() => {
    if (target) setMessages(loadMessages(userKey, target));
  }, [userKey, target, setMessages]);
  useEffect(() => {
    if (target && status === "ready") saveMessages(userKey, target, messages);
  }, [userKey, target, messages, status]);

  // Follow the newest message, unless the user has scrolled up to read
  // back: a stream that yanked the view down would make history
  // unreadable. `pinned` is a ref, not state, so scrolling never renders.
  const logRef = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);

  const onLogScroll = useCallback(() => {
    const log = logRef.current;
    if (!log) return;
    const fromBottom = log.scrollHeight - log.scrollTop - log.clientHeight;
    pinned.current = fromBottom < 80;
  }, []);

  useEffect(() => {
    const log = logRef.current;
    if (log && pinned.current) log.scrollTop = log.scrollHeight;
  }, [messages, error, status]);

  // A new conversation starts at the bottom again.
  useEffect(() => {
    pinned.current = true;
  }, [target]);

  const [compacting, setCompacting] = useState(false);
  const busy = status === "submitted" || status === "streaming";
  // While a summary is being written nothing else may change the
  // conversation: it is decided against the turns as they are.
  const locked = busy || compacting;
  const canSend = !!selected && !locked && input.trim().length > 0;

  const last = messages.at(-1);
  // Sent, and nothing to show yet: the request is on its way, or the
  // answer has started without a first token.
  const waiting =
    status === "submitted" ||
    (status === "streaming" && last?.role === "assistant" && !hasContent(last));
  const lastUserId = messages.findLast((m) => m.role === "user")?.id;
  const lastAssistant = messages.findLast((m) => m.role === "assistant");

  const selectTarget = (value: string) => {
    setTarget(value);
    router.replace(`/chat?target=${value}`);
  };

  // Compaction: a summary of the older turns takes their place in what
  // the model gets (`src/lib/compaction.ts`).
  const [autoCompact, setAutoCompact] = useState(false);
  // localStorage is the browser's: read it after mount, never in render.
  useEffect(() => {
    (async () => {
      try {
        setAutoCompact(
          window.localStorage.getItem(`aiops.chat.compact.${userKey}`) === "on"
        );
      } catch {
        // Without storage the switch starts off.
      }
    })();
  }, [userKey]);
  const changeAutoCompact = (on: boolean) => {
    setAutoCompact(on);
    try {
      window.localStorage.setItem(
        `aiops.chat.compact.${userKey}`,
        on ? "on" : "off"
      );
    } catch {
      // The choice then holds for this page only.
    }
  };

  const plan = useMemo(() => planCompaction(messages), [messages]);
  // The page: the turns above the last marker (collapsed), the marker,
  // and the live turns. An older marker is inside the collapsed part as
  // nothing: only the last summary is in use.
  const markerAt = lastMarkerIndex(messages);
  const marker = markerAt >= 0 ? messages[markerAt] : undefined;
  const hidden = messages
    .slice(0, Math.max(markerAt, 0))
    .filter((m) => !isMarker(m));
  const live = messages.slice(markerAt + 1);
  // After a compaction the newest answer still carries the count of the
  // long conversation; the meter waits for the next answer.
  const meterUsed =
    marker && markerInfo(marker)?.atMessageId === lastAssistant?.id
      ? undefined
      : contextUsed(lastAssistant?.metadata);

  // One summary call at a time, and it ends with the conversation it
  // belongs to: a switch of target, or leaving the page, aborts it.
  const compactAbort = useRef<AbortController | null>(null);
  useEffect(() => () => compactAbort.current?.abort(), [target]);
  // After Undo of an automatic compaction: not again before a new answer.
  const noAutoFor = useRef<string | undefined>(undefined);

  /**
   * "done", "failed" (nothing changed; a message still goes, with the
   * whole history) or "moved": the conversation is no longer the one
   * that was summarized, so the summary is dropped and nothing must be
   * sent in its name.
   *
   * Everything this reads comes from the render of the click, and the
   * call can take two minutes. So what it writes is decided against the
   * conversation as it is THEN (`setMessages` with a function), and only
   * for the same target: `setMessages` and `sendMessage` act on the chat
   * of the moment they run, which after a switch is another target's.
   */
  const compact = async (
    automatic: boolean
  ): Promise<"done" | "failed" | "moved"> => {
    const current = planCompaction(messages);
    if (!current || !target || compacting) return "failed";
    const from = target;
    const cutId = messages[current.at].id;
    const oldIds = current.old.map((m) => m.id);
    const controller = new AbortController();
    compactAbort.current = controller;
    setCompacting(true);
    try {
      const response = await fetch("/api/chat/compact", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // The composer waits for this; a summary that does not come in
        // two minutes will not come, and the message must still go.
        signal: AbortSignal.any([
          controller.signal,
          AbortSignal.timeout(COMPACT_TIMEOUT_MS),
        ]),
        body: JSON.stringify({
          model: target,
          window: selected?.context_length ?? null,
          transcript: transcript(
            current,
            transcriptBudget(selected?.context_length)
          ),
        }),
      });
      const answer = (await response.json()) as {
        summary?: string;
        summaryTokens?: number;
        detail?: string;
      };
      if (targetRef.current !== from) return "moved";
      if (!response.ok || !answer.summary) {
        throw new Error(
          answer.detail ?? `The summary failed (${response.status})`
        );
      }
      const marker = markerMessage(answer.summary, {
        covered: current.old.length,
        tokensBefore: contextUsed(lastAssistant?.metadata),
        summaryTokens: answer.summaryTokens,
        atMessageId: lastAssistant?.id,
        automatic,
      });
      let applied = false;
      setMessages((now) => {
        // Still the turns that were summarized, in front of the same
        // turn of the user? Anything else (cleared, edited, a marker
        // undone) and the summary stands for a conversation that is gone.
        const at = now.findIndex((m) => m.id === cutId);
        const start = lastMarkerIndex(now) + 1;
        const same =
          at >= 0 &&
          at - start === oldIds.length &&
          oldIds.every((id, k) => now[start + k]?.id === id);
        if (!same) return now;
        applied = true;
        return applyCompaction(now, { ...current, at }, marker);
      });
      if (!applied) {
        toast({
          title: "The conversation changed",
          description: "The summary was for the earlier turns; it was dropped.",
        });
        return "failed";
      }
      setAnnouncement(
        `The earlier conversation was summarized at ${timeNow()}`
      );
      return "done";
    } catch (e) {
      if (controller.signal.aborted || targetRef.current !== from) {
        return "moved";
      }
      toast({
        title: "The conversation was not compacted",
        description: `${e instanceof Error ? e.message : e}. ${
          automatic ? "Your message goes with the whole history." : ""
        }`.trim(),
        variant: "destructive",
      });
      return "failed";
    } finally {
      if (compactAbort.current === controller) compactAbort.current = null;
      setCompacting(false);
      // "Compact" leaves the page when nothing is left to compact; the
      // focus must not fall to the document.
      if (!automatic) inputRef.current?.focus();
    }
  };

  const submit = async () => {
    if (!canSend) return;
    const text = input.trim();
    setInput("");
    if (
      autoCompact &&
      noAutoFor.current !== lastAssistant?.id &&
      shouldAutoCompact(
        messages,
        contextUsed(lastAssistant?.metadata),
        selected?.context_length,
        lastAssistant?.id
      )
    ) {
      if ((await compact(true)) === "moved") {
        // Another target's chat is on the page now: this message was for
        // the one that was left. It goes back into the field.
        setInput(text);
        return;
      }
    }
    sendMessage({ text });
  };

  const onRegenerate = useCallback(
    (messageId: string) => {
      clearError();
      regenerate({ messageId });
    },
    [clearError, regenerate]
  );

  const onToolResult = useCallback(
    (
      tool: string,
      toolCallId: string,
      result: { output: string } | { errorText: string }
    ) => {
      if ("output" in result) {
        addToolOutput({
          tool: tool as never,
          toolCallId,
          output: result.output as never,
        });
      } else {
        addToolOutput({
          state: "output-error",
          tool: tool as never,
          toolCallId,
          errorText: result.errorText,
        });
      }
    },
    [addToolOutput]
  );

  const onToolApproval = useCallback(
    (id: string, approved: boolean) => {
      addToolApprovalResponse({ id, approved });
    },
    [addToolApprovalResponse]
  );

  const continueAnswer = useCallback(() => {
    sendMessage({ text: "Continue." });
  }, [sendMessage]);

  // Back into the field, and the turn (with its answer) out of the log:
  // sending it again continues from what came before it.
  const onEdit = useCallback(
    (messageId: string) => {
      const index = messages.findIndex((m) => m.id === messageId);
      if (index < 0) return;
      clearError();
      setInput(messageText(messages[index]));
      setMessages(messages.slice(0, index));
      inputRef.current?.focus();
    },
    [messages, clearError, setMessages]
  );

  // An Undo that arrives after a switch of target restores the stored
  // history only, not the log on screen.
  const targetRef = useRef(target);
  useEffect(() => {
    targetRef.current = target;
  }, [target]);

  // At once, with a way back: a confirmation would be in the way every
  // time, and the history is one click from gone otherwise.
  const clear = () => {
    const removed = messages;
    const from = target;
    clearError();
    setMessages([]);
    if (from) saveMessages(userKey, from, []);
    toast({
      title: "Conversation cleared",
      action: (
        <ToastAction
          altText="Undo"
          onClick={() => {
            saveMessages(userKey, from, removed);
            if (from === targetRef.current) setMessages(removed);
          }}
        >
          Undo
        </ToastAction>
      ),
    });
  };
  const examples = useMemo(
    () =>
      selected
        ? playgroundExamples({
            apiUrl: platformApiUrl(
              typeof window === "undefined" ? "" : window.location.origin
            ),
            model: selected.name,
            system,
            temperature: temperatureValue,
            maxOutputTokens,
            mcpServers: activeTools,
          })
        : [],
    [selected, system, temperatureValue, maxOutputTokens, activeTools]
  );

  if (loaded && chatTargets.length === 0) {
    return (
      <p className="text-muted-foreground">
        No running inference instance. Launch one from the{" "}
        <Link href="/models/catalog" className="underline">
          Model catalog
        </Link>
        .
      </p>
    );
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
      {editing !== undefined && (
        <FunctionDialog
          key={editing || "new"}
          initial={typed.functions.find((f) => f.name === editing) ?? null}
          otherNames={typed.functions
            .map((f) => f.name)
            .filter((n) => n !== editing)}
          onOpenChange={(open) => !open && setEditing(undefined)}
          onSave={typed.save}
          onDelete={typed.remove}
        />
      )}
      <ConnectCredentialDialog
        server={connecting}
        onOpenChange={(open) => !open && setConnecting(null)}
        onSaved={(server) => {
          toolServers.replace(server);
          // Connected in order to use it: turn it on.
          toolServers.toggle(server.name, true);
        }}
      />
      {/* The same bound as the conversation: with the Tools section the
          panel can be taller than the window, and it must scroll in
          itself, not make the page scroll the composer away. */}
      <aside className="min-w-0 space-y-4 lg:max-h-[calc(100vh-18rem)] lg:min-h-[24rem] lg:overflow-y-auto lg:pr-1">
        <div className="space-y-2">
          <Label>Target</Label>
          <TargetPicker
            targets={chatTargets}
            selected={requested}
            onSelect={selectTarget}
          />
        </div>
        <ChatSettings
          system={system}
          onSystemChange={setSystem}
          temperature={temperature}
          onTemperatureChange={setTemperature}
          maxTokens={maxTokens}
          onMaxTokensChange={setMaxTokens}
          autoCompact={autoCompact}
          onAutoCompactChange={changeAutoCompact}
          windowKnown={!!selected?.context_length}
          tools={
            <ChatTools
              servers={toolServers.servers}
              selected={toolServers.selected}
              active={activeTools}
              onToggle={toolServers.toggle}
              targetTools={selected?.tools}
              engine={selected?.engine}
              settingsHref={
                selected?.instance_id
                  ? `/models/endpoints/${selected.instance_id}`
                  : undefined
              }
              isViewer={isViewer}
              isAdmin={isAdmin}
              budget={budget}
              onConnect={setConnecting}
              askFirst={toolServers.askFirst}
              onAskFirstChange={toolServers.setAskFirst}
              functions={typed.functions}
              onFunctionToggle={typed.toggle}
              onFunctionEdit={(name) => setEditing(name ?? "")}
            />
          }
          examples={examples}
          onClear={clear}
          canClear={messages.length > 0 && !compacting}
        />
      </aside>

      {/* A bounded height, not a minimum: with only min-h the section grew
          with the conversation, so the log below never became scrollable
          and the composer was pushed off the bottom of the page. The 18rem
          is the shell around it (header, title, footer), measured at 274px;
          min-h keeps it usable when the viewport is short. */}
      <section className="flex h-[calc(100vh-18rem)] min-h-[24rem] min-w-0 flex-col">
        <div
          ref={logRef}
          onScroll={onLogScroll}
          role="log"
          aria-label="Conversation"
          aria-live="off"
          // min-h-0 lets this flex child shrink below its content height,
          // which is what makes overflow-y-auto scroll instead of grow.
          className="min-h-0 flex-1 overflow-y-auto rounded-md border p-4"
        >
          {/* A reading width: a bubble across a wide screen runs past 120
              characters a line. */}
          <div className="mx-auto flex min-h-full max-w-3xl flex-col gap-3">
            {messages.length === 0 && selected && !error && (
              <EmptyConversation
                target={selected}
                onPick={(prompt) => {
                  setInput(prompt);
                  inputRef.current?.focus();
                }}
              />
            )}
            {hidden.length > 0 && (
              <details
                data-testid="chat-compacted"
                className="rounded-md border border-dashed p-2 text-xs text-muted-foreground"
              >
                <summary className="cursor-pointer">
                  Earlier conversation ({hidden.length}{" "}
                  {hidden.length === 1 ? "message" : "messages"}, not sent to
                  the model any more)
                </summary>
                <div className="mt-3 flex flex-col gap-3 opacity-70">
                  {hidden.map((message) => (
                    <ChatMessage
                      key={message.id}
                      message={message}
                      streaming={false}
                      typedFunctions={typedNames}
                    />
                  ))}
                </div>
              </details>
            )}
            {marker && (
              <CompactionMarker
                summary={messageText(marker)}
                info={markerInfo(marker)!}
                onUndo={
                  locked
                    ? undefined
                    : () => {
                        // Undone by hand: with the switch on, the next
                        // send must not compact the same turns again.
                        noAutoFor.current = lastAssistant?.id;
                        setMessages((now) => undoCompaction(now, marker.id));
                      }
                }
              />
            )}
            {live.map((message) => (
              <ChatMessage
                key={message.id}
                message={message}
                streaming={busy && message.id === last?.id}
                onRegenerate={
                  !locked &&
                  message.id === lastAssistant?.id &&
                  message === last
                    ? onRegenerate
                    : undefined
                }
                onEdit={
                  !locked && message.id === lastUserId ? onEdit : undefined
                }
                onContinue={
                  !locked && message === last ? continueAnswer : undefined
                }
                onToolApproval={
                  !locked && message === last ? onToolApproval : undefined
                }
                typedFunctions={typedNames}
                onToolResult={
                  !locked && message === last ? onToolResult : undefined
                }
              />
            ))}
            {waiting && (
              <div
                role="status"
                aria-label="Waiting for the model"
                className="flex w-fit items-center gap-1 rounded-lg bg-muted px-3 py-3"
              >
                {[0, 150, 300].map((delay) => (
                  <span
                    key={delay}
                    className="size-1.5 animate-bounce rounded-full bg-muted-foreground/70"
                    style={{ animationDelay: `${delay}ms` }}
                  />
                ))}
              </div>
            )}
            {error && (
              <div
                role="alert"
                className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm"
              >
                <p className="font-medium text-destructive">
                  The answer did not arrive.
                </p>
                <p className="mt-1 text-muted-foreground">
                  {describeChatError(error.message)}
                </p>
                <div className="mt-2 flex gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      clearError();
                      regenerate();
                    }}
                  >
                    Retry
                  </Button>
                  {/Could not reach the tools/.test(error.message) && (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        clearError();
                        regenerate({ body: { toolSources: [] } });
                      }}
                    >
                      Send without tools
                    </Button>
                  )}
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={() => clearError()}
                  >
                    Dismiss
                  </Button>
                </div>
              </div>
            )}
          </div>
        </div>
        <p role="status" className="sr-only">
          {announcement}
        </p>
        <Composer
          inputRef={inputRef}
          value={input}
          onChange={setInput}
          onSubmit={submit}
          onStop={stop}
          busy={busy}
          canSend={canSend}
          placeholder={
            selected
              ? "Ask something"
              : requested
                ? "This instance is still starting"
                : "Pick a target first"
          }
          contextUsed={meterUsed}
          onCompact={
            plan && selected && !busy ? () => compact(false) : undefined
          }
          compacting={compacting}
          contextLength={selected?.context_length}
          toolServers={activeTools.length}
        />
      </section>
    </div>
  );
}

/** The last step of the last answer holds a call of a function the user
    typed: only then does a complete set of tool results go back by
    itself (see `sendAutomaticallyWhen`). */
function lastStepCallsATypedFunction(
  messages: ChatUIMessage[],
  typed: ReadonlySet<string>
): boolean {
  const last = messages.at(-1);
  if (!last || last.role !== "assistant") return false;
  const from = last.parts.findLastIndex((p) => p.type === "step-start");
  return last.parts
    .slice(from + 1)
    .some((p) => isToolUIPart(p) && typed.has(getToolOrDynamicToolName(p)));
}

function timeNow(): string {
  return new Date().toLocaleTimeString();
}
