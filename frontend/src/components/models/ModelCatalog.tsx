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
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { HandIcon, RocketIcon, PlusIcon } from "@radix-ui/react-icons";
import { Model } from "@/types/models";
import { useToast } from "@/components/hooks/use-toast";
import ImportModelDialog from "@/components/models/ImportModelDialog";
import Image from "next/image";
import { modelService } from "@/services/modelService";
import { parseApiError } from "@/lib/utils";

function formatSize(bytes: number): string {
  const MB = 1024 * 1024;
  const GB = MB * 1024;
  if (bytes >= GB) {
    return `${(bytes / GB).toFixed(2)} GB`;
  } else {
    return `${(bytes / MB).toFixed(2)} MB`;
  }
}

function getModelIcon(modelId: string) {
  switch (modelId.split("/")[0]) {
    case "meta-llama":
      return "/models/meta-llama.png";
    case "microsoft":
      return "/models/microsoft.png";
    case "nvidia":
      return "/models/nvidia.png";
    default:
      return "/models/pixtide.png";
  }
}

export default function ModelCatalog() {
  const [models, setModels] = useState<Model[]>([]);
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedCategory, setSelectedCategory] = useState("all");
  const [selectedSubcategory, setSelectedSubcategory] = useState("all");
  const [isImportDialogOpen, setIsImportDialogOpen] = useState(false);
  const { toast } = useToast();

  const fetchModels = useCallback(async () => {
    try {
      const data = await modelService.getModels();
      setModels(data);
    } catch (error) {
      toast(parseApiError(error));
    }
  }, [toast]);

  useEffect(() => {
    fetchModels();
  }, [fetchModels]);

  const handleImportSuccess = () => {
    setIsImportDialogOpen(false);
    fetchModels();
    toast({
      title: "Success",
      description: "Model imported successfully.",
    });
  };

  const filteredModels = models.filter(
    (model) =>
      (model.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        model.modelId.toLowerCase().includes(searchTerm.toLowerCase())) &&
      (selectedCategory === "all" || model.category === selectedCategory) &&
      (selectedSubcategory === "all" ||
        model.subcategory === selectedSubcategory)
  );

  const categories = Array.from(new Set(models.map((model) => model.category)));
  const subcategories = Array.from(
    new Set(models.map((model) => model.subcategory))
  );

  return (
    <>
      <div className="mb-4 flex space-x-4">
        <Input
          type="text"
          placeholder="Search by model name or ID"
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
        />
        <Select value={selectedCategory} onValueChange={setSelectedCategory}>
          <SelectTrigger className="w-[180px]">
            <SelectValue placeholder="All Categories" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Categories</SelectItem>
            {categories.map((category) => (
              <SelectItem key={category} value={category}>
                {category}
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
                {subcategory}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button onClick={() => setIsImportDialogOpen(true)}>
          <PlusIcon className="mr-2 w-4 h-4" />
          Import Model
        </Button>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {filteredModels.map((model) => (
          <Card key={model.id} className="flex flex-col">
            <CardHeader className="flex-grow">
              <div className="flex items-start space-x-4">
                <div className="relative w-9 h-9">
                  <Image
                    src={getModelIcon(model.modelId)}
                    alt={`${model.name} icon`}
                    layout="fill"
                    objectFit="contain"
                    className="rounded-md"
                  />
                </div>
                <div>
                  <CardTitle>
                    <Link
                      href={`/models/${model.id}`}
                      className="underline hover:text-blue-500"
                    >
                      {model.name}
                    </Link>
                  </CardTitle>
                  <CardDescription>{model.modelId}</CardDescription>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-2 mb-3">
                <span className="px-2 py-1 bg-green-100 text-green-800 rounded-full text-sm">
                  {model.category}
                </span>
                <span className="px-2 py-1 bg-yellow-100 text-yellow-800 rounded-full text-sm">
                  {model.subcategory}
                </span>
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
                Size: {formatSize(model.size)}
              </p>
            </CardContent>
            <CardFooter className="mt-auto">
              <div className="flex justify-between space-x-4">
                <Link href={`/models/launch/${model.id}`} passHref>
                  <Button className="flex-1">
                    <RocketIcon className="mr-2 w-4 h-4" />
                    Launch
                  </Button>
                </Link>
                <Link href={`/models/${model.id}/finetune`} passHref>
                  <Button variant="secondary" className="flex-1">
                    <HandIcon className="mr-2 w-4 h-4" />
                    Fine-tune
                  </Button>
                </Link>
              </div>
            </CardFooter>
          </Card>
        ))}
      </div>
      <ImportModelDialog
        isOpen={isImportDialogOpen}
        onClose={() => setIsImportDialogOpen(false)}
        onSuccess={handleImportSuccess}
      />
    </>
  );
}
