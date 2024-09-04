'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Header from '@/components/Header';
import Footer from '@/components/Footer';

const tabs = ['accelerators', 'deployConfig', 'envVars'];

type EnvVar = { name: string; value: string };

interface Engine {
  id: string;
  name: string;
  description: string;
  helm_chart_repo: string;
}

interface Host {
  hostname: string;
  cpu_vendor: string;
  cpu_memory: number;
  cpu_cores: number;
  cuda_driver_version: string;
  cuda_runtime_version: string;
  gpu_count: number;
  gpu_memory: number;
  gpu_model: string;
  gpu_replicas: number;
  gpu_sharing_strategy: string;
}

export default function LaunchModel({ params }: { params: { id: string } }) {
  const router = useRouter();
  const [activeTab, setActiveTab] = useState(tabs[0]);
  const [formData, setFormData] = useState({
    hostId: '',
    engineId: '',
  });
  const [envVars, setEnvVars] = useState<EnvVar[]>([{ name: '', value: '' }]);
  const [secrets, setSecrets] = useState<EnvVar[]>([{ name: '', value: '' }]);
  const [engines, setEngines] = useState<Engine[]>([]);
  const [hosts, setHosts] = useState<Host[]>([]);

  useEffect(() => {
    fetchEngines();
    fetchHosts();
  }, []);

  const fetchEngines = async () => {
    try {
      const response = await fetch('/api/v1alpha1/engines');
      if (!response.ok) {
        throw new Error('Failed to fetch engines');
      }
      const data = await response.json();
      setEngines(data);
    } catch (error) {
      console.error('Error fetching engines:', error);
    }
  };

  const fetchHosts = async () => {
    try {
      const response = await fetch('/api/v1alpha1/hosts');
      if (!response.ok) {
        throw new Error('Failed to fetch hosts');
      }
      const data = await response.json();
      setHosts(data);
    } catch (error) {
      console.error('Error fetching hosts:', error);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    const payload = {
      model: {
        id: params.id, // This is the model ID from the URL
      },
      engine: {
        id: formData.engineId,
      },
      host: formData.hostId,
      config: {
        maxInputLength: 0,
        maxTokens: 0,
        maxBatchPrefillTokens: 0,
        maxBatchTotalTokens: 0,
        quantization: "",
        image: ""
      }, // Config with default values as per the instruction
    };

    try {
      const response = await fetch('/api/v1alpha1/inferenceInstance', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        throw new Error('Failed to create inference instance');
      }

      const data = await response.json();
      // Redirect to the individual inference endpoint page
      router.push(`/inference-endpoints/${data.id}`);
    } catch (error) {
      console.error('Error creating inference instance:', error);
      // Handle error (e.g., show an error message to the user)
    }
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLSelectElement | HTMLInputElement>) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  const handleNext = () => {
    const currentIndex = tabs.indexOf(activeTab);
    if (currentIndex < tabs.length - 1) {
      setActiveTab(tabs[currentIndex + 1]);
    }
  };

  const handleEnvVarChange = (index: number, field: 'name' | 'value', value: string) => {
    const newEnvVars = [...envVars];
    newEnvVars[index][field] = value;
    setEnvVars(newEnvVars);
  };

  const handleSecretChange = (index: number, field: 'name' | 'value', value: string) => {
    const newSecrets = [...secrets];
    newSecrets[index][field] = value;
    setSecrets(newSecrets);
  };

  const addEnvVar = () => {
    setEnvVars([...envVars, { name: '', value: '' }]);
  };

  const addSecret = () => {
    setSecrets([...secrets, { name: '', value: '' }]);
  };

  return (
    <div className="flex flex-col min-h-screen">
      <Header />
      <main className="flex-grow container mx-auto px-4 py-8">
        <h1 className="text-3xl font-bold mb-8">Launch Model</h1>
        <form onSubmit={handleSubmit} className="max-w-6xl mx-auto">
          <div className="mb-4">
            <div className="flex border-b">
              {tabs.map((tab) => (
                <button
                  key={tab}
                  type="button"
                  className={`py-2 px-4 ${activeTab === tab ? 'border-b-2 border-blue-500' : ''}`}
                  onClick={() => setActiveTab(tab)}
                >
                  {tab === 'accelerators' ? 'Accelerators' : 
                   tab === 'deployConfig' ? 'Deploy Config' : 
                   'Environment Variables and Secrets'}
                </button>
              ))}
            </div>
          </div>

          {activeTab === 'accelerators' && (
            <div>
              <h2 className="text-xl font-bold mb-4">Select Accelerator</h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                {hosts.map((host) => (
                  <div
                    key={host.hostname}
                    className={`bg-white shadow-lg rounded-lg overflow-hidden cursor-pointer transition duration-300 ease-in-out ${
                      formData.hostId === host.hostname ? 'ring-2 ring-blue-500' : 'hover:shadow-xl'
                    }`}
                    onClick={() => setFormData((prev) => ({ ...prev, hostId: host.hostname }))}
                  >
                    <div className="p-6">
                      <h3 className="text-2xl font-bold mb-2">
                        {host.gpu_model && host.gpu_model !== 'N/A' ? host.gpu_model : host.cpu_vendor}
                      </h3>
                      <div className="flex flex-wrap gap-2 mb-3">
                        {host.gpu_count > 0 && (
                          <span className="px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-sm">
                            {host.gpu_count} GPU
                          </span>
                        )}
                        {host.gpu_memory > 0 && (
                          <span className="px-2 py-1 bg-green-100 text-green-800 rounded-full text-sm">
                            {(host.gpu_memory / 1024).toFixed(1)} GB GPU Memory
                          </span>
                        )}
                        {host.cpu_cores > 0 && (
                          <span className="px-2 py-1 bg-yellow-100 text-yellow-800 rounded-full text-sm">
                            {host.cpu_cores} CPU Cores
                          </span>
                        )}
                      </div>
                      {host.cpu_cores > 0 && (
                        <p className="text-sm text-gray-600 mb-4">
                          CPU: {host.cpu_vendor} - {(host.cpu_memory / 1024).toFixed(1)} GB Memory
                        </p>
                      )}
                      {/* {host.cuda_driver_version && (
                        <p className="text-sm text-gray-600">CUDA Driver: {host.cuda_driver_version}</p>
                      )} */}
                    </div>
                  </div>
                ))}
              </div>
              <button
                type="button"
                onClick={handleNext}
                className="bg-blue-500 hover:bg-blue-600 text-white font-bold py-2 px-4 rounded mt-6 transition duration-300 ease-in-out"
              >
                Next
              </button>
            </div>
          )}

          {activeTab === 'deployConfig' && (
            <div>
              <select
                name="engineId"
                value={formData.engineId}
                onChange={handleInputChange}
                className="w-full p-2 border rounded mb-4"
              >
                <option value="">Select Engine</option>
                {engines.map((engine) => (
                  <option key={engine.id} value={engine.id}>
                    {engine.name}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={handleNext}
                className="bg-blue-500 hover:bg-blue-600 text-white font-bold py-2 px-4 rounded"
              >
                Next
              </button>
            </div>
          )}

          {activeTab === 'envVars' && (
            <div>
              <h2 className="text-xl font-bold mb-4">Environment Variables</h2>
              {envVars.map((envVar, index) => (
                <div key={index} className="mb-4 flex space-x-2">
                  <input
                    type="text"
                    value={envVar.name}
                    onChange={(e) => handleEnvVarChange(index, 'name', e.target.value)}
                    className="w-1/2 p-2 border rounded"
                    placeholder="Name"
                  />
                  <input
                    type="text"
                    value={envVar.value}
                    onChange={(e) => handleEnvVarChange(index, 'value', e.target.value)}
                    className="w-1/2 p-2 border rounded"
                    placeholder="Value"
                  />
                </div>
              ))}
              <button
                type="button"
                onClick={addEnvVar}
                className="bg-gray-300 hover:bg-gray-400 text-gray-800 font-bold py-2 px-4 rounded mb-4"
              >
                +
              </button>

              <h2 className="text-xl font-bold mb-4 mt-6">Secrets</h2>
              {secrets.map((secret, index) => (
                <div key={index} className="mb-4 flex space-x-2">
                  <input
                    type="text"
                    value={secret.name}
                    onChange={(e) => handleSecretChange(index, 'name', e.target.value)}
                    className="w-1/2 p-2 border rounded"
                    placeholder="Name"
                  />
                  <input
                    type="password"
                    value={secret.value}
                    onChange={(e) => handleSecretChange(index, 'value', e.target.value)}
                    className="w-1/2 p-2 border rounded"
                    placeholder="Value"
                  />
                </div>
              ))}
              <button
                type="button"
                onClick={addSecret}
                className="bg-gray-300 hover:bg-gray-400 text-gray-800 font-bold py-2 px-4 rounded mb-4"
              >
                +
              </button>

              <button
                type="submit"
                className="bg-green-500 hover:bg-green-600 text-white font-bold py-2 px-4 rounded mt-6"
              >
                Create Inference Endpoint
              </button>
            </div>
          )}
        </form>
      </main>
      <Footer />
    </div>
  );
}