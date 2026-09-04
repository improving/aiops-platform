import React, { useState, useEffect } from "react";

interface JaegerEmbedProps {
  jaegerEndpoint: string;
  serviceName: string;
  start: number;
  end: number;
  limit: number;
  lookback: string;
  height?: string;
}

const JaegerEmbed: React.FC<JaegerEmbedProps> = ({
  jaegerEndpoint,
  serviceName,
  start,
  end,
  limit,
  lookback,
  height = "600px",
}) => {
  const [iframeUrl, setIframeUrl] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    try {
      const url = new URL(`${jaegerEndpoint}/search`);
      url.searchParams.append("service", serviceName);
      // start timestamp in microseconds
      url.searchParams.append("start", (start * 1000).toString());
      url.searchParams.append("end", (end * 1000).toString());
      url.searchParams.append("limit", limit.toString());
      url.searchParams.append("lookback", lookback);
      url.searchParams.append("uiEmbed", "v0");

      setIframeUrl(url.toString());
    } catch (err) {
      console.error("Error constructing Jaeger URL:", err);
      setError("Failed to construct Jaeger URL");
    }
  }, [jaegerEndpoint, serviceName, start, end, limit, lookback]);

  if (error) {
    return <div className="error">{error}</div>;
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
