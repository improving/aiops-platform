"use client";

import NotebookList from "@/components/notebooks/NotebookList";
import Dashboard from "@/components/Dashboard";

export default function NotebookListPage() {
  return (
    <Dashboard title="Notebooks">
      <NotebookList />
    </Dashboard>
  );
}