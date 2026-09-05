import type { Engine, Model } from "@/types/models";

/**
 * Ollama model references are registry tags (`qwen3:0.6b`); Hugging Face
 * ids are `owner/repo`.
 * Phase 3: the registry's serving options replace this rule.
 */
export function isOllamaTag(modelId: string): boolean {
  return modelId.includes(":") && !modelId.includes("/");
}

export function supportsCategory(engine: Engine, category: string): boolean {
  switch (category) {
    case "llm":
      return engine.llm_support;
    case "embedding":
      return engine.embedding_support;
    case "reranker":
      return engine.reranking_support;
    case "prompt_guard":
      return engine.prompt_guard_support;
    case "vector_db":
      return engine.vector_db_support;
    default:
      return false;
  }
}

/** The engines a catalog entry can be launched on. */
export function enginesForModel(model: Model, engines: Engine[]): Engine[] {
  const ollama = isOllamaTag(model.modelId);
  return engines.filter(
    (engine) =>
      supportsCategory(engine, model.category) &&
      (engine.name.toLowerCase() === "ollama") === ollama
  );
}

/** True when every candidate engine runs without a GPU. */
export function cpuOnly(engines: Engine[]): boolean {
  return engines.length > 0 && engines.every((engine) => engine.cpu);
}
