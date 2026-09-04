"use client";

import { Suspense } from "react";
import { useParams } from "next/navigation";
import InferenceEndpointDetails from "@/components/models/InferenceEndpointDetails";
import Dashboard from "@/components/Dashboard";

export default function InferenceEndpointDetailsPage() {
  const { id } = useParams<{ id: string }>();

  return (
    <Dashboard title="Inference Endpoint Details">
      <Suspense fallback={null}>
        <InferenceEndpointDetails params={{ id }} />
      </Suspense>
    </Dashboard>
  );
}
