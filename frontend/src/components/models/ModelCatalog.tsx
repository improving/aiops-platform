"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { HandIcon, RocketIcon, ArchiveIcon } from "@radix-ui/react-icons";
import { Model } from "@/types/models";
import { useToast } from "@/components/hooks/use-toast";
import { modelService } from "@/services/modelService";
import { formatEnumLabel, parseApiError } from "@/lib/utils";
import { DisplayCard } from "@/components/ui/DisplayCard";
import { GetModelIcon } from "@/lib/utils";
import { CardGridSkeleton } from "@/components/LoadingState";

function formatSize(bytes: number): string {
  const MB = 1024 * 1024;
  const GB = MB * 1024;
  if (bytes >= GB) {
    return `${(bytes / GB).toFixed(2)} GB`;
  } else {
    return `${(bytes / MB).toFixed(2)} MB`;
  }
}

export default function ModelCatalog() {
  const [models, setModels] = useState<Model[]>([]);
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedCategory, setSelectedCategory] = useState("all");
  const [selectedSubcategory, setSelectedSubcategory] = useState("all");
  const [loading, setLoading] = useState(true);
  const { toast } = useToast();

  const fetchModels = useCallback(async () => {
    try {
      const data = await modelService.getModels();
      setModels(data);
    } catch (error) {
      toast(parseApiError(error));
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    fetchModels();
  }, [fetchModels]);

  const filteredModels = models.filter(
    (model) =>
      (model.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        model.modelId.toLowerCase().includes(searchTerm.toLowerCase())) &&
      (selectedCategory === "all" || model.category === selectedCategory) &&
      (selectedSubcategory === "all" ||
        model.subcategory === selectedSubcategory)
  );

  const categories = Array.from(
    new Set(models.map((model) => model.category).filter(Boolean))
  );
  // A registry entry imported from a source (Hugging Face, Ollama,
  // OpenRouter) or added manually without one has no subcategory.
  const subcategories = Array.from(
    new Set(models.map((model) => model.subcategory).filter(Boolean))
  );

  if (loading) {
    return <CardGridSkeleton />;
  }

  return (
    <>
      <div className="mb-4 flex flex-wrap gap-4">
        <Input
          type="text"
          placeholder="Search by model name or ID"
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="w-full sm:w-auto sm:flex-1 sm:min-w-[200px]"
        />
        <Select value={selectedCategory} onValueChange={setSelectedCategory}>
          <SelectTrigger className="w-[180px]">
            <SelectValue placeholder="All Categories" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Categories</SelectItem>
            {categories.map((category) => (
              <SelectItem key={category} value={category}>
                {formatEnumLabel(category)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={selectedSubcategory}
          onValueChange={setSelectedSubcategory}
        >
          <SelectTrigger className="w-[180px]">
            <SelectValue placeholder="All Subcategories" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Subcategories</SelectItem>
            {subcategories.map((subcategory) => (
              <SelectItem key={subcategory} value={subcategory}>
                {formatEnumLabel(subcategory)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Link href="/models/registry" passHref>
          <Button variant="outline" icon={<ArchiveIcon className="w-4 h-4" />}>
            Manage registry
          </Button>
        </Link>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {filteredModels.map((model) => (
          <DisplayCard
            key={model.id}
            icon={GetModelIcon(model.modelId)}
            title={
              <Link
                href={`/models/${model.id}`}
                className="underline hover:text-blue-500"
              >
                {model.name}
              </Link>
            }
            description={model.modelId}
            content={
              <>
                <div className="flex flex-wrap gap-2 mb-3">
                  {model.category && (
                    <span className="px-2 py-1 bg-green-100 text-green-800 rounded-full text-sm">
                      {formatEnumLabel(model.category)}
                    </span>
                  )}
                  {model.subcategory && (
                    <span className="px-2 py-1 bg-yellow-100 text-yellow-800 rounded-full text-sm">
                      {formatEnumLabel(model.subcategory)}
                    </span>
                  )}
                  {model.countAdapters > 0 && (
                    <span className="px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-sm hover:bg-blue-200 hover:text-blue-900 underline">
                      <Link href={`/models/${model.id}?tab=adapters`}>
                        {model.countAdapters} adapters
                      </Link>
                    </span>
                  )}
                </div>
                <p className="text-gray-700 mb-4 line-clamp-2">
                  {model.description}
                </p>
                <p className="text-sm text-gray-600">
                  Size: {model.size ? formatSize(model.size) : "unknown"}
                </p>
              </>
            }
            footer={
              <div className="flex space-x-4">
                <Link href={`/models/launch/${model.id}`} passHref>
                  <Button
                    className="flex-1"
                    icon={<RocketIcon className="mr-2 w-4 h-4" />}
                  >
                    Launch
                  </Button>
                </Link>
                <Link href={`/models/${model.id}/finetune`} passHref>
                  <Button
                    variant="secondary"
                    className="flex-1"
                    icon={<HandIcon className="mr-2 w-4 h-4" />}
                  >
                    Fine-tune
                  </Button>
                </Link>
              </div>
            }
          />
        ))}
      </div>
    </>
  );
}
