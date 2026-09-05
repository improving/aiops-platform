"""The dispatcher other registry code calls without naming a specific
source module directly (``api/registry.py``, Phase 3 Task 4):
``search()`` previews and ``fetch()`` reads back one entry, routed by
the platform's source tag ("huggingface", "ollama", "openrouter")."""

from registry import huggingface, ollama, openrouter
from registry.entry import RegistryEntry, SourceError

__all__ = ["SOURCES", "SourceError", "fetch", "search"]

SOURCES = ("huggingface", "ollama", "openrouter")


def _unknown_source(source: str) -> SourceError:
    return SourceError(400, f"Unknown source: {source}")


def search(source: str, query: str, limit: int = 20) -> list[RegistryEntry]:
    """Previews for the "Add..." dialogs.

    Ollama has no listing endpoint: the query is a full ``name:tag``
    reference and the answer is the one preview ``fetch()`` would
    return from its manifest.
    """
    if source == "huggingface":
        return huggingface.search(query, limit)
    if source == "ollama":
        return [ollama.fetch(query)]
    if source == "openrouter":
        results = openrouter.list_models()
        if query:
            needle = query.lower()
            results = [
                e
                for e in results
                if needle in e.source_id.lower() or needle in e.name.lower()
            ]
        return results[:limit]
    raise _unknown_source(source)


def fetch(source: str, source_id: str) -> RegistryEntry:
    if source == "huggingface":
        return huggingface.fetch(source_id)
    if source == "ollama":
        return ollama.fetch(source_id)
    if source == "openrouter":
        for entry in openrouter.list_models():
            if entry.source_id == source_id:
                return entry
        raise SourceError(404, f"Unknown OpenRouter model: {source_id}")
    raise _unknown_source(source)
