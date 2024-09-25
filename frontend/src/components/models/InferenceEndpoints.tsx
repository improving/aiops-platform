"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  EyeOpenIcon,
  RocketIcon,
  ClipboardCopyIcon,
  OpenInNewWindowIcon,
} from "@radix-ui/react-icons";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/components/hooks/use-toast";
import { InferenceInstance } from "@/types/models";

export default function InferenceEndpoints() {
  const [endpoints, setEndpoints] = useState<InferenceInstance[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState("");
  const [filterCategory, setFilterCategory] = useState("all");
  const [filterValue, setFilterValue] = useState("");
  const [error, setError] = useState<string | null>(null); // Add error state
  const { toast } = useToast(); // Initialize toast

  useEffect(() => {
    const fetchEndpoints = async () => {
      try {
        const response = await fetch("/api/v1alpha1/inferenceInstance");
        if (!response.ok) {
          const errorData = await response.json(); // Get error details
          throw new Error(
            `HTTP ${response.status}-${response.statusText}: ${errorData.detail}`
          );
        }
        const data = await response.json();
        setEndpoints(data);
        setLoading(false);
      } catch (error: any) {
        console.error("Error fetching inference instances:", error);
        setError(error.message); // Set error state
        toast({
          title: "Error Fetching Inference Instances",
          description: error.message,
        });
        setLoading(false);
      }
    };
    fetchEndpoints();
  }, [toast]);

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

  if (error) {
    return <div>Error: {error}</div>;
  }

  return (
    <>
      {endpoints.length === 0 ? (
        <div className="text-center">
          <p className="mb-4">No inference endpoints available.</p>
          <Link href="/models/catalog">
            <Button>
              <RocketIcon className="mr-2 h-4 w-4" />
              Launch
            </Button>
          </Link>
        </div>
      ) : (
        <>
          <div className="flex gap-4 mb-6">
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
                  {Array.from(new Set(endpoints.map((e) => e.engine.name))).map(
                    (engine) => (
                      <SelectItem key={engine} value={engine}>
                        {engine}
                      </SelectItem>
                    )
                  )}
                </SelectContent>
              </Select>
            )}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {filteredEndpoints.map((endpoint) => (
              <Card key={endpoint.id}>
                <CardHeader>
                  <CardTitle>{endpoint.model.name}</CardTitle>
                  <CardDescription>ID: {endpoint.id}</CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="flex flex-wrap gap-2 mb-3">
                    <span className="px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-sm">
                      {endpoint.engine.name}
                    </span>
                    <span className="px-2 py-1 bg-green-100 text-green-800 rounded-full text-sm">
                      {endpoint.host}
                    </span>
                    {endpoint.ready ? (
                      <span className="px-2 py-1 bg-green-100 text-green-800 rounded-full text-sm">
                        Ready
                      </span>
                    ) : (
                      <span className="px-2 py-1 bg-red-100 text-red-800 rounded-full text-sm">
                        {endpoint.status || "In Progress"}
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
                      <OpenInNewWindowIcon className="w-4 h-4 inline-block" />
                      <a href={`${endpoint.endpoint}/docs`} target="_blank">
                        {endpoint.endpoint || "N/A"}
                      </a>
                    </span>
                    <Button
                      variant="outline"
                      onClick={() =>
                        navigator.clipboard.writeText(endpoint.endpoint || "")
                      }
                      className="ml-2"
                    >
                      <ClipboardCopyIcon />
                    </Button>
                  </p>
                </CardContent>
                <CardFooter>
                  <Link href={`/models/endpoints/${endpoint.id}`} passHref>
                    <Button>
                      <EyeOpenIcon className="mr-2 w-4 h-4" />
                      View Details
                    </Button>
                  </Link>
                </CardFooter>
              </Card>
            ))}
          </div>
        </>
      )}
    </>
  );
}
