"use client";

import { Suspense, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import ModelDetails from "@/components/models/ModelDetails";
import Dashboard from "@/components/Dashboard";
import { modelService } from "@/services/modelService";

export default function ModelDetailsPage() {
  const { id } = useParams<{ id: string }>();
  const [name, setName] = useState<string | null>(null);

  useEffect(() => {
    // The crumb only; ModelDetails fetches and reports errors itself.
    modelService
      .getModelById(id)
      .then((model) => setName(model.name))
      .catch(() => setName(null));
  }, [id]);

  return (
    <Dashboard
      title="Model Details"
      breadcrumbs={[
        { label: "Models" },
        { label: "Catalog", href: "/models/catalog" },
        { label: name ?? "Details" },
      ]}
    >
      <Suspense fallback={null}>
        <ModelDetails params={{ id }} />
      </Suspense>
    </Dashboard>
  );
}
