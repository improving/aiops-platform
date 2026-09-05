"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport, type UIMessage } from "ai";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { modelService } from "@/services/modelService";
import { loadMessages, saveMessages } from "@/lib/chatStorage";
import type { ChatTarget } from "@/types/models";
import { useToast } from "@/components/hooks/use-toast";
import { parseApiError } from "@/lib/utils";

function messageText(message: UIMessage): string {
  return message.parts
    .filter((part) => part.type === "text")
    .map((part) => part.text)
    .join("");
}

/** Reasoning models (qwen3, o-series) stream their thinking first. */
function messageReasoning(message: UIMessage): string {
  return message.parts
    .filter((part) => part.type === "reasoning")
    .map((part) => part.text)
    .join("");
}

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
  const [input, setInput] = useState("");

  useEffect(() => {
    modelService
      .getChatTargets()
      .then(setAllTargets)
      .catch((error) => toast(parseApiError(error)))
      .finally(() => setLoaded(true));
  }, [toast]);

  const targets = useMemo(
    () => allTargets.filter((t) => t.capability === "chat" && t.ready),
    [allTargets]
  );
  const deployedTargets = useMemo(
    () => targets.filter((t) => !t.provider_id),
    [targets]
  );
  const hostedTargets = useMemo(
    () => targets.filter((t) => !!t.provider_id),
    [targets]
  );
  const selected = targets.find((t) => t.name === target);

  const transport = useMemo(
    () =>
      new DefaultChatTransport({
        api: "/api/chat",
        prepareSendMessagesRequest: ({ messages }) => ({
          body: {
            messages,
            model: target,
            system,
            temperature: temperature === "" ? undefined : Number(temperature),
          },
        }),
      }),
    [target, system, temperature]
  );

  const { messages, sendMessage, setMessages, status, error, stop } = useChat({
    id: `${userKey}:${target || "no-target"}`,
    transport,
  });

  // History per target, in this browser only (design section 3.4).
  useEffect(() => {
    if (target) setMessages(loadMessages(userKey, target));
  }, [userKey, target, setMessages]);
  useEffect(() => {
    if (target && status === "ready") saveMessages(userKey, target, messages);
  }, [userKey, target, messages, status]);

  const busy = status === "submitted" || status === "streaming";
  const canSend = !!selected && !busy && input.trim().length > 0;

  const selectTarget = (value: string) => {
    setTarget(value);
    router.replace(`/chat?target=${value}`);
  };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSend) return;
    sendMessage({ text: input.trim() });
    setInput("");
  };

  const clear = () => {
    setMessages([]);
    if (target) saveMessages(userKey, target, []);
  };

  if (loaded && targets.length === 0) {
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
      <aside className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="chat-target">Target</Label>
          <Select value={target} onValueChange={selectTarget}>
            <SelectTrigger id="chat-target" aria-label="Target">
              <SelectValue placeholder="Pick an instance" />
            </SelectTrigger>
            <SelectContent>
              {deployedTargets.length > 0 && (
                <SelectGroup>
                  <SelectLabel>Deployed</SelectLabel>
                  {deployedTargets.map((t) => (
                    <SelectItem key={t.name} value={t.name}>
                      {t.label}
                    </SelectItem>
                  ))}
                </SelectGroup>
              )}
              {hostedTargets.length > 0 && (
                <SelectGroup>
                  <SelectLabel>Hosted</SelectLabel>
                  {hostedTargets.map((t) => (
                    <SelectItem key={t.name} value={t.name}>
                      {t.label}
                    </SelectItem>
                  ))}
                </SelectGroup>
              )}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="chat-system">System prompt</Label>
          <Textarea
            id="chat-system"
            value={system}
            onChange={(e) => setSystem(e.target.value)}
            rows={4}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="chat-temperature">Temperature</Label>
          <Input
            id="chat-temperature"
            type="number"
            min={0}
            max={2}
            step={0.1}
            value={temperature}
            placeholder="model default"
            onChange={(e) => setTemperature(e.target.value)}
          />
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={clear}
          disabled={messages.length === 0}
        >
          Clear conversation
        </Button>
      </aside>

      <section className="flex min-h-[60vh] flex-col">
        <div
          role="log"
          aria-label="Conversation"
          aria-live="polite"
          className="flex-1 space-y-3 overflow-y-auto rounded-md border p-4"
        >
          {messages.map((message) => (
            <div
              key={message.id}
              data-testid="chat-message"
              data-role={message.role}
              className={
                message.role === "user"
                  ? "ml-auto max-w-[80%] rounded-lg bg-primary px-3 py-2 text-primary-foreground"
                  : "mr-auto max-w-[80%] whitespace-pre-wrap rounded-lg bg-muted px-3 py-2"
              }
            >
              {messageReasoning(message) && (
                <details className="mb-1 text-xs text-muted-foreground">
                  <summary className="cursor-pointer">Thinking</summary>
                  <div className="mt-1 whitespace-pre-wrap">
                    {messageReasoning(message)}
                  </div>
                </details>
              )}
              {messageText(message)}
            </div>
          ))}
          {error && <p className="text-sm text-destructive">{error.message}</p>}
        </div>
        <form onSubmit={submit} className="mt-4 flex items-end gap-2">
          <div className="flex-1 space-y-2">
            <Label htmlFor="chat-input">Message</Label>
            <Textarea
              id="chat-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  submit(e);
                }
              }}
              rows={2}
              placeholder={selected ? "Ask something" : "Pick a target first"}
            />
          </div>
          {busy ? (
            <Button type="button" variant="outline" onClick={() => stop()}>
              Stop
            </Button>
          ) : (
            <Button type="submit" disabled={!canSend}>
              Send
            </Button>
          )}
        </form>
      </section>
    </div>
  );
}
