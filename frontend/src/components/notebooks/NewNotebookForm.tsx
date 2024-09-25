"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { RocketIcon } from "@radix-ui/react-icons";

export default function NewNotebookForm() {
  const router = useRouter();
  const [formData, setFormData] = useState({
    name: "",
    type: "jupyter",
    framework: "pytorch",
    resources_cpu: "0.5",
    resources_memory: "1",
    nvidia_gpu: false,
    resources_gpu: "1",
    storage_size: "5",
  });

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  const handleSelectChange = (name: string, value: string) => {
    if (name === "type" && value === "jupyter") {
      setFormData((prev) => ({ ...prev, framework: "pytorch" }));
    } else if (name === "type" && value === "vscode") {
      setFormData((prev) => ({ ...prev, framework: "" }));
    }
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  const handleSwitchChange = (checked: boolean) => {
    setFormData((prev) => ({ ...prev, nvidia_gpu: checked }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const updatedFormData = {
        ...formData,
        resources_memory: `${formData.resources_memory}Gi`,
        storage_size: `${formData.storage_size}Gi`,
      };
      const response = await fetch("/api/v1alpha1/notebooks", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(updatedFormData),
      });

      if (!response.ok) {
        throw new Error("Failed to create notebook");
      }

      router.push("/notebooks");
    } catch (error) {
      console.error("Error creating notebook:", error);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <div>
        <Label htmlFor="name">Name</Label>
        <Input
          id="name"
          name="name"
          value={formData.name}
          onChange={handleInputChange}
          required
        />
      </div>

      <div>
        <Label htmlFor="type">Type</Label>
        <Select
          name="type"
          value={formData.type}
          onValueChange={(value) => handleSelectChange("type", value)}
        >
          <SelectTrigger>
            <SelectValue placeholder="Select type" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="jupyter">Jupyter</SelectItem>
            <SelectItem value="vscode">VSCode</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {formData.type === "jupyter" && (
        <div>
          <Label htmlFor="framework">Framework</Label>
          <Select
            name="framework"
            value={formData.framework}
            onValueChange={(value) => handleSelectChange("framework", value)}
          >
            <SelectTrigger>
              <SelectValue placeholder="Select framework" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="pytorch">PyTorch</SelectItem>
              <SelectItem value="tensorflow">TensorFlow</SelectItem>
            </SelectContent>
          </Select>
        </div>
      )}

      <div>
        <Label htmlFor="resources_cpu">Resources CPU</Label>
        <Input
          id="resources_cpu"
          name="resources_cpu"
          type="number"
          min="0.5"
          max="4"
          step="0.5"
          value={formData.resources_cpu}
          onChange={handleInputChange}
          required
        />
      </div>

      <div>
        <Label htmlFor="resources_memory">Resources Memory (GB)</Label>
        <Input
          id="resources_memory"
          name="resources_memory"
          type="number"
          min="1"
          max="32"
          value={formData.resources_memory}
          onChange={handleInputChange}
          required
        />
      </div>

      {formData.type === "jupyter" && (
        <div className="flex items-center space-x-2">
          <Switch
            id="nvidia_gpu"
            checked={formData.nvidia_gpu}
            onCheckedChange={handleSwitchChange}
          />
          <Label htmlFor="nvidia_gpu">Nvidia GPU</Label>
        </div>
      )}

      {formData.nvidia_gpu && (
        <div>
          <Label htmlFor="resources_gpu">Resources GPU</Label>
          <Input
            id="resources_gpu"
            name="resources_gpu"
            type="number"
            min="1"
            max="4"
            value={formData.resources_gpu}
            onChange={handleInputChange}
            required
          />
        </div>
      )}

      <div>
        <Label htmlFor="storage_size">Storage Size (GB)</Label>
        <Input
          id="storage_size"
          name="storage_size"
          type="number"
          min="5"
          max="20"
          value={formData.storage_size}
          onChange={handleInputChange}
          required
        />
      </div>

      <Button type="submit">
        <RocketIcon className="mr-2 w-4 h-4" />
        Launch
      </Button>
    </form>
  );
}