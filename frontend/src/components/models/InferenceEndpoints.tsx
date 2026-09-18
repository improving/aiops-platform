"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { RocketIcon } from "@radix-ui/react-icons";
import { CopyButton } from "@/components/CopyButton";
import { StatusBadge } from "@/components/instances/StatusBadge";
import { ErrorBanner } from "@/components/instances/ErrorBanner";
import { LaunchProgress } from "@/components/instances/LaunchProgress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/components/hooks/use-toast";
import { InferenceInstance } from "@/types/models";
import {
  formatParameterCount,
  formatWeights,
  instanceTargetName,
} from "@/lib/format";
import { modelService } from "@/services/modelService";
import { parseApiError } from "@/lib/utils";
import { DisplayCard } from "@/components/ui/DisplayCard";
import { GetModelIcon } from "@/lib/utils";
import { CardGridSkeleton } from "@/components/LoadingState";
import { RefreshButton } from "../RefreshButton";
import { isNonTerminal, usePolling } from "@/hooks/usePolling";
import {
  ListControls,
  ShowMore,
  applyListControls,
  useListState,
} from "@/components/ListControls";

/** "7.6B parameters", "5.2 GB weights": what the registry knows, else nothing. */
function instanceFacts(endpoint: InferenceInstance): string[] {
  const parameters = formatParameterCount(endpoint.model.parameters);
  const weights = formatWeights(endpoint.model.size);
  return [
    parameters && `${parameters} parameters`,
    weights && `${weights} weights`,
  ].filter((fact): fact is string => Boolean(fact));
}

