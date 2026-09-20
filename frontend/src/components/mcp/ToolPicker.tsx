"use client";

import { useState } from "react";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { McpTool } from "@/types/mcp";

/**
 * The "Allow" radio plus the filterable tool checklist, shared by
 * `AddMcpServerDialog` (step 2) and `EditToolsDialog`. `idPrefix` keeps
 * radio names and checkbox ids unique per instance.
 */
export function ToolPicker({
  idPrefix,
  tools,
  allowAll,
  onAllowAllChange,
  selected,
  onToggle,
}: {
  idPrefix: string;
  tools: McpTool[];
  allowAll: boolean;
  onAllowAllChange: (allowAll: boolean) => void;
  selected: Set<string>;
  onToggle: (name: string, checked: boolean) => void;
}) {
  const [filter, setFilter] = useState("");
  const needle = filter.trim().toLowerCase();
  const visible = needle
    ? tools.filter(
        (tool) =>
          tool.name.toLowerCase().includes(needle) ||
          tool.description.toLowerCase().includes(needle)
      )
    : tools;

  return (
    <div className="space-y-3">
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">Allow</legend>
        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:gap-4">
          <div className="flex items-center gap-2">
            <input
              type="radio"
              id={`${idPrefix}-allow-all`}
              name={`${idPrefix}-allow`}
              checked={allowAll}
              onChange={() => onAllowAllChange(true)}
              className="h-4 w-4"
            />
            <Label htmlFor={`${idPrefix}-allow-all`}>
              All tools, also new ones
            </Label>
          </div>
          <div className="flex items-center gap-2">
            <input
              type="radio"
              id={`${idPrefix}-allow-selected`}
              name={`${idPrefix}-allow`}
              checked={!allowAll}
              onChange={() => onAllowAllChange(false)}
              className="h-4 w-4"
            />
            <Label htmlFor={`${idPrefix}-allow-selected`}>
              Only the selected tools
            </Label>
          </div>
        </div>
      </fieldset>

      <div className="space-y-2">
        <Label htmlFor={`${idPrefix}-filter`}>Filter tools</Label>
        <Input
          id={`${idPrefix}-filter`}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter tools…"
        />
      </div>

      <div className="max-h-64 space-y-2 overflow-y-auto rounded-md border p-3">
        {visible.length === 0 ? (
          <p className="text-sm text-muted-foreground">No tools found.</p>
        ) : (
          visible.map((tool) => (
            <div key={tool.name} className="flex items-start space-x-2">
              <Checkbox
                id={`${idPrefix}-tool-${tool.name}`}
                checked={allowAll || selected.has(tool.name)}
                disabled={allowAll}
                onCheckedChange={(checked) =>
                  onToggle(tool.name, checked as boolean)
                }
              />
              <div className="flex-1 space-y-0.5">
                <div className="flex items-center gap-2">
                  <Label htmlFor={`${idPrefix}-tool-${tool.name}`}>
                    {tool.name}
                  </Label>
                  {tool.read_only === false && (
                    <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-800">
                      changes data
                    </span>
                  )}
                </div>
                {/* Two lines: a server's description is written for the
                    model and can run to twenty (Context7), which left
                    room for one tool in the list. The rest is a click
                    away, and the filter still searches all of it. */}
                <details className="group text-xs text-muted-foreground">
                  <summary className="cursor-pointer list-none">
                    <span className="line-clamp-2 group-open:line-clamp-none">
                      {tool.description}
                    </span>
                  </summary>
                </details>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
