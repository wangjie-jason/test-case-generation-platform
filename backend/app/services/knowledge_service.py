from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BusinessRule, DefectRecord, FieldDict, PrdDocument, StateMachine, TermMapping


class KnowledgeService:
    """按知识库隔离的各类知识 CRUD 服务。"""

    @staticmethod
    async def list_field_dicts(db: AsyncSession, kb_id: str) -> list[FieldDict]:
        r = await db.execute(select(FieldDict).where(FieldDict.kb_id == kb_id).order_by(FieldDict.field_name))
        return list(r.scalars().all())

    @staticmethod
    async def create_field_dict(db: AsyncSession, kb_id: str, data: dict) -> FieldDict:
        item = FieldDict(kb_id=kb_id, **data); db.add(item); await db.commit(); await db.refresh(item); return item

    @staticmethod
    async def get_field_dict(db: AsyncSession, item_id: str) -> FieldDict | None:
        return await db.get(FieldDict, item_id)

    @staticmethod
    async def update_field_dict(db: AsyncSession, item: FieldDict, data: dict) -> FieldDict:
        for k, v in data.items():
            if v is not None: setattr(item, k, v)
        await db.commit(); await db.refresh(item); return item

    @staticmethod
    async def delete_field_dict(db: AsyncSession, item: FieldDict):
        await db.delete(item); await db.commit()

    @staticmethod
    async def list_business_rules(db: AsyncSession, kb_id: str) -> list[BusinessRule]:
        r = await db.execute(select(BusinessRule).where(BusinessRule.kb_id == kb_id).order_by(BusinessRule.rule_name))
        return list(r.scalars().all())

    @staticmethod
    async def create_business_rule(db: AsyncSession, kb_id: str, data: dict) -> BusinessRule:
        item = BusinessRule(kb_id=kb_id, **data); db.add(item); await db.commit(); await db.refresh(item); return item

    @staticmethod
    async def get_business_rule(db: AsyncSession, item_id: str) -> BusinessRule | None:
        return await db.get(BusinessRule, item_id)

    @staticmethod
    async def update_business_rule(db: AsyncSession, item: BusinessRule, data: dict) -> BusinessRule:
        for k, v in data.items():
            if v is not None: setattr(item, k, v)
        await db.commit(); await db.refresh(item); return item

    @staticmethod
    async def delete_business_rule(db: AsyncSession, item: BusinessRule):
        await db.delete(item); await db.commit()

    @staticmethod
    async def list_state_machines(db: AsyncSession, kb_id: str) -> list[StateMachine]:
        r = await db.execute(select(StateMachine).where(StateMachine.kb_id == kb_id).order_by(StateMachine.entity))
        return list(r.scalars().all())

    @staticmethod
    async def create_state_machine(db: AsyncSession, kb_id: str, data: dict) -> StateMachine:
        item = StateMachine(kb_id=kb_id, **data); db.add(item); await db.commit(); await db.refresh(item); return item

    @staticmethod
    async def get_state_machine(db: AsyncSession, item_id: str) -> StateMachine | None:
        return await db.get(StateMachine, item_id)

    @staticmethod
    async def update_state_machine(db: AsyncSession, item: StateMachine, data: dict) -> StateMachine:
        for k, v in data.items():
            if v is not None: setattr(item, k, v)
        await db.commit(); await db.refresh(item); return item

    @staticmethod
    async def delete_state_machine(db: AsyncSession, item: StateMachine):
        await db.delete(item); await db.commit()

    @staticmethod
    async def list_term_mappings(db: AsyncSession, kb_id: str) -> list[TermMapping]:
        r = await db.execute(select(TermMapping).where(TermMapping.kb_id == kb_id).order_by(TermMapping.ui_term))
        return list(r.scalars().all())

    @staticmethod
    async def create_term_mapping(db: AsyncSession, kb_id: str, data: dict) -> TermMapping:
        item = TermMapping(kb_id=kb_id, **data); db.add(item); await db.commit(); await db.refresh(item); return item

    @staticmethod
    async def get_term_mapping(db: AsyncSession, item_id: str) -> TermMapping | None:
        return await db.get(TermMapping, item_id)

    @staticmethod
    async def update_term_mapping(db: AsyncSession, item: TermMapping, data: dict) -> TermMapping:
        for k, v in data.items():
            if v is not None: setattr(item, k, v)
        await db.commit(); await db.refresh(item); return item

    @staticmethod
    async def delete_term_mapping(db: AsyncSession, item: TermMapping):
        await db.delete(item); await db.commit()

    # ── PRD 文档 ──

    @staticmethod
    async def list_prd_documents(db: AsyncSession, kb_id: str) -> list[PrdDocument]:
        r = await db.execute(select(PrdDocument).where(PrdDocument.kb_id == kb_id).order_by(PrdDocument.created_at.desc()))
        return list(r.scalars().all())

    @staticmethod
    async def create_prd_document(db: AsyncSession, kb_id: str, filename: str, file_format: str, raw_text: str) -> PrdDocument:
        item = PrdDocument(kb_id=kb_id, filename=filename, file_format=file_format, raw_text=raw_text)
        db.add(item); await db.commit(); await db.refresh(item); return item

    @staticmethod
    async def get_prd_document(db: AsyncSession, item_id: str) -> PrdDocument | None:
        return await db.get(PrdDocument, item_id)

    @staticmethod
    async def delete_prd_document(db: AsyncSession, item: PrdDocument):
        await db.delete(item); await db.commit()

    # ── 缺陷记录 ──

    @staticmethod
    async def list_defect_records(db: AsyncSession, kb_id: str) -> list[DefectRecord]:
        r = await db.execute(select(DefectRecord).where(DefectRecord.kb_id == kb_id).order_by(DefectRecord.created_at.desc()))
        return list(r.scalars().all())

    @staticmethod
    async def create_defect_record(db: AsyncSession, kb_id: str, data: dict) -> DefectRecord:
        item = DefectRecord(kb_id=kb_id, **data); db.add(item); await db.commit(); await db.refresh(item); return item

    @staticmethod
    async def get_defect_record(db: AsyncSession, item_id: str) -> DefectRecord | None:
        return await db.get(DefectRecord, item_id)

    @staticmethod
    async def update_defect_record(db: AsyncSession, item: DefectRecord, data: dict) -> DefectRecord:
        for k, v in data.items():
            if v is not None: setattr(item, k, v)
        await db.commit(); await db.refresh(item); return item

    @staticmethod
    async def delete_defect_record(db: AsyncSession, item: DefectRecord):
        await db.delete(item); await db.commit()
