"use client";

import {
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { ClipboardCopyIcon } from "@radix-ui/react-icons";
import NotConfigured from "@/components/NotConfigured";
import { useCopy } from "@/components/CopyButton";
import { Button } from "@/components/ui/button";
import { Combobox } from "@/components/ui/combobox";
import { useRuntimeConfig } from "@/lib/runtimeConfig";
import { parseApiError } from "@/lib/utils";
import { langflowService } from "@/services/langflowService";
import { LangflowProvision } from "@/types/models";

/** The provider slot the platform manages in Langflow (utils/langflow.py). */
const PROVIDER = "OpenAI Compatible";

export default function Develop() {
  const { langflowUrl, loaded } = useRuntimeConfig();
  const [provision, setProvision] = useState<LangflowProvision | null>(null);
  const [problem, setProblem] = useState<ReactNode>(null);
  const [syncing, setSyncing] = useState(false);

  // Idempotent on the backend, so once per page load is right: the
  // variables follow the organization the caller has active, and a
  // switch reaches Langflow the next time this page opens. The ref
  // keeps two mounts (React strict mode in `next dev`) from racing two
  // creates of the same variable, which Langflow refuses.
  const inFlight = useRef(false);
  const sync = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setSyncing(true);
    setProblem(null);
    try {
      setProvision(await langflowService.provision());
    } catch (error) {
      setProblem(parseApiError(error).description);
    } finally {
      inFlight.current = false;
      setSyncing(false);
    }
  }, []);

  useEffect(() => {
    if (!loaded || !langflowUrl) return;
    (async () => {
      await sync();
    })();
  }, [loaded, langflowUrl, sync]);

  if (!loaded) return null;
  if (!langflowUrl) {
    return (
      <NotConfigured
        name="Langflow"
        envVar="NEXT_PUBLIC_LANGFLOW_URL"
        backendVar="LANGFLOW_URL"
      />
    );
  }

  return (
    // All the height the window has left, as on the chat page (a `fill`
    // Dashboard): the editor takes the rest (flex-1 with min-h-0, or the
    // frame keeps its own height and the panel above pushes it below
    // the fold).
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <OrganizationPanel
        provision={provision}
        problem={problem}
        syncing={syncing}
        onSync={sync}
        langflowUrl={langflowUrl}
      />
      <iframe
        src={langflowUrl}
        className="min-h-0 w-full flex-1"
        title="Develop Environment"
        allowFullScreen
      />
    </div>
  );
}

/**
 * One line above the editor: who you are in Langflow, the provider slot
 * the platform manages, and a "Models" picker that opens a searchable
 * list of the names to pick, so the editor keeps the page. Flows are
 * personal (Langflow has no organizations); the models and the key
 * follow the organization you have active.
 */
function OrganizationPanel({
  provision,
  problem,
  syncing,
  onSync,
  langflowUrl,
}: {
  provision: LangflowProvision | null;
  problem: ReactNode;
  syncing: boolean;
  onSync: () => void;
  langflowUrl: string;
}) {
  return (
    <section
      role="region"
      aria-label={`Langflow for ${provision?.organization ?? "your organization"}`}
      className="rounded-md border px-3 py-1.5 text-sm"
    >
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span>
          Signed in to Langflow as{" "}
          <strong>{provision?.langflow_user ?? "…"}</strong>
        </span>
        <span className="text-muted-foreground">
          Provider {PROVIDER} → LiteLLM
        </span>
        <ModelPicker provision={provision} />
        <Button variant="outline" size="sm" loading={syncing} onClick={onSync}>
          Sync again
        </Button>
        {/* Keycloak's login page refuses to render inside a frame
            (frame-ancestors 'self'), so an expired gateway session for
            the Langflow host shows "refused to connect" below until the
            user signs in on that host in a top-level tab. */}
        <a
          href={langflowUrl}
          target="_blank"
          rel="noreferrer"
          className="ml-auto text-xs text-muted-foreground underline"
          title="If the editor shows “refused to connect”, the gateway session for the Langflow host has expired: sign in there, then reload this page."
        >
          Open in a new tab
        </a>
      </div>
      {problem && (
        <p role="alert" className="mt-1 text-destructive">
          {problem}
        </p>
      )}
    </section>
  );
}

/**
 * "Models (N)" opens a searchable list of the organization's models by
 * the names Langflow lists under the managed provider; selecting one
 * copies its name. The search matches the name and the label, so
 * "qwen" finds `inst-<id8>` too.
 */
function ModelPicker({ provision }: { provision: LangflowProvision | null }) {
  const copy = useCopy();
  const models = provision?.models ?? [];
  return (
    <Combobox
      variant="ghost"
      className="w-auto"
      contentClassName="w-[32rem]"
      disabled={models.length === 0}
      label={<>Models{provision && ` (${models.length})`}</>}
      ariaLabel="Models"
      placeholder="Search models"
      emptyText="No model matches."
      items={models.map((m) => ({
        value: m.name,
        keywords: [m.label],
        onSelect: () => copy(m.name, `model name ${m.name}`),
        node: (
          <>
            <code className="shrink-0 text-xs">{m.name}</code>
            <span className="truncate text-xs text-muted-foreground">
              {m.label}
            </span>
            <ClipboardCopyIcon className="ml-auto shrink-0 opacity-60" />
          </>
        ),
      }))}
      footer={
        <p className="border-t px-3 py-2 text-xs text-muted-foreground">
          Select a name to copy it, then pick it in a Language Model component
          under the {PROVIDER} provider. The names and the key follow the
          organization you have active; flows stay yours.
        </p>
      }
    />
  );
}
