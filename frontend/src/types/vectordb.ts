interface VectorDBSchema {
  id: string;
  name: string;
  description: string;
  chart_name: string;
  chart_description: string;
}

interface VectorDBInstanceSchema {
  id: string;
  vectorDB: VectorDBSchema;
  configParams: Record<string, unknown>;
  endpoint: string;
  // The SDK endpoint behind the gateway, protected by the instance API key;
  // null when no gateway is configured.
  api_endpoint?: string | null;
  ready: boolean;
  status: string;
}

// GET /api/v1alpha1/credentials/vdb/{id}: the value is returned once,
// afterwards it is null and shown_at says when it was revealed.
interface VectorDBCredentialSchema {
  key: string;
  value: string | null;
  shown_at: string | null;
}

export type {
  VectorDBSchema,
  VectorDBInstanceSchema,
  VectorDBCredentialSchema,
};
