"use client";

import { Suspense } from "react";
import { useParams } from "next/navigation";
import ModelDetails from "@/components/models/ModelDetails";
import Dashboard from "@/components/Dashboard";

export default function ModelDetailsPage() {
  const { id } = useParams<{ id: string }>();

  return (
    <Dashboard title="Model Details">
      <Suspense fallback={null}>
        <ModelDetails params={{ id }} />
      </Suspense>
    </Dashboard>
  );
}
