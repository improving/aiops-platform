// The numbers behind the launch form's hints: what is free on the selected
// host, and whether the model's weights fit its GPU. Estimates for a person,
// never a gate: the form shows them and still lets the launch go ahead.

import type { Host, Model } from "@/types/models";

const MIB = 1024 * 1024;
const GIB = 1024 * MIB;
const DECIMAL: Record<string, number> = {
  K: 1e3,
  M: 1e6,
  G: 1e9,
  T: 1e12,
  P: 1e15,
  E: 1e18,
};
const BINARY: Record<string, number> = {
  Ki: 1024,
  Mi: MIB,
  Gi: GIB,
  Ti: 1024 * GIB,
  Pi: 1024 * 1024 * GIB,
  Ei: 1024 * 1024 * 1024 * GIB,
};

/** A Kubernetes quantity as a plain number ("500m" -> 0.5, "16Gi" -> bytes); null when it is not one. */
export function parseQuantity(text: string): number | null {
  const match = /^([0-9]+(?:\.[0-9]+)?)(m|[EPTGMK]i?)?$/.exec(text.trim());
  if (!match) return null;
  const value = Number(match[1]);
  const suffix = match[2];
  if (!suffix) return value;
  if (suffix === "m") return value / 1000;
  return value * (BINARY[suffix] ?? DECIMAL[suffix]);
}

export interface FreeResource {
  free: number;
  total: number;
  /** What the form asks for, in the same unit; null when empty or unreadable. */
  wanted: number | null;
  over: boolean;
}

function freeOf(
  total: number,
  used: number,
  wanted: number | null
): FreeResource {
  const free = Math.max(0, total - used);
  return { free, total, wanted, over: wanted !== null && wanted > free };
}

/** Free CPU in cores; null when the host does not report its size. */
export function freeCpu(
  host: Host,
  cpuText: string,
  replicas: number
): FreeResource | null {
  if (!host.allocatable_cpu) return null;
  const one = cpuText.trim() ? parseQuantity(cpuText) : null;
  return freeOf(
    host.allocatable_cpu,
    host.requested_cpu ?? 0,
    one === null ? null : one * replicas
  );
}

/** Free memory in GiB; null when the host does not report its size. */
export function freeMemory(
  host: Host,
  memoryText: string,
  replicas: number
): FreeResource | null {
  if (!host.allocatable_memory) return null;
  const bytes = memoryText.trim() ? parseQuantity(memoryText) : null;
  return freeOf(
    host.allocatable_memory / 1024,
    (host.requested_memory ?? 0) / 1024,
    bytes === null ? null : (bytes / GIB) * replicas
  );
}

/** Free GPUs (or time slices); null on a host without GPUs. */
export function freeGpu(
  host: Host,
  gpuCount: number,
  replicas: number
): FreeResource | null {
  const total =
    host.allocatable_gpu || host.gpu_count * Math.max(1, host.gpu_replicas);
  if (!total) return null;
  return freeOf(total, host.gpu_usage ?? 0, gpuCount * replicas);
}

// vLLM takes this fraction of a GPU by default (--gpu-memory-utilization),
// and about this much of it goes to the CUDA context and activations before
// the KV cache. Measured on an RTX 4090 with a 7B AWQ model: 5.3 GiB of
// weights left 15.0 GiB for the KV cache out of 0.9 x 24 GiB.
const GPU_UTILIZATION = 0.9;
const RUNTIME_OVERHEAD_GIB = 1.3;
// Below this much KV cache a 7B class model serves only a short context or
// a few parallel requests.
const TIGHT_CACHE_GIB = 2;

export interface GpuFit {
  weightsGiB: number;
  /** Memory of the GPUs the model is split across, in GiB. */
  gpuGiB: number;
  /** What stays for the KV cache; negative when the weights do not fit. */
  cacheGiB: number;
  fits: boolean;
  /** Fits, but with little room for context and parallel requests. */
  tight: boolean;
  /** Several GPUs asked for on a time-sliced GPU: slices add no memory. */
  sliced: boolean;
}

/**
 * Whether the model's weights fit the GPU memory of `host`, from the
 * registry's `size` (the bytes of the weight files). Null when the model has
 * no size or the host no GPU. It does not model the KV cache a long context
 * needs: a model that "fits" can still run out of memory at a large
 * max_model_len.
 */
export function estimateGpuFit(
  model: Pick<Model, "size"> | null,
  host: Host | undefined,
  gpuCount: number
): GpuFit | null {
  if (!model?.size || !host?.gpu_memory) return null;
  const sliced = host.gpu_replicas > 1;
  const gpus = sliced
    ? 1
    : Math.max(1, Math.min(gpuCount, host.gpu_count || 1));
  const gpuGiB = (host.gpu_memory / 1024) * gpus;
  const weightsGiB = model.size / GIB;
  const cacheGiB =
    gpuGiB * GPU_UTILIZATION - weightsGiB - RUNTIME_OVERHEAD_GIB * gpus;
  return {
    weightsGiB,
    gpuGiB,
    cacheGiB,
    fits: cacheGiB > 0,
    tight: cacheGiB > 0 && cacheGiB < TIGHT_CACHE_GIB,
    sliced: sliced && gpuCount > 1,
  };
}

export { oneDecimal } from "@/lib/format";

/** The engine's default for `max_model_len`, lowered to the model's own
 * context length when the registry knows it and it is shorter. Every
 * other argument, and an unknown context, keep the default. */
export function capToContext(
  name: string,
  defaultValue: string,
  contextLength: number | null | undefined
): string {
  if (name !== "max_model_len" || !contextLength) return defaultValue;
  const value = Number(defaultValue);
  if (!Number.isFinite(value) || value <= contextLength) return defaultValue;
  return String(contextLength);
}
