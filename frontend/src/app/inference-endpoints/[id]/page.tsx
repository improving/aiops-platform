'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
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
  healthEndpoint: string;
  metricsEndpoint: string;
}

export default function InferenceEndpointDetails({ params }: { params: { id: string } }) {
  const router = useRouter();
  const [inferenceInstance, setInferenceInstance] = useState<InferenceInstance | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchInferenceInstance();
  }, [params.id]);

  const fetchInferenceInstance = async () => {
    try {
      const response = await fetch(`/api/v1alpha1/inferenceInstance/${params.id}`);
      if (!response.ok) {
        throw new Error('Failed to fetch inference instance');
      }
      const data = await response.json();
      setInferenceInstance(data);
      setLoading(false);
    } catch (error) {
      console.error('Error fetching inference instance:', error);
      setError('Failed to load inference instance details');
      setLoading(false);
    }
  };

  const handleDelete = async () => {
    if (window.confirm('Are you sure you want to delete this inference endpoint?')) {
      try {
        const response = await fetch(`/api/v1alpha1/inferenceInstance/${params.id}`, {
          method: 'DELETE',
        });
        if (!response.ok) {
          throw new Error('Failed to delete inference instance');
        }
        router.push('/inference-endpoints');
      } catch (error) {
        console.error('Error deleting inference instance:', error);
        setError('Failed to delete inference instance');
      }
    }
  };

  if (loading) {
    return <div>Loading...</div>;
  }

  if (error) {
    return <div>Error: {error}</div>;
  }

  if (!inferenceInstance) {
    return <div>No inference instance found</div>;
  }

  return (
    <div className="flex flex-col min-h-screen">
      <Header />
      <main className="flex-grow container mx-auto px-4 py-8">
        <h1 className="text-3xl font-bold mb-8">Inference Endpoint Details</h1>
        <div className="bg-white shadow-lg rounded-lg p-6">
          <h2 className="text-2xl font-bold mb-4">{inferenceInstance.model.name}</h2>
          <p className="mb-2"><strong>ID:</strong> {inferenceInstance.id}</p>
          <p className="mb-2"><strong>Model ID:</strong> {inferenceInstance.model.id}</p>
          <p className="mb-2"><strong>Engine:</strong> {inferenceInstance.engine.name}</p>
          <p className="mb-2"><strong>Host:</strong> {inferenceInstance.host}</p>
          <p className="mb-2"><strong>Endpoint:</strong> {inferenceInstance.endpoint}</p>
          <p className="mb-2"><strong>Health Endpoint:</strong> {inferenceInstance.healthEndpoint}</p>
          <p className="mb-2"><strong>Metrics Endpoint:</strong> {inferenceInstance.metricsEndpoint}</p>
          <button
            onClick={handleDelete}
            className="bg-red-500 hover:bg-red-600 text-white font-bold py-2 px-4 rounded mt-4"
          >
            Delete Inference Endpoint
          </button>
        </div>
      </main>
      <Footer />
    </div>
  );
}