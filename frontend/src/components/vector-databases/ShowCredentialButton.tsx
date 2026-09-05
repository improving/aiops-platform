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
import { ClipboardCopyIcon, LockClosedIcon } from "@radix-ui/react-icons";
import { vectorDBService } from "@/services/vectorDBService";
import { parseApiError } from "@/lib/utils";
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

function CopyButton({ label, text }: { label: string; text: string }) {
  const { toast } = useToast();
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      toast({ title: "Copied", description: `${label} copied to clipboard` });
    } catch {
      toast({
        title: "Copy failed",
        description: "Select the text and copy it manually",
        variant: "destructive",
      });
    }
  };
  return (
    <Button
      variant="outline"
      size="sm"
      aria-label={`Copy ${label.toLowerCase()}`}
      onClick={copy}
      icon={<ClipboardCopyIcon className="w-4 h-4" />}
    />
  );
}

function Field({
  label,
  value,
  ariaLabel,
}: {
  label: string;
  value: string;
  ariaLabel: string;
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
        <CopyButton label={label} text={value} />
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
    ? `curl -H "${credential.key}: ${credential.value}" ${apiUrl(instance, "collections")}`
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
                ? "This key is shown once. Copy it now; it is not stored by the UI."
                : "This key was already revealed."}
            </DialogDescription>
          </DialogHeader>
          {credential?.value ? (
            <div className="space-y-4">
              <Field
                label="API key"
                value={credential.value}
                ariaLabel="API key value"
              />
              <Field
                label="API endpoint"
                value={instance.api_endpoint || "N/A"}
                ariaLabel="API endpoint"
              />
              <Field label="Usage" value={usageHint} ariaLabel="Usage hint" />
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
