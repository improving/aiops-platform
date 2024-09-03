'use client';

import { useState } from 'react';
import Header from '@/components/Header';
import Footer from '@/components/Footer';
import Link from 'next/link';

// Mock data for models
const mockModels = [
  { id: 1, name: 'GPT-3', type: 'Language Model', author: 'OpenAI', description: 'Large language model' },
  { id: 2, name: 'DALL-E', type: 'Image Generation', author: 'OpenAI', description: 'Text to image model' },
  // Add more mock models here
];

export default function ModelCatalog() {
  const [searchTerm, setSearchTerm] = useState('');

  const filteredModels = mockModels.filter(
    (model) =>
      model.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      model.author.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="flex flex-col min-h-screen">
      <Header />
      <main className="flex-grow container mx-auto px-4 py-8">
        <h1 className="text-3xl font-bold mb-8">Model Catalog</h1>
        <div className="mb-4">
          <input
            type="text"
            placeholder="Search by model name or author"
            className="w-full p-2 border rounded"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredModels.map((model) => (
            <div key={model.id} className="bg-white shadow-lg rounded-lg overflow-hidden">
              <div className="p-6">
                <h2 className="text-2xl font-bold mb-2">{model.name}</h2>
                <p className="text-sm text-gray-600 mb-1">{model.type}</p>
                <p className="text-sm text-gray-600 mb-3">Author: {model.author}</p>
                <p className="text-gray-700 mb-4">{model.description}</p>
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