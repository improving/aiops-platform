"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

const tabs = ["accelerators", "deployConfig", "envVars"];

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
  const [activeTab, setActiveTab] = useState("accelerators");
  const [formData, setFormData] = useState({
    hostId: "",
    engineId: "",
  });
  const [envVars, setEnvVars] = useState<EnvVar[]>([{ name: "", value: "" }]);
  const [secrets, setSecrets] = useState<EnvVar[]>([{ name: "", value: "" }]);
  const [engines, setEngines] = useState<Engine[]>([]);
  const [hosts, setHosts] = useState<Host[]>([]);

  useEffect(() => {
    fetchEngines();
    fetchHosts();
  }, []);

  const fetchEngines = async () => {
    try {
      const response = await fetch("/api/v1alpha1/engines");
      if (!response.ok) {
        throw new Error("Failed to fetch engines");
      }
      const data = await response.json();
      setEngines(data);
    } catch (error) {
      console.error("Error fetching engines:", error);
    }
  };

  const fetchHosts = async () => {
    try {
      const response = await fetch("/api/v1alpha1/hosts");
      if (!response.ok) {
        throw new Error("Failed to fetch hosts");
      }
      const data = await response.json();
      setHosts(data);
    } catch (error) {
      console.error("Error fetching hosts:", error);
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
        image: "",
      }, // Config with default values as per the instruction
    };

    try {
      const response = await fetch("/api/v1alpha1/inferenceInstance", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        throw new Error("Failed to create inference instance");
      }

      const data = await response.json();
      // Redirect to the individual inference endpoint page
      router.push(`/inference-endpoints/${data.id}`);
    } catch (error) {
      console.error("Error creating inference instance:", error);
      // Handle error (e.g., show an error message to the user)
    }
  };

  const handleInputChange = (
    e: React.ChangeEvent<HTMLSelectElement | HTMLInputElement>
  ) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  const handleNext = () => {
    if (activeTab === "accelerators") {
      setActiveTab("deployConfig");
    } else if (activeTab === "deployConfig") {
      setActiveTab("envVars");
    }
  };

  const handleEnvVarChange = (
    index: number,
    field: "name" | "value",
    value: string
  ) => {
    const newEnvVars = [...envVars];
    newEnvVars[index][field] = value;
    setEnvVars(newEnvVars);
  };

  const handleSecretChange = (
    index: number,
    field: "name" | "value",
    value: string
  ) => {
    const newSecrets = [...secrets];
    newSecrets[index][field] = value;
    setSecrets(newSecrets);
  };

  const addEnvVar = () => {
    setEnvVars([...envVars, { name: "", value: "" }]);
  };

  const addSecret = () => {
    setSecrets([...secrets, { name: "", value: "" }]);
  };

  return (
    <div className="flex flex-col min-h-screen">
      <Header />
      <main className="flex-grow container mx-auto px-4 py-8">
        <h1 className="text-3xl font-bold mb-8">Launch Model</h1>
        <form onSubmit={handleSubmit} className="max-w-6xl mx-auto">
          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsList className="grid w-full grid-cols-3">
              <TabsTrigger value="accelerators">Accelerators</TabsTrigger>
              <TabsTrigger value="deployConfig">Deploy Config</TabsTrigger>
              <TabsTrigger value="envVars">
                Environment Variables and Secrets
              </TabsTrigger>
            </TabsList>
            <TabsContent value="accelerators">
              <Card>
                <CardHeader>
                  <CardTitle>Select Accelerator</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    {hosts.map((host) => (
                      <Card
                        key={host.hostname}
                        className={`cursor-pointer transition duration-300 ease-in-out ${
                          formData.hostId === host.hostname
                            ? "ring-2 ring-blue-500"
                            : "hover:shadow-xl"
                        }`}
                        onClick={() =>
                          setFormData((prev) => ({
                            ...prev,
                            hostId: host.hostname,
                          }))
                        }
                      >
                        <CardHeader>
                          <CardTitle>
                            {host.gpu_model && host.gpu_model !== "N/A"
                              ? host.gpu_model
                              : host.cpu_vendor}
                          </CardTitle>
                        </CardHeader>
                        <CardContent>
                          <div className="flex flex-wrap gap-2 mb-3">
                            {host.gpu_count > 0 && (
                              <span className="px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-sm">
                                {host.gpu_count} GPU
                              </span>
                            )}
                            {host.gpu_memory > 0 && (
                              <span className="px-2 py-1 bg-green-100 text-green-800 rounded-full text-sm">
                                {(host.gpu_memory / 1024).toFixed(1)} GB GPU
                                Memory
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
                              CPU: {host.cpu_vendor} -{" "}
                              {(host.cpu_memory / 1024).toFixed(1)} GB Memory
                            </p>
                          )}
                        </CardContent>
                      </Card>
                    ))}
                  </div>
                </CardContent>
                <CardFooter>
                  <Button type="button" onClick={handleNext}>
                    Next
                  </Button>
                </CardFooter>
              </Card>
            </TabsContent>
            <TabsContent value="deployConfig">
              <Card>
                <CardHeader>
                  <CardTitle>Deploy Configuration</CardTitle>
                </CardHeader>
                <CardContent>
                  <Select
                    name="engineId"
                    value={formData.engineId}
                    onValueChange={(value) =>
                      setFormData((prev) => ({ ...prev, engineId: value }))
                    }
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Select Engine" />
                    </SelectTrigger>
                    <SelectContent>
                      {engines.map((engine) => (
                        <SelectItem key={engine.id} value={engine.id}>
                          {engine.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </CardContent>
                <CardFooter>
                  <Button type="button" onClick={handleNext}>
                    Next
                  </Button>
                </CardFooter>
              </Card>
            </TabsContent>
            <TabsContent value="envVars">
              <Card>
                <CardHeader>
                  <CardTitle>Environment Variables and Secrets</CardTitle>
                </CardHeader>
                <CardContent>
                  <h2 className="text-xl font-bold mb-4">
                    Environment Variables
                  </h2>
                  {envVars.map((envVar, index) => (
                    <div key={index} className="mb-4 flex space-x-2">
                      <Input
                        value={envVar.name}
                        onChange={(e) =>
                          handleEnvVarChange(index, "name", e.target.value)
                        }
                        placeholder="Name"
                      />
                      <Input
                        value={envVar.value}
                        onChange={(e) =>
                          handleEnvVarChange(index, "value", e.target.value)
                        }
                        placeholder="Value"
                      />
                    </div>
                  ))}
                  <Button
                    variant="outline"
                    onClick={addEnvVar}
                    className="mb-4"
                  >
                    Add Environment Variable
                  </Button>

                  <h2 className="text-xl font-bold mb-4 mt-6">Secrets</h2>
                  {secrets.map((secret, index) => (
                    <div key={index} className="mb-4 flex space-x-2">
                      <Input
                        value={secret.name}
                        onChange={(e) =>
                          handleSecretChange(index, "name", e.target.value)
                        }
                        placeholder="Name"
                      />
                      <Input
                        type="password"
                        value={secret.value}
                        onChange={(e) =>
                          handleSecretChange(index, "value", e.target.value)
                        }
                        placeholder="Value"
                      />
                    </div>
                  ))}
                  <Button
                    variant="outline"
                    onClick={addSecret}
                    className="mb-4"
                  >
                    Add Secret
                  </Button>
                </CardContent>
                <CardFooter>
                  <Button type="submit">Create Inference Endpoint</Button>
                </CardFooter>
              </Card>
            </TabsContent>
          </Tabs>
        </form>
      </main>
      <Footer />
    </div>
  );
}
