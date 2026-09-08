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
 * How to call one deployed model, split by where the caller runs.
 *
 * Two audiences were interleaved here before, which is what made the
 * section long: a client outside the cluster needs the gateway host and
 * the API key, and Langflow needs the in-cluster Service address and no
 * key at all. Neither reader wanted the other's half, and the base URL
 * and model were repeated four times between them.
 *
 * Each tab now answers one question, and answers it with labelled values
 * rather than a sentence describing them: the fields are the same shape
 * in both tabs, so the difference between them is the thing that stands
 * out.
 */
export function InstanceAccess({
  endpoint,
  clusterEndpoint,
  model,
  workloadChecksApiKey = false,
  onShowApiKey,
  apiKeyLoading,
}: {
  endpoint?: string | null;
  clusterEndpoint?: string | null;
  model: string;
  workloadChecksApiKey?: boolean;
  onShowApiKey: () => void;
  apiKeyLoading?: boolean;
}) {
  const { langflowUrl, loaded } = useRuntimeConfig();
  const apiBase = endpoint ? `${endpoint}/v1` : null;

  return (
    <Tabs defaultValue="api" className="w-full">
      <TabsList>
        <TabsTrigger value="api">API access</TabsTrigger>
        <TabsTrigger value="langflow" disabled={!clusterEndpoint}>
          Langflow
        </TabsTrigger>
      </TabsList>

      <TabsContent value="api" className="space-y-3">
        <AccessFields label="API access fields" baseUrl={apiBase} model={model}>
          <code className="text-xs">x-api-key</code>
          <RevealKeyButton loading={apiKeyLoading} onClick={onShowApiKey} />
        </AccessFields>
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
        {clusterEndpoint && (
          <>
            <AccessFields
              label="Langflow fields"
              baseUrl={`${clusterEndpoint}/v1`}
              model={model}
            >
              {workloadChecksApiKey ? (
                <>
                  <code className="text-xs">api_key</code>
                  <RevealKeyButton
                    loading={apiKeyLoading}
                    onClick={onShowApiKey}
                  />
                </>
              ) : (
                <span className="text-sm text-muted-foreground">
                  none needed
                </span>
              )}
            </AccessFields>
            <p className="text-sm text-muted-foreground">
              Langflow runs inside the cluster, so it reaches the model directly
              and skips the gateway
              {workloadChecksApiKey
                ? " -- but this engine checks the key itself, so it is still required."
                : ", which is what its check was."}{" "}
              Put these in an <strong>OpenAI</strong> model component.
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

/**
 * The three fields both tabs answer, in the same order and shape.
 *
 * One component rather than two copies, so the parallel structure the
 * reader compares across is a fact of the code and not a coincidence
 * that survives until someone edits one tab. Only the Auth cell differs
 * between them, which is exactly the difference worth seeing, so it is
 * the one thing passed in.
 *
 * Quiet structure: the values are the loudest thing here, not the box.
 */
function AccessFields({
  label,
  baseUrl,
  model,
  children,
}: {
  label: string;
  /** Null before the gateway assigns a host, which is a state to name
      rather than a row to hide: the reader is looking for it. */
  baseUrl: string | null;
  model: string;
  /** The Auth cell. */
  children: React.ReactNode;
}) {
  return (
    <dl role="group" aria-label={label} className="divide-y text-sm">
      {baseUrl ? (
        <Field label="Base URL" value={baseUrl} />
      ) : (
        <Row label="Base URL">
          <span className="text-sm text-muted-foreground">
            assigned once the instance is running
          </span>
        </Row>
      )}
      <Field label="Model" value={model} />
      <Row label="Auth">{children}</Row>
    </dl>
  );
}

function RevealKeyButton({
  loading,
  onClick,
}: {
  loading?: boolean;
  onClick: () => void;
}) {
  return (
    <Button variant="outline" size="sm" loading={loading} onClick={onClick}>
      Show API key
    </Button>
  );
}

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
