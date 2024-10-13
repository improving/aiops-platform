"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { Input } from "@/components/ui/input";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { OpenInNewWindowIcon, RocketIcon } from "@radix-ui/react-icons";
import { Notebook } from "@/types/notebook";
import { notebookService } from "@/services/notebookService";
import { useToast } from "@/components/hooks/use-toast";
import { parseApiError } from "@/lib/utils";

export default function NotebookList() {
  const [notebooks, setNotebooks] = useState<Notebook[]>([]);
  const [searchTerm, setSearchTerm] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const { toast } = useToast();

  useEffect(() => {
    const fetchNotebooks = async () => {
      try {
        const data = await notebookService.getNotebooks();
        setNotebooks(data);
      } catch (error) {
        toast(parseApiError(error));
      } finally {
        setIsLoading(false);
      }
    };
    fetchNotebooks();
  }, [toast]);

  const filteredNotebooks = notebooks.filter((notebook) =>
    notebook.name.toLowerCase().includes(searchTerm.toLowerCase())
  );

  if (isLoading) {
    return <div>Loading...</div>;
  }

  return (
    <>
      {notebooks.length === 0 ? (
        <div className="text-center">
          <p className="mb-4">No notebooks available.</p>
          <Link href="/notebooks/new">
            <Button>
              <RocketIcon className="mr-2 w-4 h-4" />
              New Notebook
            </Button>
          </Link>
        </div>
      ) : (
        <>
          <div className="mb-4 flex justify-between items-center">
            <Input
              type="text"
              placeholder="Search notebooks"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="max-w-sm"
            />
            <Link href="/notebooks/new" passHref>
              <Button>
                <RocketIcon className="mr-2 w-4 h-4" />
                New Notebook
              </Button>
            </Link>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {filteredNotebooks.map((notebook) => (
              <Card key={notebook.id}>
                <CardHeader>
                  <CardTitle>
                    <Link
                      href={`/notebooks/${notebook.id}`}
                      className="hover:text-blue-500 underline"
                    >
                      {notebook.name}
                    </Link>
                  </CardTitle>
                </CardHeader>
                <CardContent>
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
                </CardContent>
                <CardFooter className="flex justify-between">
                  <Button
                    disabled={!notebook.ready}
                    onClick={() => window.open(notebook.endpoint, "_blank")}
                  >
                    <OpenInNewWindowIcon className="mr-2 w-4 h-4" />
                    Connect
                  </Button>
                </CardFooter>
              </Card>
            ))}
          </div>
        </>
      )}
    </>
  );
}
