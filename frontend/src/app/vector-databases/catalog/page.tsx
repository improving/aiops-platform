"use client";

import VectorDBCatalog from '@/components/vector-databases/VectorDBCatalog';
import Dashboard from '@/components/Dashboard';

export default function VectorDBCatalogPage() {
  return (
    <Dashboard title="Vector Database Catalog">
      <VectorDBCatalog />
    </Dashboard>
  );
}