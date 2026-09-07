"use client";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useRuntimeConfig } from "@/lib/runtimeConfig";

interface NotConfiguredProps {
  /** Human readable name of the tool, for example "Grafana". */
  name: string;
  /** Build-time variable that can point at the tool (NEXT_PUBLIC_*). */
  envVar: string;
  /** Backend variable served by GET /v1alpha1/config/ui, for example GRAFANA_URL. */
  backendVar: string;
}

/** Placeholder shown where an iframe would embed an external tool. */
export default function NotConfigured({
  name,
  envVar,
  backendVar,
}: NotConfiguredProps) {
  const { loaded } = useRuntimeConfig();
  // Wait for the runtime config so the card never flashes before the
  // backend had a chance to name the tool.
  if (!loaded) return null;
  return (
    <Card className="max-w-md">
      <CardHeader>
        <CardTitle>{name} is not configured</CardTitle>
        <CardDescription>
          Set <code className="font-mono">{backendVar}</code> on the backend
          (served to the UI by{" "}
          <code className="font-mono">/v1alpha1/config/ui</code>) or{" "}
          <code className="font-mono">{envVar}</code> when the UI is built, then
          reload.
        </CardDescription>
      </CardHeader>
      <CardContent className="text-sm text-muted-foreground">
        The {name} URL must be reachable from the browser.
      </CardContent>
    </Card>
  );
}
