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

const GB = 1e9;
const MB = 1e6;

/** "8.0 of 10.0 GB (80 %)", or "3.0 GB" when the total is not known. */
function downloadText(done: number, total?: number | null): string {
  if (!total) return `${(done / GB).toFixed(1)} GB`;
  const percent = Math.min(100, Math.floor((done / total) * 100));
  return `${(done / GB).toFixed(1)} of ${(total / GB).toFixed(1)} GB (${percent} %)`;
}

/** "6.1 MB/s, about 5 min left"; empty until there is a rate to trust. */
function rateText(
  first: { bytes: number; at: number } | null,
  done: number,
  total: number | null | undefined,
  now: number
): string {
  if (!first) return "";
  const seconds = (now - first.at) / 1000;
  const gained = done - first.bytes;
  // Ten seconds and some progress: one poll says nothing about a speed.
  if (seconds < 10 || gained <= 0) return "";
  const rate = gained / seconds;
  const speed = `${(rate / MB).toFixed(1)} MB/s`;
  if (!total || done >= total) return speed;
  const left = (total - done) / rate;
  const about =
    left < 90 ? "about a minute" : `about ${Math.round(left / 60)} min`;
  return `${speed}, ${about} left`;
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
  const watchesDownload =
    active &&
    launch?.downloaded_bytes != null &&
    (!launch.total_bytes || launch.downloaded_bytes < launch.total_bytes);
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(
      () => setNow(Date.now()),
      // A download's speed needs a clock about as fresh as the page's poll.
      countsSeconds ? 1000 : watchesDownload ? 5000 : 15_000
    );
    return () => clearInterval(timer);
  }, [active, countsSeconds, watchesDownload]);

  // The first amount seen and when, to tell a speed from the polls the page
  // makes anyway. Kept in state and adjusted during render, not in an
  // effect (https://react.dev/learn/you-might-not-need-an-effect); a smaller
  // amount than before means the download began again.
  const done = active ? (launch?.downloaded_bytes ?? null) : null;
  const total = launch?.total_bytes;
  const downloading = done !== null && (!total || done < total);
  const [first, setFirst] = useState<{ bytes: number; at: number } | null>(
    null
  );
  if (downloading && (first === null || done < first.bytes)) {
    setFirst({ bytes: done, at: now });
  } else if (!downloading && first !== null) {
    setFirst(null);
  }

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
        {downloading && <span> · {downloadText(done, total)}</span>}
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
      {downloading && (
        <div data-slot="download-progress" className="mt-2 space-y-1">
          {total ? (
            <div
              role="progressbar"
              aria-label="Model download"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.min(100, Math.floor((done / total) * 100))}
              className="h-1.5 w-full overflow-hidden rounded-full bg-blue-200 dark:bg-blue-900"
            >
              <div
                className="h-full bg-blue-600 dark:bg-blue-400"
                style={{ width: `${Math.min(100, (done / total) * 100)}%` }}
              />
            </div>
          ) : null}
          <p className="text-xs">
            {downloadText(done, total)}
            {rateText(first, done, total, now) &&
              ` · ${rateText(first, done, total, now)}`}
          </p>
        </div>
      )}
    </div>
  );
}
