"use client";

import { useParams } from "next/navigation";
import ModelFineTune from "@/components/models/ModelFineTune";
import Dashboard from "@/components/Dashboard";

export default function ModelFineTunePage() {
  const { id } = useParams<{ id: string }>();

  return (
    <Dashboard
      title="Fine-tune Model"
      breadcrumbs={[
        { label: "Models" },
        { label: "Catalog", href: "/models/catalog" },
        { label: "Fine-tune" },
      ]}
    >
      <ModelFineTune params={{ id }} />
    </Dashboard>
  );
}
