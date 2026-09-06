import React, { useState } from "react";
import NotConfigured from "@/components/NotConfigured";

interface GrafanaEmbedProps {
  grafanaEndpoint: string;
  dashboardID: string;
  panelID: string;
  orgID: string;
  queryParams?: {
    [key: string]: string;
  };
  height?: string;
}

/** The d-solo URL of one panel, or null when it cannot be built. */
function panelUrl(
  grafanaEndpoint: string,
  dashboardID: string,
  panelID: string,
  orgID: string,
  queryParams: { [key: string]: string }
): string | null {
  if (!grafanaEndpoint || !dashboardID || !panelID) return null;
  try {
    const url = new URL(`${grafanaEndpoint}/d-solo/${dashboardID}`);
    url.searchParams.append("orgId", orgID);
    url.searchParams.append("panelId", panelID);
    url.searchParams.append("theme", "light");
    Object.entries(queryParams).forEach(([key, value]) => {
      url.searchParams.append(key, value);
    });
    return url.toString();
  } catch {
    return null;
  }
}

const GrafanaEmbed: React.FC<GrafanaEmbedProps> = ({
  grafanaEndpoint,
  dashboardID,
  panelID,
  orgID,
  queryParams = {},
  height = "300px",
}) => {
  const [error, setError] = useState<string | null>(null);
  // Computed synchronously: an iframe must never render with an empty
  // src (the browser would load the page itself into the frame).
  const iframeUrl = panelUrl(
    grafanaEndpoint,
    dashboardID,
    panelID,
    orgID,
    queryParams
  );

  if (!grafanaEndpoint) {
    return <NotConfigured name="Grafana" envVar="NEXT_PUBLIC_GRAFANA_URL" />;
  }

  if (error) {
    return <div className="error">{error}</div>;
  }

  if (!iframeUrl) {
    return (
      <div className="text-sm text-muted-foreground">
        This panel has no dashboard reference.
      </div>
    );
  }

  return (
    <div className="grafana-embed">
      <iframe
        src={iframeUrl}
        width="100%"
        height={height}
        title="Grafana Dashboard"
        onError={() => setError("Failed to load dashboard")}
      />
    </div>
  );
};

export default GrafanaEmbed;
