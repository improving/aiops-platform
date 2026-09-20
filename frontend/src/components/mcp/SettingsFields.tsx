"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import type { McpSetting } from "@/types/mcp";

const ON = ["true", "1", "yes", "on"];

/**
 * The settings of a deployed MCP server, from the catalog entry's
 * schema: a text field for each variable, a password field for a secret
 * one, a switch for a setting that adds an argument. A secret that has a
 * value already (`kept`) can stay empty: empty keeps it, and its value
 * is never shown again.
 */
export function SettingsFields({
  idPrefix,
  schema,
  values,
  onChange,
  kept = [],
}: {
  idPrefix: string;
  schema: McpSetting[];
  values: Record<string, string>;
  onChange: (name: string, value: string) => void;
  kept?: string[];
}) {
  return (
    <div className="space-y-3">
      {schema.map((setting) => {
        const id = `${idPrefix}-${setting.name}`;
        const value = values[setting.name] ?? setting.default ?? "";
        if (setting.flag) {
          return (
            <div key={setting.name} className="flex items-center gap-2">
              <Switch
                id={id}
                checked={ON.includes(value.toLowerCase())}
                onCheckedChange={(on) =>
                  onChange(setting.name, on ? "true" : "false")
                }
              />
              <Label htmlFor={id}>{setting.label}</Label>
            </div>
          );
        }
        const isKept = setting.secret && kept.includes(setting.name);
        return (
          <div key={setting.name} className="space-y-1">
            <Label htmlFor={id}>
              {setting.label}
              {setting.required ? " *" : ""}
            </Label>
            <Input
              id={id}
              type={setting.secret ? "password" : "text"}
              autoComplete="off"
              value={values[setting.name] ?? (setting.secret ? "" : value)}
              placeholder={isKept ? "set; leave empty to keep it" : undefined}
              onChange={(e) => onChange(setting.name, e.target.value)}
            />
            {setting.help && (
              <p className="text-xs text-muted-foreground">{setting.help}</p>
            )}
            {setting.secret && (
              <p className="text-xs text-muted-foreground">
                Stored as a Kubernetes Secret and never shown again.
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** Required settings that have no value (a kept secret counts). */
export function missingSettings(
  schema: McpSetting[],
  values: Record<string, string>,
  kept: string[] = []
): McpSetting[] {
  return schema.filter(
    (s) =>
      s.required &&
      !s.flag &&
      !(values[s.name] ?? s.default ?? "").trim() &&
      !(s.secret && kept.includes(s.name))
  );
}
