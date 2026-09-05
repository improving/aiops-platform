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
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { modelService } from "@/services/modelService";
import type { InferenceInstance } from "@/types/models";
import { useToast } from "@/components/hooks/use-toast";
import { parseApiError } from "@/lib/utils";

const STORAGE_PREFIX = "aiops.chat.";

function loadMessages(instanceId: string): UIMessage[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_PREFIX + instanceId);
    return raw ? (JSON.parse(raw) as UIMessage[]) : [];
  } catch {
    return [];
  }
}

function saveMessages(instanceId: string, messages: UIMessage[]) {
  try {
    if (messages.length === 0) {
      window.localStorage.removeItem(STORAGE_PREFIX + instanceId);
    } else {
      window.localStorage.setItem(
        STORAGE_PREFIX + instanceId,
        JSON.stringify(messages)
      );
    }
  } catch {
    // Storage can be unavailable (private mode); the chat still works.
  }
}

function messageText(message: UIMessage): string {
  return message.parts
    .filter((part) => part.type === "text")
    .map((part) => part.text)
    .join("");
}

export default function ChatPanel() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { toast } = useToast();
  const [instances, setInstances] = useState<InferenceInstance[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [instanceId, setInstanceId] = useState(
    searchParams.get("instance") ?? ""
  );
  const [system, setSystem] = useState("");
  const [temperature, setTemperature] = useState(0.7);
  const [input, setInput] = useState("");

  useEffect(() => {
    modelService
      .getInferenceInstances()
      .then((list) => setInstances(list.filter((i) => i.ready && i.endpoint)))
      .catch((error) => toast(parseApiError(error)))
      .finally(() => setLoaded(true));
  }, [toast]);

  const instance = instances.find((i) => i.id === instanceId);
  const model = instance?.model.modelId ?? "";

  const transport = useMemo(
    () =>
      new DefaultChatTransport({
        api: "/api/chat",
        prepareSendMessagesRequest: ({ messages }) => ({
          body: { messages, instanceId, model, system, temperature },
        }),
      }),
    [instanceId, model, system, temperature]
  );

  const { messages, sendMessage, setMessages, status, error, stop } = useChat({
    id: instanceId || "no-instance",
    transport,
  });

  // History per instance, in this browser only (design section 3.4).
  useEffect(() => {
    if (instanceId) setMessages(loadMessages(instanceId));
  }, [instanceId, setMessages]);
  useEffect(() => {
    if (instanceId && status === "ready") saveMessages(instanceId, messages);
  }, [instanceId, messages, status]);

  const busy = status === "submitted" || status === "streaming";
  const canSend = !!instance && !busy && input.trim().length > 0;

  const selectTarget = (value: string) => {
    setInstanceId(value);
    router.replace(`/chat?instance=${value}`);
  };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSend) return;
    sendMessage({ text: input.trim() });
    setInput("");
  };

  const clear = () => {
    setMessages([]);
    if (instanceId) saveMessages(instanceId, []);
  };

  if (loaded && instances.length === 0) {
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
          <Select value={instanceId} onValueChange={selectTarget}>
            <SelectTrigger id="chat-target" aria-label="Target">
              <SelectValue placeholder="Pick an instance" />
            </SelectTrigger>
            <SelectContent>
              {instances.map((i) => (
                <SelectItem key={i.id} value={i.id}>
                  {i.model.name} · {i.engine.name}
                </SelectItem>
              ))}
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
            onChange={(e) => setTemperature(Number(e.target.value))}
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
              placeholder={instance ? "Ask something" : "Pick a target first"}
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
