"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Label } from "@/components/ui/label";
import { VectorDBInstanceSchema } from "@/types/vectordb";
import { vectorDBService } from "@/services/vectorDBService";
import { useToast } from "@/components/hooks/use-toast";
import { DeleteButton } from "@/components/DeleteButton";
import { CopyButton } from "@/components/CopyButton";
import { CodeSnippet } from "@/components/CodeSnippet";
import { DetailSkeleton } from "@/components/LoadingState";
import { DisplayCard } from "@/components/ui/DisplayCard";
import { GetVectorDBIcon, parseApiError } from "@/lib/utils";
import { isNonTerminal, usePolling } from "@/hooks/usePolling";
import { ShowCredentialButton } from "@/components/vector-databases/ShowCredentialButton";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-2 items-center gap-4">
      <Label>{label}</Label>
      <span className="flex items-center gap-2 break-all">{children}</span>
    </div>
  );
}

export default function VectorDBInstanceDetails({ id }: { id: string }) {
  const [instance, setInstance] = useState<VectorDBInstanceSchema | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const { toast } = useToast();

  const fetchInstance = useCallback(
    async (options?: { silent?: boolean }) => {
      try {
        setInstance(await vectorDBService.getVectorDBInstance(id));
      } catch (error) {
        if (!options?.silent) toast(parseApiError(error));
      } finally {
        setLoading(false);
      }
    },
    [id, toast]
  );

  useEffect(() => {
    fetchInstance();
  }, [fetchInstance]);

  const poll = useCallback(() => fetchInstance({ silent: true }), [fetchInstance]);
  usePolling(poll, instance ? isNonTerminal(instance) : false);

  if (loading) return <DetailSkeleton />;
  if (!instance) return <div>Vector database instance not found</div>;

  const apiBase = instance.api_endpoint?.replace(/\/$/, "") ?? "<api endpoint>";
  const configEntries = Object.entries(instance.configParams ?? {});

  return (
    <DisplayCard
      icon={GetVectorDBIcon(instance.vectorDB.chart_name)}
      title={instance.vectorDB.name}
      description={`ID: ${instance.id}`}
      onRefresh={() => fetchInstance()}
      content={
        <div className="grid gap-4">
          <Row label="Chart">{instance.vectorDB.chart_name}</Row>
          <Row label="Status">{instance.ready ? "Ready" : instance.status || "In progress"}</Row>
          <Row label="Endpoint">
            <span className={instance.ready ? "text-green-500" : "text-red-500"}>
              {instance.endpoint || "N/A"}
            </span>
            {instance.endpoint && <CopyButton label="Endpoint" text={instance.endpoint} />}
          </Row>
          <Row label="API endpoint">
            {instance.api_endpoint || "N/A"}
            {instance.api_endpoint && <CopyButton label="API endpoint" text={instance.api_endpoint} />}
          </Row>
          {configEntries.length > 0 && (
            <Row label="Configuration">
              <span className="text-sm text-muted-foreground">
                {configEntries.map(([k, v]) => `${k}=${String(v)}`).join(", ")}
              </span>
            </Row>
          )}
          <div className="grid grid-cols-2 items-start gap-4">
            <Label>Access</Label>
            <div className="space-y-2 text-sm text-muted-foreground">
              <p>
                The API endpoint is protected at the gateway; send the instance API key in the
                header shown by &quot;Show credential&quot;.
              </p>
              <CodeSnippet
                label="curl example"
                code={`curl -H "api-key: <api key>" ${apiBase}/collections`}
              />
            </div>
          </div>
        </div>
      }
      footer={
        <div className="flex flex-wrap gap-2">
          <ShowCredentialButton instance={instance} />
          <DeleteButton
            onDelete={() => vectorDBService.deleteVectorDBInstance(instance.id)}
            onSuccess={() => router.push("/vector-databases/endpoints")}
          />
        </div>
      }
    />
  );
}
