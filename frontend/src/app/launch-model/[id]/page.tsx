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

export default function LaunchModel({ params }: { params: { id: string } }) {
  const router = useRouter();
  const [activeTab, setActiveTab] = useState(tabs[0]);
  const [formData, setFormData] = useState({
    acceleratorType: '',
    acceleratorCount: 1,
    engineId: '',
  });
  const [envVars, setEnvVars] = useState<EnvVar[]>([{ name: '', value: '' }]);
  const [secrets, setSecrets] = useState<EnvVar[]>([{ name: '', value: '' }]);
  const [engines, setEngines] = useState<Engine[]>([]);

  useEffect(() => {
    fetchEngines();
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

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    // Here you would typically send the form data to your backend
    console.log('Form submitted:', { ...formData, envVars, secrets });
    // Redirect to the inference endpoint details page
    router.push(`/inference-endpoints/${params.id}`);
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
        <form onSubmit={handleSubmit} className="max-w-lg mx-auto">
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
              <select
                name="acceleratorType"
                value={formData.acceleratorType}
                onChange={handleInputChange}
                className="w-full p-2 border rounded mb-2"
              >
                <option value="">Select Accelerator Type</option>
                <option value="GPU">GPU</option>
                <option value="TPU">TPU</option>
                <option value="FPGA">FPGA</option>
              </select>
              <input
                type="number"
                name="acceleratorCount"
                value={formData.acceleratorCount}
                onChange={handleInputChange}
                min="1"
                className="w-full p-2 border rounded mb-4"
                placeholder="Number of accelerators"
              />
              <button
                type="button"
                onClick={handleNext}
                className="bg-blue-500 hover:bg-blue-600 text-white font-bold py-2 px-4 rounded"
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