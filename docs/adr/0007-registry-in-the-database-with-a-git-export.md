---
status: proposed
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

- An Alembic migration reshapes `models` and adds `model_serving_options` and `providers`; existing rows become `manual` entries.
- Importers depend on external APIs (Hugging Face Hub, OpenRouter); they run on demand and on a schedule, never at request time.
- The export is the source of truth for a fresh install; the database is the source of truth for a running one.
