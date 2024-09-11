import React, { useState, useEffect } from 'react';

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

const GrafanaEmbed: React.FC<GrafanaEmbedProps> = ({
  grafanaEndpoint,
  dashboardID,
  panelID,
  orgID,
  queryParams = {},
  height = '300px'
}) => {
  const [iframeUrl, setIframeUrl] = useState<string>('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    try {
      const url = new URL(`${grafanaEndpoint}/d-solo/${dashboardID}`);
      url.searchParams.append('orgId', orgID);
      url.searchParams.append('panelId', panelID);
      url.searchParams.append('theme', 'light');
      
      Object.entries(queryParams).forEach(([key, value]) => {
        url.searchParams.append(key, value);
      });

      setIframeUrl(url.toString());
    } catch (err) {
      setError('Failed to construct dashboard URL');
    }
  }, [grafanaEndpoint, dashboardID, panelID, orgID, queryParams]);

  if (error) {
    return <div className="error">{error}</div>;
  }

  return (
    <div className="grafana-embed">
      <iframe
        src={iframeUrl}
        width="100%"
        height={height}
        title="Grafana Dashboard"
        onError={() => setError('Failed to load dashboard')}
      />
    </div>
  );
};

export default GrafanaEmbed;