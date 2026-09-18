"use client";

import { useEffect, useState } from "react";

import type { LaunchProgress as LaunchProgressData } from "@/types/models";

/** "45 s", "4 min", "1 h 12 min" since `since`; empty without it. */
function elapsed(since: string | null | undefined, now: number): string {
  if (!since) return "";
  const started = new Date(since).getTime();
  if (Number.isNaN(started)) return "";
  const seconds = Math.max(0, Math.floor((now - started) / 1000));
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

/**
 * What an instance that is not ready yet is waiting for: the backend's
 * `launch` (derived from the pods on every read, `null` once the instance
 * is ready, stopped or failed), with the time since the step began.
 * `needs_attention` is the backend's call: amber when only a person can
 * move the launch on, blue when it only needs time.
 * Renders nothing without it. The status badge stays one of its four
 * words on purpose; this line is where the detail goes. `compact` is the
 * one-line form for the cards.
 */
export function LaunchProgress({
  launch,
  ready,
  compact = false,
}: {
  launch?: LaunchProgressData | null;
  ready?: boolean;
  compact?: boolean;
}) {
  const [now, setNow] = useState(() => Date.now());
  const active = Boolean(launch) && !ready;
  // The text counts seconds in the first minute and minutes after it, so
  // the clock ticks each second only while that shows; the page's own poll
  // re-renders the rest.
  const countsSeconds =
    active &&
    Boolean(launch?.since) &&
    now - new Date(launch?.since ?? 0).getTime() < 60_000;
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(
      () => setNow(Date.now()),
      countsSeconds ? 1000 : 15_000
    );
    return () => clearInterval(timer);
  }, [active, countsSeconds]);

  if (!launch || ready) return null;
  const time = elapsed(launch.since, now);
  const attention = launch.needs_attention;
  const tone = attention
    ? "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200"
    : "border-blue-200 bg-blue-50 text-blue-900 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-200";

  if (compact) {
    return (
      <p
        data-slot="launch-progress"
        role="status"
        className={`truncate rounded-md border px-2 py-1 text-sm ${tone}`}
        title={launch.message}
      >
        <span className="font-medium">{launch.phase}</span>
        {time && <span> · {time}</span>}
        {attention && <span> · {launch.message}</span>}
      </p>
    );
  }
  return (
    <div
      data-slot="launch-progress"
      role="status"
      className={`rounded-md border p-3 text-sm ${tone}`}
    >
      <p className="font-medium">
        {launch.phase}
        {time && <span className="font-normal"> for {time}</span>}
        {launch.replicas_total > 1 && (
          <span className="font-normal">
            {" "}
            · {launch.replicas_total} replicas, none ready yet
          </span>
        )}
      </p>
      <p className="whitespace-pre-wrap break-words">{launch.message}</p>
    </div>
  );
}
