---
status: accepted
date: 2026-09-05
---

# The model registry lives in the database, is edited in the UI, and is exported to git

The catalog is a CSV seeded at start with no source, license or capability metadata, and adding a model means editing a file.
Registry entries now live in the database with a source (`manual`, `huggingface`, `ollama`, `openrouter`), the source id,
license, parameter count, context length, capabilities, formats and a raw snapshot; admins edit, import and publish them in the UI;
`make registry-export` writes `backend/raw_data/models.yaml`, which seeds an empty database and makes changes reviewable in pull requests.
Serving options link an entry to the engines or hosted providers that can run it.

## Considered options

- Git-only YAML: reviewable, but no importers and no admin workflow in the product.
- Keep the CSV and add import buttons: no metadata model, so serving options and providers have nowhere to attach.

## Consequences

- An Alembic migration (`0007`) reshapes `models` and adds `model_serving_options`; existing rows become `manual` entries.
  The `providers` table came earlier with Phase 2b (migration `0006`).
- Importers depend on external APIs (Hugging Face Hub, OpenRouter); they run on demand and on a schedule, never at request time.
- The export is the source of truth for a fresh install; the database is the source of truth for a running one.

## Consequences observed (2026-09-05, Phase 3)

- The YAML seed sorts entries by source, source id and name, so a fresh `TEST_MODE` database assigns different deterministic ids than the old CSV did; snapshot files changed once.
- Serving options carry the engine reference (an Ollama tag, a Hugging Face repo, `hf.co/<repo>:<quant>` for GGUF repos on Ollama, a hosted provider model);
  the instance persists the chosen `reference`, and every controller and the LiteLLM registration read `instance.reference or model.modelId`.
- The importers verify TLS with certifi, because the dev backend's `SSL_CERT_FILE` points at the local CA.
- The Phase 1 rule that guessed engines from the model id (`frontend/src/lib/engines.ts`) is gone; the wizard renders serving options.

