'use client';

import { useState, useEffect } from 'react';
import Header from '@/components/Header';
import Footer from '@/components/Footer';
import Link from 'next/link';

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
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('');
  const [selectedSubcategory, setSelectedSubcategory] = useState('');

  useEffect(() => {
    fetchModels();
  }, []);

  const fetchModels = async () => {
    try {
      const response = await fetch('/api/v1alpha1/models');
      if (!response.ok) {
        throw new Error('Failed to fetch models');
      }
      const data = await response.json();
      setModels(data);
    } catch (error) {
      console.error('Error fetching models:', error);
    }
  };

  const filteredModels = models.filter(
    (model) =>
      (model.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        model.modelId.toLowerCase().includes(searchTerm.toLowerCase())) &&
      (selectedCategory === '' || model.category === selectedCategory) &&
      (selectedSubcategory === '' || model.subcategory === selectedSubcategory)
  );

  const categories = Array.from(new Set(models.map((model) => model.category)));
  const subcategories = Array.from(new Set(models.map((model) => model.subcategory)));

  return (
    <div className="flex flex-col min-h-screen">
      <Header />
      <main className="flex-grow container mx-auto px-4 py-8">
        <h1 className="text-3xl font-bold mb-8">Model Catalog</h1>
        <div className="mb-4 flex space-x-4">
          <input
            type="text"
            placeholder="Search by model name or ID"
            className="w-full p-2 border rounded"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
          <select
            className="p-2 border rounded"
            value={selectedCategory}
            onChange={(e) => setSelectedCategory(e.target.value)}
          >
            <option value="">All Categories</option>
            {categories.map((category) => (
              <option key={category} value={category}>
                {category}
              </option>
            ))}
          </select>
          <select
            className="p-2 border rounded"
            value={selectedSubcategory}
            onChange={(e) => setSelectedSubcategory(e.target.value)}
          >
            <option value="">All Subcategories</option>
            {subcategories.map((subcategory) => (
              <option key={subcategory} value={subcategory}>
                {subcategory}
              </option>
            ))}
          </select>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredModels.map((model) => (
            <div key={model.id} className="bg-white shadow-lg rounded-lg overflow-hidden">
              <div className="p-6">
                <h2 className="text-2xl font-bold mb-2">{model.name}</h2>
                <div className="flex flex-wrap gap-2 mb-3">
                  {/* <span className="px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-sm">
                    {model.modelId}
                  </span> */}
                  <span className="px-2 py-1 bg-green-100 text-green-800 rounded-full text-sm">
                    {model.category}
                  </span>
                  <span className="px-2 py-1 bg-yellow-100 text-yellow-800 rounded-full text-sm">
                    {model.subcategory}
                  </span>
                </div>
                <p className="text-gray-700 mb-4">{model.description}</p>
                <p className="text-sm text-gray-600 mb-4">Size: {formatSize(model.size)}</p>
                <Link
                  href={`/launch-model/${model.id}`}
                  className="bg-blue-500 hover:bg-blue-600 text-white font-bold py-2 px-4 rounded transition duration-300 ease-in-out inline-block"
                >
                  Launch
                </Link>
              </div>
            </div>
          ))}
        </div>
      </main>
      <Footer />
    </div>
  );
}