// Small formatters shared by the instance and model pages.

/** "5.3", "24", "0.5": one decimal, without a trailing ".0". */
export function oneDecimal(value: number): string {
  return value.toFixed(1).replace(/\.0$/, "");
}

/** 7615616512 -> "7.6B", 494032768 -> "494M"; empty without a count. */
export function formatParameterCount(count?: number | null): string {
  if (!count) return "";
  if (count >= 1e9) return `${oneDecimal(count / 1e9)}B`;
  if (count >= 1e6) return `${Math.round(count / 1e6)}M`;
  return String(count);
}

/** Bytes as "5.2 GB" or "940 MB"; empty without a size. */
export function formatWeights(bytes?: number | null): string {
  if (!bytes) return "";
  const gb = bytes / 1024 ** 3;
  return gb >= 1
    ? `${oneDecimal(gb)} GB`
    : `${Math.round(bytes / 1024 ** 2)} MB`;
}

/**
 * The name Chat, Langflow and the API know an inference instance by:
 * its LiteLLM model name, else "inst-" plus the last eight hex characters
 * of the id (backend/utils/litellm.py instance_model_name).
 */
export function instanceTargetName(instance: {
  id: string;
  litellm_model_name?: string | null;
}): string {
  return (
    instance.litellm_model_name ??
    `inst-${instance.id.replace(/-/g, "").slice(-8)}`
  );
}