export default function InferenceEndpoints() {
  const [endpoints, setEndpoints] = useState<InferenceInstance[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState("");
  const [filterCategory, setFilterCategory] = useState("all");
  const [filterValue, setFilterValue] = useState("");
  const [listState, updateList, nextPage] = useListState();
  const { toast } = useToast();

  const fetchEndpoints = useCallback(
    async (options?: { silent?: boolean }) => {
      try {
        const data = await modelService.getInferenceInstances();
        setEndpoints(data);
      } catch (error) {
        if (!options?.silent) toast(parseApiError(error));
      } finally {
        setLoading(false);
      }
    },
    [toast]
  );

  useEffect(() => {
    (async () => {
      await fetchEndpoints();
    })();
  }, [fetchEndpoints]);

  const pollEndpoints = useCallback(
    () => fetchEndpoints({ silent: true }),
    [fetchEndpoints]
  );
  usePolling(pollEndpoints, endpoints.some(isNonTerminal));

  const filteredEndpoints = endpoints.filter((endpoint) => {
    const searchLower = searchTerm.toLowerCase();
    const matchesSearch =
      endpoint.id.toLowerCase().includes(searchLower) ||
      endpoint.model.name.toLowerCase().includes(searchLower);

    if (filterCategory === "hostname") {
      return (
        matchesSearch &&
        endpoint.host.toLowerCase() === filterValue.toLowerCase()
      );
    } else if (filterCategory === "engineName") {
      return (
        matchesSearch &&
        endpoint.engine.name.toLowerCase() === filterValue.toLowerCase()
      );
    }
    return matchesSearch; // For "all"
  });

  const { visible, total, hasMore } = applyListControls(
    filteredEndpoints,
    listState,
    { name: (e) => e.model.name, ready: (e) => e.ready }
  );

  if (loading) {
    return <CardGridSkeleton />;
  }

  return (
    <>
      {endpoints.length === 0 ? (
        <div className="text-center">
          <p className="mb-4">No model instances yet.</p>
          <Link href="/models/catalog">
            <Button icon={<RocketIcon className="mr-2 h-4 w-4" />}>
              Launch
            </Button>
          </Link>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-4 mb-6">
            <div className="flex flex-wrap gap-4 grow">
              <Input
                placeholder="Search by ID or model name"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="max-w-sm"
              />
              <Select onValueChange={(value) => setFilterCategory(value)}>
                <SelectTrigger className="w-[180px]">
                  <SelectValue placeholder="Filter by" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All</SelectItem>
                  <SelectItem value="hostname">Hostname</SelectItem>
                  <SelectItem value="engineName">Engine Name</SelectItem>
                </SelectContent>
              </Select>
              {filterCategory === "hostname" && (
                <Select onValueChange={(value) => setFilterValue(value)}>
                  <SelectTrigger className="w-[180px]">
                    <SelectValue placeholder="Select Hostname" />
                  </SelectTrigger>
                  <SelectContent>
                    {Array.from(new Set(endpoints.map((e) => e.host))).map(
                      (host) => (
                        <SelectItem key={host} value={host}>
                          {host}
                        </SelectItem>
                      )
                    )}
                  </SelectContent>
                </Select>
              )}
              {filterCategory === "engineName" && (
                <Select onValueChange={(value) => setFilterValue(value)}>
                  <SelectTrigger className="w-[180px]">
                    <SelectValue placeholder="Select Engine" />
                  </SelectTrigger>
                  <SelectContent>
                    {Array.from(
                      new Set(endpoints.map((e) => e.engine.name))
                    ).map((engine) => (
                      <SelectItem key={engine} value={engine}>
                        {engine}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
              <ListControls state={listState} onChange={updateList} />
            </div>
            <RefreshButton onRefresh={fetchEndpoints} />
          </div>
          {total === 0 ? (
            <p className="text-muted-foreground">No instances match.</p>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {visible.map((endpoint) => (
                <DisplayCard
                  key={endpoint.id}
                  icon={GetModelIcon(endpoint.model.modelId)}
                  title={
                    <Link
                      href={`/models/endpoints/${endpoint.id}`}
                      className="hover:text-blue-500 underline"
                    >
                      {endpoint.model.name}
                    </Link>
                  }
                  description={`ID: ${endpoint.id}`}
                  content={
                    <>
                      <div className="flex flex-wrap gap-2 mb-3">
                        <span className="px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-sm">
                          {endpoint.engine.name}
                        </span>
                        {endpoint.host && (
                          <span className="px-2 py-1 bg-green-100 text-green-800 rounded-full text-sm">
                            {endpoint.host}
                          </span>
                        )}
                        <StatusBadge
                          ready={endpoint.ready}
                          status={endpoint.status}
                        />
                        <span
                          data-slot="accelerator"
                          className="px-2 py-1 bg-gray-100 text-gray-800 rounded-full text-sm"
                        >
                          {endpoint.engine.cpu
                            ? "CPU"
                            : `${endpoint.gpu_count ?? 1} GPU`}
                        </span>
                        <span className="px-2 py-1 bg-gray-100 text-gray-800 rounded-full text-sm">
                          {endpoint.replicas ?? 1}{" "}
                          {(endpoint.replicas ?? 1) === 1
                            ? "replica"
                            : "replicas"}
                        </span>
                        {endpoint.config.lora_adapters.length > 0 && (
                          <span className="px-2 py-1 bg-purple-100 text-purple-800 rounded-full text-sm">
                            {endpoint.config.lora_adapters.length} Adapters
                          </span>
                        )}
                      </div>
                      <div className="mb-3 space-y-2">
                        <LaunchProgress
                          compact
                          launch={endpoint.launch}
                          ready={endpoint.ready}
                        />
                        <ErrorBanner
                          compact
                          error={endpoint.last_error}
                          at={endpoint.last_error_at}
                        />
                      </div>
                      {/* One quiet line of facts: what runs, how big, and the
                          name Chat, Langflow and the API know it by. */}
                      <p
                        data-slot="instance-facts"
                        className="mb-2 flex flex-wrap items-center gap-x-2 text-sm text-muted-foreground"
                      >
                        {instanceFacts(endpoint).map((fact) => (
                          <span key={fact}>{fact} ·</span>
                        ))}
                        <span className="font-mono text-xs">
                          {instanceTargetName(endpoint)}
                        </span>
                        <CopyButton
                          label={`${endpoint.model.name} model name`}
                          text={instanceTargetName(endpoint)}
                        />
                      </p>
                      <p className="flex items-center text-sm text-gray-600 mb-2">
                        <strong className="mr-1 shrink-0">Endpoint: </strong>
                        <span
                          title={endpoint.endpoint || undefined}
                          className={`truncate ${
                            endpoint.ready ? "text-green-500" : "text-red-500"
                          }`}
                        >
                          {endpoint.endpoint || "N/A"}
                        </span>
                        {endpoint.endpoint && (
                          <span className="ml-2">
                            <CopyButton
                              label={`${endpoint.model.name} endpoint`}
                              text={endpoint.endpoint}
                            />
                          </span>
                        )}
                      </p>
                    </>
                  }
                  footer={
                    // One action, the one the state calls for: talk to a
                    // model that serves, read the log of one that does not.
                    // Chat only lists models one can chat with.
                    endpoint.ready && endpoint.model.category === "llm" ? (
                      <Button asChild variant="outline" size="sm">
                        <Link
                          href={`/chat?target=${instanceTargetName(endpoint)}`}
                        >
                          Chat
                        </Link>
                      </Button>
                    ) : endpoint.status === "Stopped" ? undefined : (
                      <Button asChild variant="outline" size="sm">
                        <Link
                          href={`/models/endpoints/${endpoint.id}?tab=logs`}
                        >
                          Logs
                        </Link>
                      </Button>
                    )
                  }
                />
              ))}
            </div>
          )}
          <ShowMore
            hasMore={hasMore}
            onClick={nextPage}
            shown={visible.length}
            total={total}
          />
        </>
      )}
    </>
  );
}
