interface VectorDBSchema {
  id: string;
  name: string;
  description: string;
}

interface VectorDBInstanceSchema {
  id: string;
  vectorDB: VectorDBSchema;
  configParams: Record<string, any>;
  endpoint: string;
}

export type { VectorDBSchema, VectorDBInstanceSchema };
