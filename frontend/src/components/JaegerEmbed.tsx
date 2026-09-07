"use client";

import React, { useState } from "react";
import NotConfigured from "@/components/NotConfigured";
import { useRuntimeConfig } from "@/lib/runtimeConfig";

interface JaegerEmbedProps {
  serviceName: string;
  start: number;
  end: number;
  limit: number;
  lookback: string;
  height?: string;
}

const JaegerEmbed: React.FC<JaegerEmbedProps> = ({
  serviceName,
  start,
  end,
  limit,
  lookback,
  height = "600px",
}) => {
  const runtime = useRuntimeConfig();
  const endpoint = runtime.jaegerUrl;
  const [error, setError] = useState<string | null>(null);
  // Computed synchronously: an iframe must never render with an empty
  // src (the browser would load the page itself into the frame).
  let iframeUrl: string | null = null;
  try {
    const url = new URL(`${endpoint}/search`);
    url.searchParams.append("service", serviceName);
    // start timestamp in microseconds
    url.searchParams.append("start", (start * 1000).toString());
    url.searchParams.append("end", (end * 1000).toString());
    url.searchParams.append("limit", limit.toString());
    url.searchParams.append("lookback", lookback);
    url.searchParams.append("uiEmbed", "v0");
    iframeUrl = url.toString();
  } catch {
    iframeUrl = null;
  }

  if (!runtime.loaded) return null;
  if (!endpoint) {
    return (
      <NotConfigured
        name="Jaeger"
        envVar="NEXT_PUBLIC_JAEGER_URL"
        backendVar="JAEGER_URL"
      />
    );
  }

  if (error) {
    return <div className="error">{error}</div>;
  }

  if (!iframeUrl) {
    return <div className="error">Failed to construct Jaeger URL</div>;
  }

  return (
    <div className="jaeger-embed">
      <iframe
        src={iframeUrl}
        width="100%"
        height={height}
        title="Jaeger Dashboard"
        onError={() => setError("Failed to load Jaeger dashboard")}
      />
    </div>
  );
};

export default JaegerEmbed;
