from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BusinessRule, FieldDict, StateMachine, TermMapping


class ValidationService:

    @staticmethod
    async def validate_cases(db: AsyncSession, cases: list[dict]) -> list[dict]:
        all_fields = (await db.execute(select(FieldDict))).scalars().all()
        all_rules = (await db.execute(select(BusinessRule))).scalars().all()
        field_names = {f.field_name for f in all_fields}; field_ids = {f.id for f in all_fields}
        rule_names = {r.rule_name for r in all_rules}; rule_ids = {r.id for r in all_rules}

        warnings = []
        for i, case in enumerate(cases):
            cw = []
            for ref in case.get("knowledge_refs", []):
                rid, rt = ref.get("id", ""), ref.get("type", "")
                if rt == "field_dict" and rid not in field_ids and rid not in field_names: cw.append(f"字段不存在: {rid}")
                if rt == "business_rule" and rid not in rule_ids and rid not in rule_names: cw.append(f"规则不存在: {rid}")
            if cw: warnings.append({"case_index": i, "title": case.get("title", ""), "warnings": cw})
        return warnings
