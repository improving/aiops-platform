import { Toast } from "@/components/hooks/use-toast";
import { AxiosError } from "axios";
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

interface FastAPIValidationError {
  msg: string;
  loc?: (string | number)[];
}

type ApiErrorDetail =
  | string
  | FastAPIValidationError[]
  | Record<string, unknown>;

interface ErrorResponse {
  detail?: ApiErrorDetail;
}

function formatErrorDetail(
  detail: ApiErrorDetail | undefined
): string | undefined {
  if (detail === undefined || detail === null) {
    return undefined;
  }

  if (typeof detail === "string") {
    return detail;
  }

  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (item && typeof item === "object" && "msg" in item) {
          const loc = Array.isArray(item.loc)
            ? item.loc.filter((part) => part !== "body").join(".")
            : undefined;
          return loc ? `${loc}: ${item.msg}` : item.msg;
        }
        return typeof item === "string" ? item : JSON.stringify(item);
      })
      .join("; ");
  }

  try {
    return JSON.stringify(detail);
  } catch {
    return undefined;
  }
}

export function parseApiError(error: unknown): Toast {
  if (error instanceof AxiosError) {
    const status = error.response?.status;
    const data = error.response?.data as ErrorResponse | string | undefined;

    const detail =
      typeof data === "string" ? data : formatErrorDetail(data?.detail);
    const description = detail || error.message;

    return {
      title: "API Error",
      description: status ? `HTTP ${status}: ${description}` : description,
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
    switch (modelId.split("/")[0].toLowerCase()) {
      case "meta-llama":
        return "/models/meta-llama.png";
      case "microsoft":
        return "/models/microsoft.png";
      case "nvidia":
        return "/models/nvidia.png";
      case "mistralai":
        return "/models/mistral.png";
      case "qwen":
        return "/models/qwen.webp";
      default:
        return "/models/pixtide.png";
    }
  } catch {
    return "/models/pixtide.png";
  }
}

// Words that should render in all caps rather than Title Case, e.g. "llm" -> "LLM".
const ACRONYM_LABELS = new Set(["llm"]);

/**
 * Formats a raw enum-ish value (e.g. "llm", "prompt_guard", "text
 * generation") as a human-readable Title Case label ("LLM", "Prompt
 * Guard", "Text Generation") for display, while callers keep using the
 * raw value for filtering/comparison.
 */
export function formatEnumLabel(value: string): string {
  return value
    .split(/[\s_-]+/)
    .filter(Boolean)
    .map((word) =>
      ACRONYM_LABELS.has(word.toLowerCase())
        ? word.toUpperCase()
        : word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()
    )
    .join(" ");
}

/** A date-only display value, or "—" for a null timestamp. */
export function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleDateString() : "—";
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
  } catch {
    return "/models/pixtide.png";
  }
}
