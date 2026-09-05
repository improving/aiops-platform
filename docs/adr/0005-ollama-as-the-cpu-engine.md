---
status: accepted
date: 2026-09-05
---

# Ollama is the engine for small models on CPU

The platform's engines all need a GPU, so nothing runs on the kind stack or on a laptop.
We add Ollama as an engine: one instance serves several small models pulled by name,
exposes an OpenAI-compatible chat API, and has a management API (`/api/pull`, `/api/tags`) the registry can drive.
It is installed with the platform's own `charts/ollama` and joins the gateway like every other instance.

## Considered options

- llama.cpp server: smaller image and direct GGUF pulls from Hugging Face, but one model per pod and no management API or chart.
- LocalAI: broad backend support and a gallery, but heavier and its arm64 story is unverified.
- vLLM CPU and TGI CPU: not realistic on four CPUs; vLLM reserves gigabytes of KV cache by default and TGI is in maintenance mode.

## Consequences

- Engines gain a `cpu` flag; the launch wizard's accelerator step is optional for such engines.
- Ollama images are large (about 2.6 GiB on arm64) and each model adds its quantized size on first pull; the kind stack keeps one Ollama instance with two or three small models.
- GPU engines are unchanged; on the lab, Ollama is optional.
