import logging
from io import BytesIO
from typing import Any

import openpyxl

logger = logging.getLogger(__name__)


class ExcelImportService:

    # 常见中文优先级到内部缺陷级别的映射。
    SEVERITY_MAP = {
        "致命": "critical", "严重": "major", "高": "major",
        "一般": "minor", "中": "minor",
        "轻微": "trivial", "低": "trivial",
        "critical": "critical", "major": "major", "minor": "minor", "trivial": "trivial",
        "紧急": "critical", "高优先级": "major",
    }

    @classmethod
    def _map_severity(cls, value: str) -> str:
        v = str(value).strip()
        return cls.SEVERITY_MAP.get(v, "minor")

    @classmethod
    def parse_defect_records(cls, file_content: bytes) -> list[dict[str, Any]]:
        """从缺陷 Excel 导入记录，识别标题、描述、优先级列并忽略多余列。"""
        wb = openpyxl.load_workbook(BytesIO(file_content), read_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []

        # 建立表头到列下标的映射。
        headers = [str(h).strip() if h else "" for h in rows[0]]
        col_map = {h: i for i, h in enumerate(headers)}

        # 必填列。
        title_col = col_map.get("标题")
        desc_col = col_map.get("描述")
        severity_col = col_map.get("优先级")

        if title_col is None and desc_col is None:
            raise ValueError("Excel 缺少必要列：标题 和 描述")

        result = []
        for row in rows[1:]:
            title = str(row[title_col]).strip() if title_col is not None and row[title_col] else ""
            desc = str(row[desc_col]).strip() if desc_col is not None and row[desc_col] else ""
            if not title and not desc:
                continue

            severity = "minor"
            if severity_col is not None and row[severity_col]:
                severity = cls._map_severity(str(row[severity_col]))

            result.append({"title": title, "description": desc, "severity": severity})

        wb.close()
        return result

    @classmethod
    def parse_field_dicts(cls, file_content: bytes) -> list[dict[str, Any]]:
        """从字段字典 Excel 导入记录：字段名、页面展示名、数据来源、类型、枚举值、业务含义。"""
        wb = openpyxl.load_workbook(BytesIO(file_content), read_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        headers = [str(h).strip() if h else "" for h in rows[0]]
        col_map = {h: i for i, h in enumerate(headers)}

        result = []
        for row in rows[1:]:
            fn = str(row[col_map.get("字段名", 0)]).strip() if row[col_map.get("字段名", 0)] else ""
            if not fn:
                continue
            result.append({
                "field_name": fn,
                "display_name": str(row[col_map.get("页面展示名", 1)]).strip() if len(row) > 1 and row[1] else "",
                "data_source": str(row[col_map.get("数据来源", 2)]).strip() if len(row) > 2 and row[2] else "",
                "data_type": str(row[col_map.get("类型", 3)]).strip() if len(row) > 3 and row[3] else "str",
                "enum_values": str(row[col_map.get("枚举值", 4)]).strip() if len(row) > 4 and row[4] else "",
                "description": str(row[col_map.get("业务含义", 5)]).strip() if len(row) > 5 and row[5] else "",
            })
        wb.close()
        return result

    @classmethod
    def parse_business_rules(cls, file_content: bytes) -> list[dict[str, Any]]:
        """从业务规则 Excel 导入记录：规则名称、类型、表达式、描述、来源。"""
        wb = openpyxl.load_workbook(BytesIO(file_content), read_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        headers = [str(h).strip() if h else "" for h in rows[0]]
        col_map = {h: i for i, h in enumerate(headers)}

        result = []
        for row in rows[1:]:
            rn = str(row[col_map.get("规则名称", 0)]).strip() if row[col_map.get("规则名称", 0)] else ""
            if not rn:
                continue
            result.append({
                "rule_name": rn,
                "rule_type": str(row[col_map.get("类型", 1)]).strip() if len(row) > 1 and row[1] else "hard",
                "expression": str(row[col_map.get("表达式", 2)]).strip() if len(row) > 2 and row[2] else "",
                "description": str(row[col_map.get("描述", 3)]).strip() if len(row) > 3 and row[3] else "",
                "source": str(row[col_map.get("来源", 4)]).strip() if len(row) > 4 and row[4] else "",
            })
        wb.close()
        return result

    @classmethod
    def generate_import_template(cls, template_type: str) -> BytesIO:
        """生成空的 Excel 导入模板。"""
        wb = openpyxl.Workbook()

        if template_type == "defects":
            ws = wb.active
            ws.title = "缺陷记录"
            ws.append(["标题", "描述", "优先级"])
            ws.append(["示例：设备数量显示错误", "直播页面显示的设备数实际为通道数", "严重"])

        elif template_type == "field-dicts":
            ws = wb.active
            ws.title = "字段字典"
            ws.append(["字段名", "页面展示名", "数据来源", "类型", "枚举值", "业务含义"])
            ws.append(["channel_count", "设备数", "camera表", "int", "", "摄像机通道数"])

        elif template_type == "business-rules":
            ws = wb.active
            ws.title = "业务规则"
            ws.append(["规则名称", "类型", "表达式", "描述", "来源"])
            ws.append(["VIP免运费", "hard", "user_level=vip -> freight=0", "VIP用户免运费", "PRD v3.2"])

        else:
            ws = wb.active
            ws.title = "通用模板"
            ws.append(["请指定模板类型: defects / field-dicts / business-rules"])

        output = BytesIO()
        wb.save(output)
        output.seek(0)
        wb.close()
        return output


class ExcelExportService:
    """导出测试用例到 Excel。"""

    @classmethod
    def export_test_cases(cls, cases: list[dict[str, Any]]) -> BytesIO:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "测试用例"
        ws.append(["用例标题", "等级", "前置条件", "步骤描述", "预期结果"])
        for c in cases:
            steps_str = c.get("steps", "")
            if isinstance(steps_str, list):
                steps_str = "\n".join(
                    f"{s.get('step_no', i+1)}. {s.get('action', str(s))}" if isinstance(s, dict) else str(s)
                    for i, s in enumerate(steps_str)
                )
            elif isinstance(steps_str, str):
                try:
                    import json
                    parsed = json.loads(steps_str)
                    if isinstance(parsed, list):
                        steps_str = "\n".join(f"{s.get('step_no', i+1)}. {s.get('action', str(s))}" if isinstance(s, dict) else str(s) for i, s in enumerate(parsed))
                except Exception:
                    logger.debug("步骤字段不是 JSON 数组，按原始字符串导出")

            ws.append([
                c.get("title", ""),
                c.get("priority", "P1"),
                c.get("precondition", ""),
                steps_str,
                c.get("expected_result", ""),
            ])

        output = BytesIO()
        wb.save(output)
        output.seek(0)
        wb.close()
        return output
