"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/components/hooks/use-toast";
import { ErrorBanner } from "@/components/instances/ErrorBanner";
import { EventsPanel } from "@/components/instances/EventsPanel";
import { LaunchProgress } from "@/components/instances/LaunchProgress";
import { LogsPanel } from "@/components/instances/LogsPanel";
import {
  SettingsFields,
  missingSettings,
} from "@/components/mcp/SettingsFields";
import { parseApiError } from "@/lib/utils";
import { mcpService } from "@/services/mcpService";
import type { LogsQuery } from "@/types/models";
import type { McpInstance, McpServer } from "@/types/mcp";

/**
 * What a deployed MCP server has and a remote one has not (W13): its
 * settings, its logs and its events, next to the tools that every server
 * shows. `tools` is the sheet's own tool list, so both kinds of server
 * render it in one place.
 */
export function McpInstancePanels({
  server,
  admin,
  tools,
  initialTab = "tools",
  onChanged,
}: {
  server: McpServer;
  admin: boolean;
  tools: React.ReactNode;
  initialTab?: string;
  onChanged: () => void | Promise<void>;
}) {
  const { toast } = useToast();
  const deploy = server.deploy!;
  const id = deploy.instance_id;
  const [instance, setInstance] = useState<McpInstance | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const loaded = await mcpService.getInstance(id);
        setInstance(loaded);
        setValues(loaded.settings);
      } catch (e) {
        setError(String(parseApiError(e).description));
      }
    })();
  }, [id]);

  const fetchLogs = useCallback(
    (query: LogsQuery) => mcpService.getInstanceLogs(id, query),
    [id]
  );
  const fetchEvents = useCallback(() => mcpService.getInstanceEvents(id), [id]);

  const run = async (work: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setError(null);
    try {
      const result = await work();
      if (result && typeof result === "object" && "schema" in result) {
        const changed = result as McpInstance;
        setInstance(changed);
        setValues(changed.settings);
      }
      await onChanged();
      toast({ title: "Success", description: done, variant: "success" });
    } catch (e) {
      setError(String(parseApiError(e).description));
    } finally {
      setBusy(false);
    }
  };

  const schema = instance?.schema ?? [];
  const kept = instance?.secret_settings ?? [];
  const missing = missingSettings(schema, values, kept);

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        {deploy.catalog_title} · runs on the platform
      </p>
      <ErrorBanner error={deploy.last_error} at={deploy.last_error_at} />
      <LaunchProgress launch={deploy.launch} ready={deploy.ready} />
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <Tabs
        defaultValue={!admin && initialTab === "logs" ? "events" : initialTab}
        className="w-full min-w-0"
      >
        <TabsList>
          <TabsTrigger value="tools">Tools</TabsTrigger>
          <TabsTrigger value="settings">Settings</TabsTrigger>
          {/* An MCP server can log what members asked: admins only. */}
          {admin && <TabsTrigger value="logs">Logs</TabsTrigger>}
          <TabsTrigger value="events">Events</TabsTrigger>
        </TabsList>
        <TabsContent value="tools">{tools}</TabsContent>
        <TabsContent value="settings" className="space-y-3">
          <p className="break-all font-mono text-xs text-muted-foreground">
            {deploy.image}
            {deploy.tag.startsWith("@") ? deploy.tag : `:${deploy.tag}`}
          </p>
          {admin ? (
            <>
              <SettingsFields
                idPrefix="mcp-instance"
                schema={schema}
                values={values}
                kept={kept}
                onChange={(key, value) =>
                  setValues((current) => ({ ...current, [key]: value }))
                }
              />
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  disabled={busy || missing.length > 0 || !instance}
                  loading={busy}
                  onClick={() =>
                    run(
                      () => mcpService.updateSettings(id, values),
                      "Saved; the server restarts"
                    )
                  }
                >
                  Save settings
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy}
                  onClick={() =>
                    run(
                      () => mcpService.restartInstance(id),
                      "The server restarts"
                    )
                  }
                >
                  Restart
                </Button>
                {deploy.upgrade_available && (
                  <Button
                    type="button"
                    variant="outline"
                    disabled={busy}
                    onClick={() =>
                      run(
                        () => mcpService.upgradeImage(id),
                        "Moved to the catalog's image; the server restarts"
                      )
                    }
                  >
                    Upgrade the image
                  </Button>
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                A change restarts the server; its tools are away for a moment.
              </p>
            </>
          ) : (
            <ul className="space-y-1 text-sm">
              {schema.map((s) => (
                <li key={s.name}>
                  {s.label}:{" "}
                  <span className="text-muted-foreground">
                    {s.secret
                      ? kept.includes(s.name)
                        ? "set"
                        : "not set"
                      : (instance?.settings[s.name] ?? "–")}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </TabsContent>
        {admin && (
          <TabsContent value="logs">
            <LogsPanel fetchLogs={fetchLogs} />
          </TabsContent>
        )}
        <TabsContent value="events">
          <EventsPanel fetchEvents={fetchEvents} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
