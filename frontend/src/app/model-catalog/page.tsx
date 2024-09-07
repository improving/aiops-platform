"use client";

import { useState, useEffect } from "react";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
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

interface Model {
  id: string;
  name: string;
  modelId: string;
  description: string;
  category: string;
  subcategory: string;
  size: number;
}

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

  useEffect(() => {
    fetchModels();
  }, []);

  const fetchModels = async () => {
    try {
      const response = await fetch("/api/v1alpha1/models");
      if (!response.ok) {
        throw new Error("Failed to fetch models");
      }
      const data = await response.json();
      setModels(data);
    } catch (error) {
      console.error("Error fetching models:", error);
    }
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
    <div className="flex flex-col min-h-screen">
      <Header />
      <main className="flex-grow container mx-auto px-4 py-8">
        <h1 className="text-3xl font-bold mb-8">Model Catalog</h1>
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
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredModels.map((model) => (
            <Card key={model.id}>
              <CardHeader>
                <CardTitle>{model.name}</CardTitle>
                <CardDescription>{model.modelId}</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-2 mb-3">
                  <span className="px-2 py-1 bg-green-100 text-green-800 rounded-full text-sm">
                    {model.category}
                  </span>
                  <span className="px-2 py-1 bg-yellow-100 text-yellow-800 rounded-full text-sm">
                    {model.subcategory}
                  </span>
                </div>
                <p className="text-gray-700 mb-4">{model.description}</p>
                <p className="text-sm text-gray-600 mb-4">
                  Size: {formatSize(model.size)}
                </p>
              </CardContent>
              <CardFooter>
                <Link href={`/launch-model/${model.id}`} passHref>
                  <Button>Launch</Button>
                </Link>
              </CardFooter>
            </Card>
          ))}
        </div>
      </main>
      <Footer />
    </div>
  );
}
