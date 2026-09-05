"""The manual registry entry: the old "Import Model" dialog
(``api/models.py`` ``POST /v1alpha1/models``) and the registry's own
``POST /v1alpha1/registry/manual`` both create a row this way, so an
entry created either route is exactly the same shape and always
published (there is no draft state for a hand-entered row)."""

from models.models import STATUS_PUBLISHED, DBModel
from models.serving_option import ServingOption
from utils import genid

CAPABILITY_BY_CATEGORY = {
    "llm": ["chat"],
    "embedding": ["embedding"],
    "reranker": ["rerank"],
    "prompt_guard": ["guard"],
}


def create_manual_model(
    db,
    *,
    name: str,
    model_id: str,
    category: str | None,
    subcategory: str | None = None,
    description: str | None = None,
    size: int | None = None,
    license: str | None = None,
    serving_options: list[tuple[str, str]] | None = None,
) -> DBModel:
    model = DBModel(
        id=genid.uuid4(),
        name=name,
        modelId=model_id,
        description=description,
        category=category,
        subcategory=subcategory,
        size=size,
        source="manual",
        source_id=None,
        license=license,
        capabilities=CAPABILITY_BY_CATEGORY.get(category, []),
        formats=[],
        tags=[],
        status=STATUS_PUBLISHED,
    )
    db.add(model)
    db.flush()
    for engine, reference in serving_options or []:
        db.add(
            ServingOption(
                model_id=model.id, engine=engine, reference=reference
            )
        )
    db.commit()
    db.refresh(model)
    return model
