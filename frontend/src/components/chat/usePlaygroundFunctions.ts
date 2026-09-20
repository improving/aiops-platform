import { useCallback, useEffect, useMemo, useState } from "react";
import { FUNCTION_NAME, type FunctionToolSource } from "@/lib/toolSources";

/** A function typed in the playground. `parameters` is kept as the text
    the user wrote, so an edit shows what they typed. */
export type PlaygroundFunction = {
  name: string;
  description: string;
  parameters: string;
  enabled: boolean;
};

export const EXAMPLE_PARAMETERS = JSON.stringify(
  {
    type: "object",
    properties: { city: { type: "string", description: "The city's name" } },
    required: ["city"],
  },
  null,
  2
);

const KEY_PREFIX = "aiops.chat.functions.";

function storageKey(userKey: string): string {
  return `${KEY_PREFIX}${encodeURIComponent(userKey)}`;
}

/** What is wrong with a definition, or "" when it can be sent. */
export function functionProblem(
  fn: Pick<PlaygroundFunction, "name" | "parameters">,
  others: string[]
): string {
  if (!FUNCTION_NAME.test(fn.name)) {
    return "The name is letters, digits and _, and starts with a letter or _.";
  }
  if (others.includes(fn.name)) return "A function with this name exists.";
  try {
    const schema: unknown = JSON.parse(fn.parameters);
    if (
      !schema ||
      typeof schema !== "object" ||
      Array.isArray(schema) ||
      (schema as { type?: unknown }).type !== "object"
    ) {
      return 'The parameters are a JSON Schema with "type": "object".';
    }
  } catch {
    return "The parameters are not valid JSON.";
  }
  return "";
}

/**
 * Functions the user typed to try a function-calling prompt: the model
 * may call them, nothing runs, and the user types each result. They are
 * the user's and the browser's, like the choice of tool servers.
 */
export function usePlaygroundFunctions(userKey: string) {
  const [functions, setFunctions] = useState<PlaygroundFunction[]>([]);

  useEffect(() => {
    (async () => {
      try {
        const raw = localStorage.getItem(storageKey(userKey));
        const value: unknown = raw ? JSON.parse(raw) : [];
        setFunctions(
          Array.isArray(value) ? (value as PlaygroundFunction[]) : []
        );
      } catch {
        setFunctions([]);
      }
    })();
  }, [userKey]);

  const update = useCallback(
    (next: PlaygroundFunction[]) => {
      setFunctions(next);
      try {
        localStorage.setItem(storageKey(userKey), JSON.stringify(next));
      } catch {
        // Only the convenience is lost.
      }
    },
    [userKey]
  );

  const save = useCallback(
    (fn: PlaygroundFunction, previousName?: string) => {
      const rest = functions.filter(
        (f) => f.name !== (previousName ?? fn.name)
      );
      update([...rest, fn].sort((a, b) => a.name.localeCompare(b.name)));
    },
    [functions, update]
  );

  const remove = useCallback(
    (name: string) => update(functions.filter((f) => f.name !== name)),
    [functions, update]
  );

  const toggle = useCallback(
    (name: string, on: boolean) =>
      update(
        functions.map((f) => (f.name === name ? { ...f, enabled: on } : f))
      ),
    [functions, update]
  );

  // What a request carries: the enabled ones that still parse.
  const sources = useMemo<FunctionToolSource[]>(
    () =>
      functions
        .filter((f) => f.enabled && functionProblem(f, []) === "")
        .map((f) => ({
          type: "function",
          name: f.name,
          description: f.description,
          parameters: JSON.parse(f.parameters) as Record<string, unknown>,
        })),
    [functions]
  );

  return { functions, sources, save, remove, toggle };
}
