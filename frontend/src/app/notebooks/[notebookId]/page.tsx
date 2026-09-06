"use client";

import { useParams } from "next/navigation";
import NotebookDetails from "@/components/notebooks/NotebookDetails";
import Dashboard from "@/components/Dashboard";

export default function NotebookDetailsPage() {
  const params = useParams();
  const notebookId = params.notebookId as string;

  return (
    <Dashboard
      title="Notebook Details"
      breadcrumbs={[{ label: "Notebooks", href: "/notebooks" }, { label: "Details" }]}
    >
      <NotebookDetails notebookId={notebookId} />
    </Dashboard>
  );
}