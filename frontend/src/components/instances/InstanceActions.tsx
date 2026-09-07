"use client";

import { useRef, useState } from "react";
import { ChevronDownIcon } from "@radix-ui/react-icons";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useToast } from "@/components/hooks/use-toast";
import { parseApiError } from "@/lib/utils";

type Action = "restart" | "stop" | "resume" | "scale";

const COPY: Record<
  Action,
  { title: string; description: string; confirm: string; done: string }
> = {
  restart: {
    title: "Restart instance?",
    description:
      "The pods are replaced; requests fail until the new pods are ready.",
    confirm: "Restart",
    done: "Restart requested",
  },
  stop: {
    title: "Stop instance?",
    description:
      "The pods are removed and the endpoint stops answering. The instance keeps its configuration and can be resumed.",
    confirm: "Stop",
    done: "Instance stopped",
  },
  resume: {
    title: "Resume instance?",
    description: "The pods are created again with the stored replica count.",
    confirm: "Resume",
    done: "Instance resumed",
  },
  scale: {
    title: "Scale instance",
    description: "Set the number of replicas (0 to 16). 0 stops the instance.",
    confirm: "Scale",
    done: "Replica count updated",
  },
};

/**
 * The "Actions" menu of a detail page (spec 6.3). Every item opens a
 * confirmation dialog; a kind passes only the callbacks it supports
 * (vector databases: `onRestart` only). `onDone` refetches the instance.
 */
export function InstanceActions({
  status,
  replicas = 1,
  onRestart,
  onStop,
  onResume,
  onScale,
  onDone,
}: {
  status?: string | null;
  replicas?: number;
  onRestart: () => Promise<unknown>;
  onStop?: () => Promise<unknown>;
  onResume?: () => Promise<unknown>;
  onScale?: (replicas: number) => Promise<unknown>;
  onDone: () => Promise<void> | void;
}) {
  const [pending, setPending] = useState<Action | null>(null);
  const [busy, setBusy] = useState(false);
  const [replicaInput, setReplicaInput] = useState(String(replicas));
  const { toast } = useToast();
  const stopped = status === "Stopped";
  // Synchronous re-entrancy guard: `busy` (state) is not committed until
  // after a re-render, so a rapid double click before that commit would
  // otherwise fire the same action twice.
  const runningRef = useRef(false);

  const openDialog = (action: Action) => {
    setReplicaInput(String(replicas));
    setPending(action);
  };

  const run = async () => {
    if (!pending || busy || runningRef.current) return;
    runningRef.current = true;
    try {
      let count = 0;
      if (pending === "scale") {
        count = Number(replicaInput);
        if (
          replicaInput.trim() === "" ||
          !Number.isInteger(count) ||
          count < 0 ||
          count > 16
        ) {
          toast({
            title: "Replicas must be a whole number from 0 to 16",
            variant: "destructive",
          });
          return;
        }
      }
      setBusy(true);
      try {
        if (pending === "restart") await onRestart();
        else if (pending === "stop") await onStop?.();
        else if (pending === "resume") await onResume?.();
        else await onScale?.(count);
        toast({ title: COPY[pending].done, variant: "success" });
        setPending(null);
        await onDone();
      } catch (error) {
        toast(parseApiError(error));
      } finally {
        setBusy(false);
      }
    } finally {
      runningRef.current = false;
    }
  };

  return (
    <>
      {/* Non-modal: a modal menu leaves `pointer-events: none` on the body
          while it closes, and the dialog opened from onSelect would swallow
          the first click on its confirm button. */}
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <Button
            variant="outline"
            icon={<ChevronDownIcon className="w-4 h-4" />}
          >
            Actions
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start">
          <DropdownMenuItem
            onSelect={() => openDialog("restart")}
            disabled={stopped}
          >
            Restart
          </DropdownMenuItem>
          {onStop && !stopped && (
            <DropdownMenuItem onSelect={() => openDialog("stop")}>
              Stop
            </DropdownMenuItem>
          )}
          {onResume && stopped && (
            <DropdownMenuItem onSelect={() => openDialog("resume")}>
              Resume
            </DropdownMenuItem>
          )}
          {onScale && (
            <DropdownMenuItem onSelect={() => openDialog("scale")}>
              Scale…
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      <Dialog
        open={pending !== null}
        onOpenChange={(open) => {
          if (!open && !busy) setPending(null);
        }}
      >
        <DialogContent>
          {pending && (
            <>
              <DialogHeader>
                <DialogTitle>{COPY[pending].title}</DialogTitle>
                <DialogDescription>
                  {COPY[pending].description}
                </DialogDescription>
              </DialogHeader>
              {pending === "scale" && (
                <div className="grid gap-2">
                  <Label htmlFor="scale-replicas">Replicas</Label>
                  <Input
                    id="scale-replicas"
                    type="text"
                    inputMode="numeric"
                    value={replicaInput}
                    onChange={(e) => setReplicaInput(e.target.value)}
                  />
                </div>
              )}
              <DialogFooter>
                <Button
                  variant="outline"
                  onClick={() => setPending(null)}
                  disabled={busy}
                >
                  Cancel
                </Button>
                <Button onClick={run} loading={busy}>
                  {COPY[pending].confirm}
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
