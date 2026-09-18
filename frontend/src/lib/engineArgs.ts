// What the launch form knows about the CLI arguments and environment
// variables of the engines this platform runs, for the info button next to a
// row (components/models/ArgHelp.tsx). Pure data: a row whose name is not
// here simply has no button. Engine names are the ones of
// backend/raw_data/engines.csv. Keep a `defaultValue` only where the engine
// documents one; "set by the platform" rows say where that happens.

export type ArgKind = "arg" | "env";

export interface ArgDoc {
  /** As typed into the form; lookup ignores a leading "--" and "_" vs "-". */
  name: string;
  kind: ArgKind;
  engines: string[];
  summary: string;
  /** The engine's own default, not the value the form is seeded with. */
  defaultValue?: string;
  range?: string;
  /** What to watch for on this platform. */
  note?: string;
  docUrl?: string;
}

const VLLM_ARGS =
  "https://docs.vllm.ai/en/latest/configuration/engine_args.html";
const VLLM_ENV = "https://docs.vllm.ai/en/latest/configuration/env_vars.html";
const HF_ENV =
  "https://huggingface.co/docs/huggingface_hub/package_reference/environment_variables";
const TGI_ARGS =
  "https://huggingface.co/docs/text-generation-inference/reference/launcher";
const OLLAMA_FAQ = "https://docs.ollama.com/faq";

