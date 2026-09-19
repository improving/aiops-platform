// The CLI arguments and environment variables of an instance as form
// rows, shared by the launch wizard and the Edit settings dialog. The
// backend merges the engine defaults at every render, so only a row the
// user changed or added is sent (`ownValues`).

import { normalize } from "@/lib/engineArgs";

export type SettingRow = {
  name: string;
  value: string;
  editable: boolean;
  /** Added by the user: its name can change and it can be deleted. */
  new: boolean;
  /** Differs from the engine default, so it is sent. */
  updated: boolean;
};

type EngineDefault = { name: string; defaultValue: string; editable: boolean };

export const EMPTY_ROW: SettingRow = {
  name: "",
  value: "",
  editable: true,
  new: true,
  updated: true,
};

/** The engine's defaults, overlaid with the instance's own values; a name
    the engine has no default for comes after them, as a row of its own. */
export function rowsFromDefaults(
  defaults: EngineDefault[],
  own: Record<string, string> | null | undefined = {}
): SettingRow[] {
  const mine = own ?? {};
  const known = new Set(defaults.map((d) => d.name));
  return [
    ...defaults.map((d) => ({
      name: d.name,
      value: mine[d.name] ?? d.defaultValue,
      editable: d.editable,
      new: false,
      updated: d.name in mine,
    })),
    ...Object.entries(mine)
      .filter(([name]) => !known.has(name))
      .map(([name, value]) => ({
        name,
        value,
        editable: true,
        new: true,
        updated: true,
      })),
  ];
}

/** What the request carries: the rows that are the user's own. */
export function ownValues(rows: SettingRow[]): Record<string, string> {
  return Object.fromEntries(
    rows
      .filter((row) => row.new || row.updated)
      .map((row) => [row.name.trim(), row.value])
  );
}

// --- tool calling (vLLM) -----------------------------------------------------

export const TOOL_FLAG = "--enable-auto-tool-choice";
export const TOOL_PARSER = "--tool-call-parser";

/** The parser vLLM documents for a model family, from the model's
    reference. `hermes` when nothing matches: it is the most common
    format, and the row stays editable. */
export function guessToolParser(reference: string): string {
  const name = reference.toLowerCase();
  // Before Llama: Hermes-3-Llama-3.1 is a Hermes model on a Llama base,
  // and a wrong parser fails silently.
  if (/hermes/.test(name)) return "hermes";
  if (/llama-?3|llama-?4/.test(name)) return "llama3_json";
  if (/mistral|mixtral/.test(name)) return "mistral";
  if (/granite/.test(name)) return "granite";
  if (/deepseek-?v3/.test(name)) return "deepseek_v3";
  if (/internlm/.test(name)) return "internlm";
  if (/jamba/.test(name)) return "jamba";
  return "hermes";
}

const isRow = (row: SettingRow, name: string) =>
  normalize(row.name) === normalize(name);

export function hasToolCalling(rows: SettingRow[]): boolean {
  return rows.some((row) => isRow(row, TOOL_FLAG));
}

/** The two rows added or removed together; a parser the user already
    typed is kept. */
export function withToolCalling(
  rows: SettingRow[],
  on: boolean,
  parser: string
): SettingRow[] {
  if (!on) {
    return rows.filter(
      (row) => !isRow(row, TOOL_FLAG) && !isRow(row, TOOL_PARSER)
    );
  }
  const added = [...rows];
  if (!hasToolCalling(rows)) {
    added.push({ ...EMPTY_ROW, name: TOOL_FLAG });
  }
  if (!rows.some((row) => isRow(row, TOOL_PARSER))) {
    added.push({ ...EMPTY_ROW, name: TOOL_PARSER, value: parser });
  }
  return added;
}

/** A name used twice: the request is a map, so one of the two rows would
    be dropped without a word. Undefined when every name is its own. */
export function duplicateName(rows: SettingRow[]): string | undefined {
  const seen = new Set<string>();
  for (const row of rows) {
    const name = row.name.trim();
    if (seen.has(name)) return name;
    seen.add(name);
  }
  return undefined;
}
