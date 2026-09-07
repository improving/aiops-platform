const STYLES: Record<string, string> = {
  Ready: "bg-green-100 text-green-800",
  Running: "bg-green-100 text-green-800",
  Pending: "bg-yellow-100 text-yellow-800",
  Stopped: "bg-gray-100 text-gray-800",
  Failed: "bg-red-100 text-red-800",
};

/**
 * What the badge says: "Ready" when the pods are ready (the existing specs
 * assert that word), else the persisted status, else "Pending" for a row
 * the platform has not looked at yet.
 */
export function instanceStatusLabel({
  ready,
  status,
}: {
  ready?: boolean;
  status?: string | null;
}): string {
  if (ready) return "Ready";
  return status || "Pending";
}

/**
 * One status badge for inference instances, vector databases and
 * notebooks. `label` overrides the word: the notebook pages show the raw
 * persisted status, because `e2e/cluster/notebook-lifecycle.spec.ts`
 * asserts the Status field reads "Running" (not "Ready") once the
 * notebook is up.
 */
export function StatusBadge({
  ready,
  status,
  label,
}: {
  ready?: boolean;
  status?: string | null;
  label?: string;
}) {
  const text = label ?? instanceStatusLabel({ ready, status });
  const style = STYLES[text] ?? "bg-red-100 text-red-800";
  return (
    <span
      data-slot="status-badge"
      className={`px-2 py-1 rounded-full text-sm ${style}`}
    >
      {text}
    </span>
  );
}
