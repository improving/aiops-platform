"use client";

import { useParams } from "next/navigation";
import Dashboard from "@/components/Dashboard";
import VectorDBInstanceDetails from "@/components/vector-databases/VectorDBInstanceDetails";

export default function VectorDBInstanceDetailsPage() {
  const { id } = useParams<{ id: string }>();
  return (
    <Dashboard
      title="Vector Database Instance Details"
      breadcrumbs={[
        { label: "Vector Databases" },
        { label: "Instances", href: "/vector-databases/endpoints" },
        { label: "Details" },
      ]}
    >
      <VectorDBInstanceDetails id={id} />
    </Dashboard>
  );
}
