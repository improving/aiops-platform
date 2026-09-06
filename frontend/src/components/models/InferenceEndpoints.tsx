"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { RocketIcon, ClipboardCopyIcon } from "@radix-ui/react-icons";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/components/hooks/use-toast";
import { InferenceInstance } from "@/types/models";
import { modelService } from "@/services/modelService";
import { parseApiError } from "@/lib/utils";
import { DisplayCard } from "@/components/ui/DisplayCard";
import { GetModelIcon } from "@/lib/utils";
import { RefreshButton } from "../RefreshButton";
import { isNonTerminal, usePolling } from "@/hooks/usePolling";

export default function InferenceEndpoints() {
  const [endpoints, setEndpoints] = useState<InferenceInstance[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState("");
  const [filterCategory, setFilterCategory] = useState("all");
  const [filterValue, setFilterValue] = useState("");
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
    fetchEndpoints();
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

  if (loading) {
    return <div>Loading...</div>;
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
            </div>
            <RefreshButton onRefresh={fetchEndpoints} />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {filteredEndpoints.map((endpoint) => (
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
                      {endpoint.ready ? (
                        <span className="px-2 py-1 bg-green-100 text-green-800 rounded-full text-sm">
                          Ready
                        </span>
                      ) : (
                        <span className="px-2 py-1 bg-red-100 text-red-800 rounded-full text-sm">
                          {endpoint.status || "In Progress"}
                        </span>
                      )}
                      {endpoint.config.lora_adapters.length > 0 && (
                        <span className="px-2 py-1 bg-purple-100 text-purple-800 rounded-full text-sm">
                          {endpoint.config.lora_adapters.length} Adapters
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-gray-600 mb-2">
                      <strong>Endpoint: </strong>
                      <span
                        className={
                          endpoint.ready ? "text-green-500" : "text-red-500"
                        }
                      >
                        {endpoint.endpoint || "N/A"}
                      </span>
                      <Button
                        variant="outline"
                        onClick={() =>
                          navigator.clipboard.writeText(endpoint.endpoint || "")
                        }
                        className="ml-2"
                        icon={<ClipboardCopyIcon className="w-4 h-4" />}
                      ></Button>
                    </p>
                  </>
                }
              />
            ))}
          </div>
        </>
      )}
    </>
  );
}
