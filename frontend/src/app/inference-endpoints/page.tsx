'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import Header from '@/components/Header';
import Footer from '@/components/Footer';

interface InferenceInstance {
  id: string;
  model: {
    id: string;
    name: string;
  };
  engine: {
    id: string;
    name: string;
  };
  host: string;
  endpoint: string;
}

export default function InferenceEndpoints() {
  const [endpoints, setEndpoints] = useState<InferenceInstance[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchEndpoints();
  }, []);

  const fetchEndpoints = async () => {
    try {
      const response = await fetch('/api/v1alpha1/inferenceInstance');
      if (!response.ok) {
        throw new Error('Failed to fetch inference instances');
      }
      const data = await response.json();
      setEndpoints(data);
      setLoading(false);
    } catch (error) {
      console.error('Error fetching inference instances:', error);
      setError('Failed to load inference instances');
      setLoading(false);
    }
  };

  if (loading) {
    return <div>Loading...</div>;
  }

  if (error) {
    return <div>Error: {error}</div>;
  }

  return (
    <div className="flex flex-col min-h-screen">
      <Header />
      <main className="flex-grow container mx-auto px-4 py-8">
        <h1 className="text-3xl font-bold mb-8">Inference Endpoints</h1>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {endpoints.map((endpoint) => (
            <Link
              key={endpoint.id}
              href={`/inference-endpoints/${endpoint.id}`}
              className="bg-white shadow-lg rounded-lg overflow-hidden hover:shadow-xl transition duration-300 ease-in-out"
            >
              <div className="p-6">
                <h2 className="text-2xl font-bold mb-2">{endpoint.model.name}</h2>
                <div className="flex flex-wrap gap-2 mb-3">
                  <span className="px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-sm">
                    {endpoint.engine.name}
                  </span>
                  <span className="px-2 py-1 bg-green-100 text-green-800 rounded-full text-sm">
                    {endpoint.host}
                  </span>
                </div>
                <p className="text-sm text-gray-600 mb-2">
                  <strong>ID:</strong> {endpoint.id}
                </p>
                <p className="text-sm text-gray-600 mb-2">
                  <strong>Endpoint:</strong> {endpoint.endpoint}
                </p>
                {/* <Link
                  href={`/model-catalog/${endpoint.model.id}`}
                  className="text-blue-500 hover:text-blue-600 transition duration-300 ease-in-out"
                  onClick={(e) => e.stopPropagation()}
                >
                  View Model Details
                </Link> */}
              </div>
            </Link>
          ))}
        </div>
      </main>
      <Footer />
    </div>
  );
}