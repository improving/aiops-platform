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
  configParams: Record<string, any>;
  endpoint: string;
}

export type { VectorDBSchema, VectorDBInstanceSchema };
