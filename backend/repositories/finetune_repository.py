from uuid import UUID

from sqlalchemy.orm import Session

from logger import setup_logger
from models.finetune import DBFinetune
from schemas.finetune import FinetuneCreateSchema, FinetuneUpdateSchema

logger = setup_logger(__name__)


class FinetuneRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_all(self) -> list[DBFinetune]:
        return self.db.query(DBFinetune).all()

    def get_by_model_id(self, model_id: UUID, scope=None) -> list[DBFinetune]:
        """The jobs of a model; ``scope`` is an extra SQL filter."""
        query = self.db.query(DBFinetune).filter(
            DBFinetune.model_id == model_id
        )
        if scope is not None:
            query = query.filter(scope)
        return query.all()

    def get_by_id(
        self, model_id: UUID, finetune_id: UUID
    ) -> DBFinetune | None:
        return (
            self.db.query(DBFinetune)
            .filter(
                DBFinetune.id == finetune_id, DBFinetune.model_id == model_id
            )
            .first()
        )

    def create(
        self,
        model_id: UUID,
        finetune: FinetuneCreateSchema,
        org_id: UUID | None = None,
        owner_id: UUID | None = None,
    ) -> DBFinetune:
        logger.info(f"Creating finetune job for model {model_id}")
        db_finetune = DBFinetune(
            **finetune.model_dump(),
            model_id=model_id,
            org_id=org_id,
            owner_id=owner_id,
        )
        self.db.add(db_finetune)
        self.db.commit()
        self.db.refresh(db_finetune)
        return db_finetune

    def update(
        self, model_id: UUID, finetune_id: UUID, finetune: FinetuneUpdateSchema
    ) -> DBFinetune | None:
        db_finetune = self.get_by_id(model_id, finetune_id)
        if db_finetune:
            update_data = finetune.model_dump(exclude_unset=True)
            for key, value in update_data.items():
                setattr(db_finetune, key, value)
            self.db.commit()
            self.db.refresh(db_finetune)
        return db_finetune

    def delete(self, model_id: UUID, finetune_id: UUID) -> bool:
        db_finetune = self.get_by_id(model_id, finetune_id)
        if db_finetune:
            self.db.delete(db_finetune)
            self.db.commit()
            return True
        return False