export const ENGINE_ARG_DOCS: readonly ArgDoc[] = [
  // --- vLLM ----------------------------------------------------------------
  {
    name: "max_model_len",
    kind: "arg",
    engines: ["vLLM"],
    summary:
      "The longest request the server accepts, prompt plus answer, in tokens. The KV cache is sized for it, so a larger value needs more GPU memory.",
    defaultValue: "the model's own context length",
    range: "1 to the model's context length",
    note: "A model with a 32k or 128k context often does not fit a 24 GB GPU at its default; 4192 to 16384 is a safe range there. vLLM stops at start with a KV cache error when the value is too large.",
    docUrl: VLLM_ARGS,
  },
  {
    name: "port",
    kind: "arg",
    engines: ["vLLM"],
    summary: "The port the server listens on inside the pod.",
    defaultValue: "8000",
    note: "Leave it: the Service, the probes and the gateway route point at this port.",
    docUrl: VLLM_ARGS,
  },
  {
    name: "--gpu-memory-utilization",
    kind: "arg",
    engines: ["vLLM"],
    summary:
      "The fraction of each GPU's memory vLLM takes for weights, activations and the KV cache.",
    defaultValue: "0.9",
    range: "0.1 to 1.0",
    note: "vLLM reserves this much even for a small model, so a second GPU workload on the same GPU does not fit unless you lower it.",
    docUrl: VLLM_ARGS,
  },
  {
    name: "--tensor-parallel-size",
    kind: "arg",
    engines: ["vLLM"],
    summary: "How many GPUs one copy of the model is split across.",
    defaultValue: "1",
    note: "Set by the platform to the GPU count when that is more than 1; add it only to override. Slices of one time-sliced GPU do not work.",
    docUrl: VLLM_ARGS,
  },
  {
    name: "--max-num-seqs",
    kind: "arg",
    engines: ["vLLM"],
    summary:
      "The most requests vLLM works on at the same time. Lower it to cut memory use, raise it for more parallel users.",
    range: "integer, 1 or more",
    docUrl: VLLM_ARGS,
  },
  {
    name: "--quantization",
    kind: "arg",
    engines: ["vLLM"],
    summary: "The weight quantization method, for example awq, gptq or fp8.",
    defaultValue: "read from the model's config",
    note: "Not needed for an AWQ or GPTQ model: vLLM detects it and picks its fastest kernel. fp8 quantizes a full-precision model while loading and needs an Ada or newer GPU.",
    docUrl: VLLM_ARGS,
  },
  {
    name: "--dtype",
    kind: "arg",
    engines: ["vLLM"],
    summary: "The precision of weights and activations.",
    defaultValue: "auto (the model's own, usually bfloat16)",
    range: "auto, half, float16, bfloat16, float32",
    docUrl: VLLM_ARGS,
  },
  {
    name: "--enable-prefix-caching",
    kind: "arg",
    engines: ["vLLM"],
    summary:
      "Reuse the KV cache of a shared prompt prefix (a long system prompt, a chat history) between requests.",
    note: "A flag: leave the value empty.",
    docUrl: VLLM_ARGS,
  },
  {
    name: "--trust-remote-code",
    kind: "arg",
    engines: ["vLLM"],
    summary:
      "Allow the model repository's own Python code to run. Some models need it.",
    note: "A flag: leave the value empty. Only for repositories you trust: the code runs in the pod.",
    docUrl: VLLM_ARGS,
  },
  {
    name: "--served-model-name",
    kind: "arg",
    engines: ["vLLM"],
    summary:
      "The model name clients send in the API instead of the repository id.",
    note: "The platform registers the instance in LiteLLM under its own name (inst-...), so chat and Langflow do not need this.",
    docUrl: VLLM_ARGS,
  },
  {
    name: "HF_HUB_OFFLINE",
    kind: "env",
    engines: ["vLLM", "HuggingFace"],
    summary:
      "1 forbids every download: the model must already be in the cache. 0 lets the engine download it on the first start.",
    defaultValue: "0",
    range: "0 or 1",
    note: "Use 0 for a model that was never started on this cluster. With 1 and an empty cache the pod fails at start.",
    docUrl: HF_ENV,
  },
  {
    name: "HF_HUB_CACHE",
    kind: "env",
    engines: ["vLLM"],
    summary: "Where downloaded models are kept inside the pod.",
    note: "Leave it at /model: that is where the platform mounts the shared model cache volume, so a second start needs no download.",
    docUrl: HF_ENV,
  },
  {
    name: "HF_HOME",
    kind: "env",
    engines: ["HuggingFace"],
    summary: "The Hugging Face home directory, which holds the model cache.",
    docUrl: HF_ENV,
  },
  {
    name: "VLLM_LOGGING_LEVEL",
    kind: "env",
    engines: ["vLLM"],
    summary: "How much vLLM writes to the log (Logs tab).",
    defaultValue: "INFO",
    range: "DEBUG, INFO, WARNING, ERROR",
    docUrl: VLLM_ENV,
  },
  {
    name: "VLLM_CACHE_ROOT",
    kind: "env",
    engines: ["vLLM"],
    summary: "Where vLLM keeps its compile cache.",
    note: "Set by the platform to the model volume, so a second start skips the compilation.",
    docUrl: VLLM_ENV,
  },
  // --- Hugging Face TGI: configured by environment variables ---------------
  {
    name: "MAX_INPUT_TOKENS",
    kind: "env",
    engines: ["HuggingFace"],
    summary: "The longest prompt the server accepts, in tokens.",
    range: "less than MAX_TOTAL_TOKENS",
    docUrl: TGI_ARGS,
  },
  {
    name: "MAX_TOTAL_TOKENS",
    kind: "env",
    engines: ["HuggingFace"],
    summary:
      "The most tokens of one request, prompt plus answer. It sets the memory each request can take.",
    range: "more than MAX_INPUT_TOKENS",
    docUrl: TGI_ARGS,
  },
  {
    name: "MAX_BATCH_PREFILL_TOKENS",
    kind: "env",
    engines: ["HuggingFace"],
    summary:
      "The most prompt tokens processed in one step; the main knob for prefill memory.",
    docUrl: TGI_ARGS,
  },
  {
    name: "NUM_SHARD",
    kind: "env",
    engines: ["HuggingFace"],
    summary: "How many GPUs the model is split across.",
    note: "Set by the platform to the GPU count when that is more than 1.",
    docUrl: TGI_ARGS,
  },
  {
    name: "QUANTIZE",
    kind: "env",
    engines: ["HuggingFace"],
    summary:
      "The quantization method, for example awq, gptq, bitsandbytes or fp8.",
    note: "TGI does not detect it: set it for a quantized repository.",
    docUrl: TGI_ARGS,
  },
  // --- Ollama ---------------------------------------------------------------
  {
    name: "OLLAMA_NUM_PARALLEL",
    kind: "env",
    engines: ["Ollama"],
    summary: "How many requests one loaded model answers at the same time.",
    docUrl: OLLAMA_FAQ,
  },
  {
    name: "OLLAMA_KEEP_ALIVE",
    kind: "env",
    engines: ["Ollama"],
    summary:
      "How long a model stays in memory after its last request, for example 5m or 24h; -1 keeps it for ever.",
    defaultValue: "5m",
    docUrl: OLLAMA_FAQ,
  },
  {
    name: "OLLAMA_CONTEXT_LENGTH",
    kind: "env",
    engines: ["Ollama"],
    summary: "The context window in tokens for every model the server loads.",
    docUrl: OLLAMA_FAQ,
  },
  {
    name: "OLLAMA_MAX_LOADED_MODELS",
    kind: "env",
    engines: ["Ollama"],
    summary: "How many models may be in memory at the same time.",
    docUrl: OLLAMA_FAQ,
  },
];

function normalize(name: string): string {
  return name.trim().replace(/^--/, "").replace(/_/g, "-").toLowerCase();
}

/** The entry for a row, or undefined: the form then shows no info button. */
export function lookupArgDoc(
  engineName: string | undefined,
  kind: ArgKind,
  name: string
): ArgDoc | undefined {
  if (!engineName || !name.trim()) return undefined;
  const wanted = normalize(name);
  return ENGINE_ARG_DOCS.find(
    (doc) =>
      doc.kind === kind &&
      doc.engines.includes(engineName) &&
      normalize(doc.name) === wanted
  );
}
