"use client";

import { CopyButton } from "@/components/CopyButton";

/**
 * The persisted failure reason (`last_error`) in a red banner with a copy
 * button. Renders nothing without an error; `compact` keeps it to one
 * line for the cards.
 */
export function ErrorBanner({
  error,
  at,
  compact = false,
}: {
  error?: string | null;
  at?: string | null;
  compact?: boolean;
}) {
  if (!error) return null;
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200"
    >
      <div className="min-w-0 grow">
        <p className="font-medium">
          Failed{at ? ` at ${new Date(at).toLocaleString()}` : ""}
        </p>
        <p className={compact ? "truncate" : "whitespace-pre-wrap break-all"}>
          {error}
        </p>
      </div>
      <CopyButton label="error" text={error} />
    </div>
  );
}
