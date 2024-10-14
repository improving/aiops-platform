import { Toast } from "@/components/hooks/use-toast";
import { AxiosError } from "axios";
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

interface ErrorResponse {
  detail?: { msg: string }[];
}

export function parseApiError(error: unknown): Toast {
  if (error instanceof AxiosError) {
    const status = error.response?.status;
    const statusText = error.response?.statusText;
    const data = error.response?.data as ErrorResponse;

    let description: string;

    if (data?.detail && Array.isArray(data.detail)) {
      description = data.detail.map((d) => d.msg).join(", ");
    } else if (typeof data === "string") {
      description = data;
    } else {
      description = error.message;
    }

    return {
      title: "API Error",
      description: `HTTP ${status} - ${statusText}: ${description}`,
      variant: "destructive",
    };
  } else if (error instanceof Error) {
    return {
      title: "Error",
      description: error.message,
      variant: "destructive",
    };
  } else {
    return {
      title: "Unexpected Error",
      description: "An unexpected error occurred. Please try again.",
      variant: "destructive",
    };
  }
}

export function GetModelIcon(modelId: string) {
  try {
    switch (modelId.split("/")[0]) {
      case "meta-llama":
        return "/models/meta-llama.png";
      case "microsoft":
        return "/models/microsoft.png";
      case "nvidia":
        return "/models/nvidia.png";
      case "mistralai":
        return "/models/mistral.png";
      default:
        return "/models/pixtide.png";
    }
  } catch (error) {
    return "/models/pixtide.png";
  }
}

export function GetVectorDBIcon(vectorDBId: string) {
  try {
    switch (vectorDBId) {
      case "chromadb":
        return "/vectordbs/chroma.png";
      case "milvus":
        return "/vectordbs/milvus.png";
      case "qdrant":
        return "/vectordbs/qdrant.png";
      default:
        return "/models/pixtide.png";
    }
  } catch (error) {
    return "/models/pixtide.png";
  }
}
