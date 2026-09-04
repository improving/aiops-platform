"use client";

import VectorDBEndpoints from '@/components/vector-databases/VectorDBEndpoints';
import Dashboard from '@/components/Dashboard';

export default function VectorDatabasesEndpoints() {
  return (
    <Dashboard title="Vector Databases Endpoints">
      <VectorDBEndpoints />
    </Dashboard>
  );
}
