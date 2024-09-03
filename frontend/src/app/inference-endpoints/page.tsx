'use client';

import { useState } from 'react';
import Header from '@/components/Header';
import Footer from '@/components/Footer';
import Link from 'next/link';

// Mock data for inference endpoints
const mockEndpoints = [
  { id: 1, name: 'GPT-3 Endpoint', modelReference: 'GPT-3' },
  { id: 2, name: 'DALL-E Endpoint', modelReference: 'DALL-E' },
  // Add more mock endpoints here
];

export default function InferenceEndpoints() {
  const [searchTerm, setSearchTerm] = useState('');

  const filteredEndpoints = mockEndpoints.filter(
    (endpoint) =>
      endpoint.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      endpoint.modelReference.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="flex flex-col min-h-screen">
      <Header />
      <main className="flex-grow container mx-auto px-4 py-8">
        <h1 className="text-3xl font-bold mb-8">Inference Endpoints</h1>
        <div className="mb-4">
          <input
            type="text"
            placeholder="Search by endpoint name or model reference"
            className="w-full p-2 border rounded"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredEndpoints.map((endpoint) => (
            <Link
              key={endpoint.id}
              href={`/inference-endpoints/${endpoint.id}`}
              className="border rounded p-4 hover:bg-gray-100 transition-colors"
            >
              <h2 className="text-xl font-bold">{endpoint.name}</h2>
              <p className="text-sm text-gray-600">Model: {endpoint.modelReference}</p>
            </Link>
          ))}
        </div>
      </main>
      <Footer />
    </div>
  );
}