"use client";

import NewNotebookForm from "@/components/notebooks/NewNotebookForm";
import Dashboard from "@/components/Dashboard";

export default function NewNotebookPage() {
  return (
    <Dashboard title="Create New Notebook">
      <NewNotebookForm />
    </Dashboard>
  );
}