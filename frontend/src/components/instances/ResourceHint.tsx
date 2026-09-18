import type { FreeResource } from "@/lib/launchHints";
import { oneDecimal } from "@/lib/launchHints";

/**
 * One line under a resource input: what is free on the selected host, a
 * bar of what is taken, and a warning when the form asks for more than is
 * free. A hint, never a gate: Kubernetes decides, and an instance that
 * does not fit waits as Pending with the scheduler's reason. Renders
 * nothing without numbers (no host picked, or a host that reports none).
 */
export function ResourceHint({
  id,
  resource,
  unit,
  hostname,
  overMessage,
}: {
  id: string;
  resource: FreeResource | null;
  unit: string;
  hostname: string;
  overMessage: string;
}) {
  if (!resource) return null;
  const { free, total, wanted, over } = resource;
  const taken = total > 0 ? Math.min(100, ((total - free) / total) * 100) : 0;
  const asked =
    wanted !== null && total > 0
      ? Math.min(100 - taken, (wanted / total) * 100)
      : 0;
  return (
    <div id={id} data-slot="resource-hint" className="space-y-1 text-xs">
      <div
        aria-hidden
        className="flex h-1.5 w-full overflow-hidden rounded-full bg-muted"
      >
        <div className="bg-foreground/40" style={{ width: `${taken}%` }} />
        <div
          className={over ? "bg-destructive" : "bg-primary"}
          style={{ width: `${asked}%` }}
        />
      </div>
      <p
        role={over ? "alert" : "status"}
        className={over ? "text-destructive" : "text-muted-foreground"}
      >
        {oneDecimal(free)} of {oneDecimal(total)} {unit} free on {hostname}
        {over && `. ${overMessage}`}
      </p>
    </div>
  );
}
