"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { OpenInNewWindowIcon, RocketIcon } from "@radix-ui/react-icons";
import { Notebook } from "@/types/notebook";
import { notebookService } from "@/services/notebookService";
import { useToast } from "@/components/hooks/use-toast";
import { parseApiError } from "@/lib/utils";
import { DisplayCard } from "@/components/ui/DisplayCard";
import { RefreshButton } from "../RefreshButton";
import { isNonTerminal, usePolling } from "@/hooks/usePolling";
import { CardGridSkeleton } from "@/components/LoadingState";
import { CopyButton } from "@/components/CopyButton";
import {
  ListControls,
  ShowMore,
  applyListControls,
  useListState,
} from "@/components/ListControls";

export default function NotebookList() {
  const [notebooks, setNotebooks] = useState<Notebook[]>([]);
  const [searchTerm, setSearchTerm] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [listState, updateList] = useListState();
  const { toast } = useToast();

  const fetchNotebooks = useCallback(
    async (options?: { silent?: boolean }) => {
      try {
        const data = await notebookService.getNotebooks();
        setNotebooks(data);
      } catch (error) {
        if (!options?.silent) toast(parseApiError(error));
      } finally {
        setIsLoading(false);
      }
    },
    [toast]
  );

  useEffect(() => {
    fetchNotebooks();
  }, [fetchNotebooks]);

  const pollNotebooks = useCallback(
    () => fetchNotebooks({ silent: true }),
    [fetchNotebooks]
  );
  usePolling(pollNotebooks, notebooks.some(isNonTerminal));

  const filteredNotebooks = notebooks.filter((notebook) =>
    notebook.name.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const { visible, total, hasMore } = applyListControls(
    filteredNotebooks,
    listState,
    { name: (n) => n.name, ready: (n) => n.ready }
  );

  if (isLoading) {
    return <CardGridSkeleton />;
  }

  return (
    <>
      {notebooks.length === 0 ? (
        <div className="text-center">
          <p className="mb-4">No notebooks yet.</p>
          <Link href="/notebooks/new">
            <Button icon={<RocketIcon className="mr-2 w-4 h-4" />}>
              New Notebook
            </Button>
          </Link>
        </div>
      ) : (
        <>
          <div className="mb-4 flex flex-wrap justify-between items-center gap-2">
            <div className="flex flex-wrap gap-2">
              <Input
                type="text"
                placeholder="Search notebooks"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="max-w-sm"
              />
              <ListControls state={listState} onChange={updateList} />
            </div>
            <div className="flex flex-wrap gap-2">
              <Link href="/notebooks/new" passHref>
                <Button icon={<RocketIcon className="mr-2 w-4 h-4" />}>
                  New Notebook
                </Button>
              </Link>
              <RefreshButton onRefresh={fetchNotebooks} />
            </div>
          </div>
          {total === 0 ? (
            <p className="text-muted-foreground">No notebooks match.</p>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {visible.map((notebook) => (
                <DisplayCard
                  key={notebook.id}
                  icon={`/notebooks/${notebook.type}.png`}
                  title={
                    <Link
                      href={`/notebooks/${notebook.id}`}
                      className="hover:text-blue-500 underline"
                    >
                      {notebook.name}
                    </Link>
                  }
                  description={`ID: ${notebook.id}`}
                  content={
                    <div className="flex flex-wrap gap-2 mb-3">
                      <span className="px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-sm">
                        {notebook.type}
                      </span>
                      {notebook.type == "jupyter" && (
                        <span className="px-2 py-1 bg-purple-100 text-purple-800 rounded-full text-sm">
                          {notebook.framework || "N/A"}
                        </span>
                      )}
                      {notebook.nvidia_gpu && (
                        <span className="px-2 py-1 bg-green-100 text-green-800 rounded-full text-sm">
                          GPUs: {notebook.resources_gpu}
                        </span>
                      )}
                      {notebook.resources_cpu && (
                        <span className="px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-sm">
                          CPU: {notebook.resources_cpu}
                        </span>
                      )}
                      {notebook.resources_memory && (
                        <span className="px-2 py-1 bg-green-100 text-green-800 rounded-full text-sm">
                          Mem: {notebook.resources_memory}
                        </span>
                      )}
                    </div>
                  }
                  footer={
                    <div className="flex items-center gap-2">
                      <Button
                        disabled={!notebook.ready}
                        onClick={() => window.open(notebook.endpoint, "_blank")}
                        icon={<OpenInNewWindowIcon className="mr-2 w-4 h-4" />}
                      >
                        Connect
                      </Button>
                      {notebook.endpoint && (
                        <CopyButton
                          label="notebook URL"
                          text={notebook.endpoint}
                        />
                      )}
                    </div>
                  }
                />
              ))}
            </div>
          )}
          <ShowMore
            hasMore={hasMore}
            onClick={() => updateList({ page: listState.page + 1 })}
            shown={visible.length}
            total={total}
          />
        </>
      )}
    </>
  );
}
