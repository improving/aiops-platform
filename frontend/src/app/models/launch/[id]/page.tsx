"use client";

import { useParams } from "next/navigation";
import LaunchModel from "@/components/models/LaunchModel";
import Dashboard from "@/components/Dashboard";

export default function LaunchModelPage() {
  const { id } = useParams<{ id: string }>();

  return (
    <Dashboard
      title="Launch Model"
      breadcrumbs={[
        { label: "Models" },
        { label: "Catalog", href: "/models/catalog" },
        { label: "Launch" },
      ]}
    >
      <LaunchModel params={{ id }} />
    </Dashboard>
  );
}
