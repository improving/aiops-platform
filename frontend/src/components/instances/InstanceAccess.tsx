"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CopyButton } from "@/components/CopyButton";
import {
  CodeExamplesDialog,
  type CodeExample,
} from "@/components/instances/CodeExamplesDialog";
import { useRuntimeConfig } from "@/lib/runtimeConfig";

/**
 * How to call one deployed model, split by where the caller sits.
 *
 * A client outside the cluster needs the gateway host and the API key.
 * A flow in Langflow needs neither: the Develop page has provisioned the
 * organization's LiteLLM into Langflow's "OpenAI Compatible" provider,
 * so Langflow lists this model by its LiteLLM name, and that name is the
 * one thing the Langflow tab has to say. Each tab answers its own
 * question with labelled values rather than a sentence describing them.
 */
export function InstanceAccess({
  endpoint,
  model,
  litellmModelName,
  onShowApiKey,
  apiKeyLoading,
}: {
  endpoint?: string | null;
  model: string;
  /** The name LiteLLM, and so Langflow, knows this instance by;
      null while the instance is not registered there. */
  litellmModelName: string | null;
  onShowApiKey: () => void;
  apiKeyLoading?: boolean;
}) {
  const { langflowUrl, loaded } = useRuntimeConfig();
  const apiBase = endpoint ? `${endpoint}/v1` : null;

  return (
    <Tabs defaultValue="api" className="w-full">
      <TabsList>
        <TabsTrigger value="api">API access</TabsTrigger>
        <TabsTrigger value="langflow" disabled={!litellmModelName}>
          Langflow
        </TabsTrigger>
      </TabsList>

      <TabsContent value="api" className="space-y-3">
        <dl
          role="group"
          aria-label="API access fields"
          className="divide-y text-sm"
        >
          {apiBase ? (
            <Field label="Base URL" value={apiBase} />
          ) : (
            // A state to name rather than a row to hide: the reader is
            // looking for it.
            <Row label="Base URL">
              <span className="text-sm text-muted-foreground">
                assigned once the instance is running
              </span>
            </Row>
          )}
          <Field label="Model" value={model} />
          <Row label="Auth">
            <code className="text-xs">x-api-key</code>
            <Button
              variant="outline"
              size="sm"
              loading={apiKeyLoading}
              onClick={onShowApiKey}
            >
              Show API key
            </Button>
          </Row>
        </dl>
        <p className="text-sm text-muted-foreground">
          The gateway rejects requests without the key, so the endpoint does not
          open in a browser.
        </p>
        {apiBase && (
          <CodeExamplesDialog
            examples={apiExamples(apiBase, model)}
            title="Call this model"
            description={`Replace <api key> with the instance key. Base URL and model are filled in.`}
          />
        )}
      </TabsContent>

      <TabsContent value="langflow" className="space-y-3">
        {litellmModelName && (
          <>
            <dl
              role="group"
              aria-label="Langflow fields"
              className="divide-y text-sm"
            >
              <Field label="Model name" value={litellmModelName} />
              <Row label="Provider">
                <span>OpenAI Compatible, served by LiteLLM</span>
              </Row>
            </dl>
            <p className="text-sm text-muted-foreground">
              Langflow lists this name in its Language Model component once the
              Develop page has synced your organization. No address and no key
              to paste: both are already in Langflow.
            </p>
            {loaded && langflowUrl && (
              <Button asChild variant="outline" size="sm">
                <Link href="/develop">Open Langflow</Link>
              </Button>
            )}
          </>
        )}
      </TabsContent>
    </Tabs>
  );
}

/** The same request in each language, opened on demand. */
function apiExamples(apiBase: string, model: string): CodeExample[] {
  return [
    {
      id: "curl",
      label: "curl",
      lang: "shell",
      code: `curl ${apiBase}/chat/completions \\
  -H "x-api-key: <api key>" -H "content-type: application/json" \\
  -d '{"model":"${model}","messages":[{"role":"user","content":"Hello"}]}'`,
    },
    {
      id: "python",
      label: "Python",
      lang: "python",
      code: `from openai import OpenAI

client = OpenAI(
    base_url="${apiBase}",
    api_key="unused",
    default_headers={"x-api-key": "<api key>"},
)
print(client.chat.completions.create(
    model="${model}",
    messages=[{"role": "user", "content": "Hello"}],
).choices[0].message.content)`,
    },
    {
      id: "typescript",
      label: "TypeScript",
      lang: "typescript",
      code: `import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "${apiBase}",
  apiKey: "unused",
  defaultHeaders: { "x-api-key": "<api key>" },
});
const res = await client.chat.completions.create({
  model: "${model}",
  messages: [{ role: "user", content: "Hello" }],
});
console.log(res.choices[0].message.content);`,
    },
  ];
}

/** Quiet structure: the values are the loudest thing here, not the box. */
function Row({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid grid-cols-[7rem_1fr] items-center gap-3 py-2">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="flex items-center gap-2">{children}</dd>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <Row label={label}>
      <span className="font-mono text-xs break-all">{value}</span>
      <CopyButton label={label} text={value} />
    </Row>
  );
}
