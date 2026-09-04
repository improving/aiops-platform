"use client";

import { useEffect, useState, useRef } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useToast } from "@/components/hooks/use-toast";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { FineTuneConfig, FineTuneParams, Dataset, Model } from "@/types/models";
import yaml from "yaml";
import { RocketIcon, UploadIcon } from "@radix-ui/react-icons";
import { modelService } from "@/services/modelService";
import { parseApiError } from "@/lib/utils";

export default function ModelFineTune({ params }: { params: { id: string } }) {
  const router = useRouter();
  const { toast } = useToast();
  const [model, setModel] = useState<Model>();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isLoadingFile, setIsLoadingFile] = useState(false);

  useEffect(() => {
    async function fetchModel() {
      try {
        const data = await modelService.getModelById(params.id);
        setModel(data);
        setFineTuneConfig((prev) => ({
          ...prev,
          base_model: data.modelId,
        }));
      } catch (error) {
        toast(parseApiError(error));
      }
    }
    fetchModel();
  }, [params.id, toast]);

  const [fineTuneConfig, setFineTuneConfig] = useState<FineTuneConfig>({
    task: "",
    base_model: "",
    project_name: "",
    log: "tensorboard",
    backend: "local",
    data: {
      path: "",
      train_split: "train",
      valid_split: null,
      chat_template: "tokenizer",
      column_mapping: {
        text_column: null,
        prompt_text_column: null,
        rejected_text_column: null,
      },
    },
    params: {
      unsloth: false,
      block_size: 128,
      model_max_length: 512,
      epochs: 2,
      batch_size: 1,
      lr: 1e-5,
      quantization: null,
      target_modules: null,
      merge_adapter: false,
      peft: true,
      lora_r: 16,
      lora_alpha: 32,
      lora_dropout: 0.05,
      padding: "right",
      optimizer: "paged_adamw_8bit",
      scheduler: "cosine",
      gradient_accumulation: 4,
      mixed_precision: null,
    },
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);

    try {
      await modelService.startFineTuning(params.id, {
        name: fineTuneConfig.project_name,
        params: fineTuneConfig,
      });
      toast({
        title: "Success",
        description: "Fine-tuning process started successfully",
        variant: "success",
      });
      router.push(`/models/${params.id}?tab=finetune`);
    } catch (error) {
      toast(parseApiError(error));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleParamChange = (key: keyof FineTuneParams, value: any) => {
    if (value == "none") {
      value = null;
    }
    setFineTuneConfig((prev) => ({
      ...prev,
      params: { ...prev.params, [key]: value },
    }));
  };

  const handleDatasetChange = (key: keyof Dataset, value: any) => {
    setFineTuneConfig((prev) => ({
      ...prev,
      data: { ...prev.data, [key]: value },
    }));
  };

  const handleColumnMappingChange = (key: string, value: string | null) => {
    setFineTuneConfig((prev) => ({
      ...prev,
      data: {
        ...prev.data,
        column_mapping: {
          ...prev.data.column_mapping,
          [key]: value,
        },
      },
    }));
  };

  const handleImportYaml = (event: React.ChangeEvent<HTMLInputElement>) => {
    setIsLoadingFile(true);
    const file = event.target.files?.[0];
    if (file) {
      const reader = new FileReader();
      reader.onload = (e) => {
        try {
          const yamlContent = e.target?.result as string;
          const parsedYaml = yaml.parse(yamlContent) as FineTuneConfig;
          setFineTuneConfig((prevConfig) => ({
            ...prevConfig,
            ...parsedYaml,
            base_model: model?.modelId || parsedYaml.base_model,
          }));
          toast({
            title: "Success",
            description: "YAML file imported successfully",
            variant: "success",
          });
        } catch (error) {
          console.error("Error parsing YAML:", error);
          toast({
            title: "Error",
            description: "Failed to parse YAML file",
            variant: "destructive",
          });
        }
      };
      reader.readAsText(file);
    }
    // Reset the file input so the same file can be selected again
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
    setIsLoadingFile(false);
  };

  const triggerFileInput = () => {
    fileInputRef.current?.click();
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-8">
      <div className="flex justify-end mb-4">
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <div>
                <input
                  type="file"
                  ref={fileInputRef}
                  onChange={handleImportYaml}
                  accept=".yaml,.yml"
                  className="hidden"
                />
                <Button
                  type="button"
                  onClick={triggerFileInput}
                  icon={<UploadIcon className="w-4 h-4 mr-2" />}
                  loading={isLoadingFile}
                >
                  Import Config
                </Button>
              </div>
            </TooltipTrigger>
            <TooltipContent>
              <p>
                Import a YAML file to pre-fill the fine-tuning configuration.
              </p>
              <p>You can modify the values after importing.</p>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Fine-tune Config</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <Label htmlFor="project_name">Name of fine-tune job</Label>
            <Input
              id="project_name"
              value={fineTuneConfig.project_name}
              onChange={(e) =>
                setFineTuneConfig((prev) => ({
                  ...prev,
                  project_name: e.target.value,
                  task: e.target.value,
                }))
              }
              required
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Dataset</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <Label htmlFor="dataset-path">Dataset Path</Label>
            <Input
              id="dataset-path"
              value={fineTuneConfig.data.path}
              onChange={(e) => handleDatasetChange("path", e.target.value)}
              required
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Label htmlFor="train-split">Train Split</Label>
            <Input
              id="train-split"
              value={fineTuneConfig.data.train_split}
              onChange={(e) =>
                handleDatasetChange("train_split", e.target.value)
              }
              required
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Label htmlFor="valid-split">Valid Split</Label>
            <Input
              id="valid-split"
              value={fineTuneConfig.data.valid_split || ""}
              onChange={(e) =>
                handleDatasetChange("valid_split", e.target.value || null)
              }
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Label htmlFor="chat-template">Chat Template</Label>
            <Select
              value={fineTuneConfig.data.chat_template || "none"}
              onValueChange={(value) =>
                handleDatasetChange("chat_template", value)
              }
            >
              <SelectTrigger>
                <SelectValue
                  placeholder="Select chat template"
                  defaultValue="none"
                />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">None</SelectItem>
                <SelectItem value="tokenizer">tokenizer</SelectItem>
                <SelectItem value="chatml">chatml</SelectItem>
                <SelectItem value="zephyr">zephyr</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Label htmlFor="text-column">Text Column</Label>
            <Input
              id="text-column"
              value={fineTuneConfig.data.column_mapping.text_column || ""}
              onChange={(e) =>
                handleColumnMappingChange("text_column", e.target.value || null)
              }
              required
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Label htmlFor="prompt-text-column">Prompt Text Column</Label>
            <Input
              id="prompt-text-column"
              value={
                fineTuneConfig.data.column_mapping.prompt_text_column || ""
              }
              onChange={(e) =>
                handleColumnMappingChange(
                  "prompt_text_column",
                  e.target.value || null
                )
              }
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Label htmlFor="rejected-text-column">Rejected Text Column</Label>
            <Input
              id="rejected-text-column"
              value={
                fineTuneConfig.data.column_mapping.rejected_text_column || ""
              }
              onChange={(e) =>
                handleColumnMappingChange(
                  "rejected_text_column",
                  e.target.value || null
                )
              }
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Hyperparameters</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4 justify-start">
            <Label htmlFor="block_size">Block Size</Label>
            <Input
              id="block_size"
              type="number"
              value={fineTuneConfig.params.block_size}
              onChange={(e) =>
                handleParamChange("block_size", parseInt(e.target.value))
              }
              required
            />
          </div>
          <div className="grid grid-cols-2 gap-4 justify-start">
            <Label htmlFor="model_max_length">Model Max Length</Label>
            <Input
              id="model_max_length"
              type="number"
              value={fineTuneConfig.params.model_max_length}
              onChange={(e) =>
                handleParamChange("model_max_length", parseInt(e.target.value))
              }
              required
            />
          </div>
          <div className="grid grid-cols-2 gap-4 justify-start">
            <Label htmlFor="epochs">Epochs</Label>
            <Input
              id="epochs"
              type="number"
              value={fineTuneConfig.params.epochs}
              onChange={(e) =>
                handleParamChange("epochs", parseInt(e.target.value))
              }
              required
            />
          </div>
          <div className="grid grid-cols-2 gap-4 justify-start">
            <Label htmlFor="batch_size">Batch Size</Label>
            <Input
              id="batch_size"
              type="number"
              value={fineTuneConfig.params.batch_size}
              onChange={(e) =>
                handleParamChange("batch_size", parseInt(e.target.value))
              }
              required
            />
          </div>
          <div className="grid grid-cols-2 gap-4 justify-start">
            <Label htmlFor="lr">Learning Rate</Label>
            <Input
              id="lr"
              type="number"
              step="0.000001"
              value={fineTuneConfig.params.lr}
              onChange={(e) =>
                handleParamChange("lr", parseFloat(e.target.value))
              }
              required
            />
          </div>
          <div className="grid grid-cols-2 gap-4 justify-start">
            <Label htmlFor="quantization">Quantization</Label>
            <Select
              value={fineTuneConfig.params.quantization || "none"}
              onValueChange={(value) =>
                handleParamChange("quantization", value)
              }
            >
              <SelectTrigger>
                <SelectValue placeholder="Select quantization" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">None</SelectItem>
                <SelectItem value="int4">Int4</SelectItem>
                <SelectItem value="int8">Int8</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="grid grid-cols-2 gap-4 justify-start">
            <Label htmlFor="gradient_accumulation">Gradient Accumulation</Label>
            <Input
              id="gradient_accumulation"
              type="number"
              value={fineTuneConfig.params.gradient_accumulation}
              onChange={(e) =>
                handleParamChange(
                  "gradient_accumulation",
                  parseInt(e.target.value)
                )
              }
              required
            />
          </div>
          <div className="grid grid-cols-2 gap-4 justify-start">
            <Label htmlFor="lora_r">Lora R</Label>
            <Input
              id="lora_r"
              type="number"
              value={fineTuneConfig.params.lora_r}
              onChange={(e) =>
                handleParamChange("lora_r", parseInt(e.target.value))
              }
              required
            />
          </div>
          <div className="grid grid-cols-2 gap-4 justify-start">
            <Label htmlFor="lora_alpha">Lora Alpha</Label>
            <Input
              id="lora_alpha"
              type="number"
              value={fineTuneConfig.params.lora_alpha}
              onChange={(e) =>
                handleParamChange("lora_alpha", parseInt(e.target.value))
              }
              required
            />
          </div>
          <div className="grid grid-cols-2 gap-4 justify-start">
            <Label htmlFor="lora_dropout">Lora Dropout</Label>
            <Input
              id="lora_dropout"
              type="number"
              value={fineTuneConfig.params.lora_dropout}
              onChange={(e) =>
                handleParamChange("lora_dropout", parseFloat(e.target.value))
              }
              required
            />
          </div>
          <div className="grid grid-cols-2 gap-4 justify-start">
            <Label htmlFor="padding">Padding</Label>
            <Select
              value={fineTuneConfig.params.padding || "none"}
              onValueChange={(value) => handleParamChange("padding", value)}
            >
              <SelectTrigger>
                <SelectValue placeholder="Select padding" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">None</SelectItem>
                <SelectItem value="left">Left</SelectItem>
                <SelectItem value="right">Right</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {/* Add more hyperparameter inputs here */}
        </CardContent>
      </Card>

      <Button
        type="submit"
        icon={<RocketIcon className="w-4 h-4 mr-2" />}
        loading={isSubmitting}
      >
        {isSubmitting ? "Starting..." : "Start"}
      </Button>
    </form>
  );
}
