import type { CodeExample } from "@/components/instances/CodeExamplesDialog";

export type PlaygroundRequest = {
  apiUrl: string;
  model: string;
  system: string;
  temperature?: number;
  maxOutputTokens?: number;
};

const TOKEN = "<API_TOKEN>";

/** The platform API next to this UI: `ui.<domain>` is served beside
    `api.<domain>`; anywhere else (next dev) the reader fills it in. */
export function platformApiUrl(origin: string): string {
  try {
    const url = new URL(origin);
    if (url.hostname.startsWith("ui.")) {
      url.hostname = `api.${url.hostname.slice(3)}`;
      return url.origin;
    }
  } catch {
    // Not a URL: fall through to the placeholder.
  }
  return "https://<PLATFORM_API_HOST>";
}

function requestBody(request: PlaygroundRequest) {
  const messages = [
    ...(request.system.trim()
      ? [{ role: "system", content: request.system.trim() }]
      : []),
    { role: "user", content: "Hello" },
  ];
  return {
    model: request.model,
    messages,
    ...(request.temperature === undefined
      ? {}
      : { temperature: request.temperature }),
    ...(request.maxOutputTokens === undefined
      ? {}
      : { max_tokens: request.maxOutputTokens }),
  };
}

/**
 * The playground's own request, for a client: the platform's
 * OpenAI-compatible endpoint with a personal API token, the target's
 * name as the model, and the settings of the panel. Not the instance's
 * `inf-<id8>` host: that one is on the instance page, and it skips the
 * platform's per-user usage records.
 */
export function playgroundExamples(request: PlaygroundRequest): CodeExample[] {
  const body = requestBody(request);
  const extras = [
    ...(request.temperature === undefined
      ? []
      : [`    temperature=${request.temperature},`]),
    ...(request.maxOutputTokens === undefined
      ? []
      : [`    max_tokens=${request.maxOutputTokens},`]),
  ];
  return [
    {
      id: "curl",
      label: "curl",
      lang: "shell",
      code: [
        `curl ${request.apiUrl}/v1alpha1/chat/completions \\`,
        `  -H "Authorization: Bearer ${TOKEN}" \\`,
        `  -H "Content-Type: application/json" \\`,
        `  -d '${JSON.stringify(body, null, 2).replace(/'/g, "'\\''")}'`,
      ].join("\n"),
    },
    {
      id: "python",
      label: "Python",
      lang: "python",
      code: [
        "from openai import OpenAI",
        "",
        "client = OpenAI(",
        `    base_url="${request.apiUrl}/v1alpha1",`,
        `    api_key="${TOKEN}",`,
        ")",
        "response = client.chat.completions.create(",
        `    model=${JSON.stringify(request.model)},`,
        `    messages=${JSON.stringify(body.messages)},`,
        ...extras,
        ")",
        "print(response.choices[0].message.content)",
      ].join("\n"),
    },
  ];
}
