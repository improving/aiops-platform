"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useToast } from "@/components/hooks/use-toast";
import { LockClosedIcon } from "@radix-ui/react-icons";
import { vectorDBService } from "@/services/vectorDBService";
import { parseApiError } from "@/lib/utils";
import { CopyButton } from "@/components/CopyButton";
import { MaskedSecret } from "@/components/MaskedSecret";
import {
  VectorDBCredentialSchema,
  VectorDBInstanceSchema,
} from "@/types/vectordb";

interface ShowCredentialButtonProps {
  instance: VectorDBInstanceSchema;
}

/** The SDK URL for a path: api_endpoint ends with "/" when it is set. */
function apiUrl(instance: VectorDBInstanceSchema, path: string) {
  const base = instance.api_endpoint?.replace(/\/$/, "");
  return base ? `${base}/${path}` : `<api endpoint>/${path}`;
}

function Field({
  label,
  value,
  ariaLabel,
  copyLabel,
}: {
  label: string;
  value: string;
  ariaLabel: string;
  copyLabel?: string;
}) {
  return (
    <div>
      <p className="text-sm font-medium mb-1">{label}</p>
      <div className="flex items-center gap-2">
        <code
          aria-label={ariaLabel}
          className="flex-1 rounded bg-muted px-2 py-1 text-sm break-all"
        >
          {value}
        </code>
        <CopyButton label={copyLabel ?? label} text={value} />
      </div>
    </div>
  );
}

/**
 * Reveals the per-instance API key through
 * GET /api/v1alpha1/credentials/vdb/{id}. The backend hands the value out
 * once, so the fetch happens on the click and the dialog says so.
 */
export function ShowCredentialButton({ instance }: ShowCredentialButtonProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [credential, setCredential] = useState<VectorDBCredentialSchema | null>(
    null
  );
  const { toast } = useToast();

  const reveal = async () => {
    setIsLoading(true);
    try {
      setCredential(await vectorDBService.getVectorDBCredential(instance.id));
      setIsOpen(true);
    } catch (error) {
      toast(parseApiError(error));
    } finally {
      setIsLoading(false);
    }
  };

  const usageHint = credential?.value
    ? `curl -H "${credential.key}: <api key>" ${apiUrl(instance, "collections")}`
    : "";

  return (
    <>
      <Button
        variant="outline"
        onClick={reveal}
        loading={isLoading}
        icon={<LockClosedIcon className="w-4 h-4" />}
      >
        Show credential
      </Button>
      <Dialog open={isOpen} onOpenChange={setIsOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>API key for {instance.vectorDB.name}</DialogTitle>
            <DialogDescription>
              {credential?.value
                ? "Masked so it stays out of screen shares; copy or reveal it now. Shown once, and not stored by the UI."
                : "This key was already revealed."}
            </DialogDescription>
          </DialogHeader>
          {credential?.value ? (
            <div className="space-y-4">
              <div>
                <p className="text-sm font-medium mb-1">API key</p>
                <MaskedSecret value={credential.value} label="API key value" />
              </div>
              <Field
                label="API endpoint"
                value={instance.api_endpoint || "N/A"}
                ariaLabel="API endpoint"
              />
              <Field
                label="Usage"
                value={usageHint}
                ariaLabel="Usage hint"
                copyLabel="usage hint"
              />
              <p className="text-sm text-muted-foreground">
                Send the key in the <code>{credential.key}</code> header on the
                API endpoint; requests without it are rejected by the gateway.
              </p>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              The key was revealed
              {credential?.shown_at
                ? ` on ${new Date(credential.shown_at).toLocaleString()}`
                : ""}{" "}
              and cannot be shown here again. An organization admin can fetch it
              once more with{" "}
              <code>
                GET /api/v1alpha1/credentials/vdb/{instance.id}?reveal=true
              </code>
              .
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsOpen(false)}>
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
