"""Shared types for the registry importers (Hugging Face, Ollama,
OpenRouter): the entry a source's JSON parses into, and the error a
source raises on a rejected or unreachable request."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RegistryEntry:
    """One catalog entry from an importer, before it becomes a
    ``models`` row plus its serving options (``db/db.py``,
    ``api/registry.py``, Phase 3 Task 4)."""

    source: str
    source_id: str
    name: str
    description: str | None
    category: str | None
    subcategory: str | None
    size: int | None
    license: str | None
    parameters: int | None
    context_length: int | None
    capabilities: list[str]
    formats: list[str]
    tags: list[str]
    raw: dict
    # (engine, reference) pairs; empty for a gated Hugging Face repo.
    serving_options: list[tuple[str, str]] = field(default_factory=list)


class SourceError(Exception):
    """A source rejected the request (429, with a retry-after detail)
    or could not be reached (502)."""

    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(detail)
