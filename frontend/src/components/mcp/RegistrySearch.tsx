"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { parseApiError } from "@/lib/utils";
import { mcpService } from "@/services/mcpService";
import type { McpRegistryPreview } from "@/types/mcp";

/**
 * Search of the official MCP registry, inside the add dialog. "Use"
 * only fills the connection form: the URL rule and the connection test
 * come after it, as for a typed URL, so an entry is never trusted
 * because it came from the registry. Entries are published by their
 * authors, and the note under the list says so.
 */
export function RegistrySearch({
  onUse,
}: {
  onUse: (entry: McpRegistryPreview) => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<McpRegistryPreview[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const search = async () => {
    setSearching(true);
    setError(null);
    try {
      setResults(await mcpService.searchRegistry(query.trim()));
    } catch (e) {
      setResults(null);
      setError(String(parseApiError(e).description));
    } finally {
      setSearching(false);
    }
  };

  return (
    <div className="space-y-3">
      <form
        className="flex items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void search();
        }}
      >
        <div className="flex-1 space-y-1">
          <Label htmlFor="mcp-registry-query">Search the MCP registry</Label>
          <Input
            id="mcp-registry-query"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="linear, grafana, postgres…"
          />
        </div>
        <Button type="submit" variant="outline" loading={searching}>
          Search
        </Button>
      </form>

      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}

      {results !== null && results.length === 0 && (
        <p className="text-sm text-muted-foreground">No entries found.</p>
      )}

      {results !== null && results.length > 0 && (
        <ul
          aria-label="Registry entries"
          className="max-h-72 space-y-2 overflow-y-auto rounded-md border p-2"
        >
          {results.map((entry) => (
            <li
              key={`${entry.name}@${entry.version ?? ""}`}
              className="flex items-start justify-between gap-3 rounded-md p-2 hover:bg-muted/50"
            >
              <div className="min-w-0 space-y-0.5">
                <p className="truncate text-sm font-medium">{entry.title}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {entry.name}
                  {entry.version ? ` · ${entry.version}` : ""}
                </p>
                {entry.description && (
                  <p className="line-clamp-2 text-xs text-muted-foreground">
                    {entry.description}
                  </p>
                )}
                {!entry.remote && (
                  <p className="text-xs text-muted-foreground">
                    {entry.remote_reason ??
                      (entry.deployable
                        ? "An image to deploy; a platform admin imports it into the catalog."
                        : (entry.deployable_reason ??
                          "No remote endpoint to connect to."))}
                  </p>
                )}
              </div>
              {entry.remote ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  aria-label={`Use ${entry.name}`}
                  disabled={entry.already_added}
                  onClick={() => onUse(entry)}
                >
                  {entry.already_added ? "Added" : "Use"}
                </Button>
              ) : (
                <span className="shrink-0 text-xs text-muted-foreground">
                  not usable yet
                </span>
              )}
            </li>
          ))}
        </ul>
      )}

      <p className="text-xs text-muted-foreground">
        These entries are published by their authors. The platform has not
        reviewed them; the connection test and your own check of the address
        come next.
      </p>
    </div>
  );
}
