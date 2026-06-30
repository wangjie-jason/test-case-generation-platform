class PromptService:
    """三层 Prompt 构造器，包含推理流程和质量约束。"""

    SYSTEM_TEMPLATE = """你是一名资深的功能测试用例设计专家，拥有10年以上的企业级系统测试经验。

## 分析流程
1. 提取需求中的功能点、输入参数（含数据类型和约束）、业务规则、集成点
2. 对照知识库确认字段、规则、状态、术语
3. 结合历史缺陷识别高风险场景

## 必须应用的测试设计技术

### 1. 等价类划分
将输入值分为有效等价类和无效等价类，每个等价类至少 1 条用例：
- 有效类：符合业务规则的正常输入
- 无效类：非法格式、越权访问、过期状态

### 2. 边界值分析
对每个数值/长度/日期范围字段，测试以下边界：
- 最小值-1、最小值、最小值+1
- 最大值-1、最大值、最大值+1
- 0、负数、空值/null、超长字符串

### 3. 决策表（如有复杂业务规则）
当存在多条互相关联的业务规则时，列出条件组合，确保每种组合对应预期结果

### 4. 状态迁移（如有状态机）
- 覆盖每个合法状态转换路径
- 覆盖非法状态转换（如 已发布→草稿）
- 考虑并发状态冲突（如两人同时审核同一条记录）

### 5. 错误推测法
根据常见缺陷模式补充用例：
- null/空字符串/纯空格输入
- SQL注入、XSS攻击字符：`'>"<script>alert(1)</script>`、`' OR 1=1--`
- 特殊字符：emoji 🔍、全角字符、超长文本
- 并发操作、重复提交

### 6. 组合测试
当多个参数相互影响时，覆盖关键参数的两两组合

## 知识库（强制约束 - 不得编造）
### 字段字典（生成用例时只能使用这些字段，不得虚构）
{field_dicts}

### 业务规则（预期结果必须符合以下规则，不得违反）
{business_rules}

### 状态机（前置条件和状态变更必须符合流转规则）
{state_machines}

### 术语映射（注意页面展示名和实际字段名的对应关系）
{term_mappings}

### 历史缺陷（以下场景必须覆盖对应的回归用例）
{defects}

## 用例设计原则
- 每个功能点至少 1 条正向 + 1 条反向用例
- 每个数值字段至少 1 条边界值用例
- 每条历史缺陷至少 1 条回归用例
- 不要遗漏：空值/null、特殊字符注入、并发冲突、权限越界
- 如术语映射表有歧义字段，必须设计字段映射验证用例

## 输出格式
严格输出 JSON 数组（不要 markdown 代码块）。参考以下格式：

[
  {{
    "title": "【模块-功能】验证点（必加【模块-功能点】前缀，如【实时视频-设备列表】验证设备数量显示正确）",
    "priority": "P0|P1|P2",
    "precondition": "前置条件",
    "steps": "测试步骤（用数字编号：1.操作 2.操作）",
    "expected_result": "预期结果（用数字编号对应步骤）",
    "knowledge_refs": [{{"type": "field_dict|business_rule|state_machine|term_mapping", "id": "ID", "name": "名称"}}]
  }}
]

格式要求：
- title 必加【模块-功能点】前缀，如【实时视频-设备列表】验证设备数量
- priority 分 P0(核心功能)、P1(重要)、P2(边缘)
- 每条覆盖单一验证点，不要合并多个场景
- 历史缺陷的缺陷描述和根因必须覆盖

## Few-shot 示例（参考以下历史优质用例的格式和粒度）
{historical_cases}

## 质量自检（生成每条用例后自查）
- [ ] 该用例引用的字段是否都在字段字典中？
- [ ] 预期结果是否与业务规则一致（不违背）？
- [ ] 状态变更是否在状态机中有合法路径？
- [ ] 是否覆盖了历史缺陷中提到的风险点？
- [ ] 测试步骤是否具体可执行（含测试数据）？"""

    @staticmethod
    def build(
        requirement_text: str,
        field_dicts: list[dict],
        business_rules: list[dict],
        state_machines: list[dict],
        term_mappings: list[dict],
        defect_chunks: list[dict] | None = None,
        prd_chunks: list[dict] | None = None,
        historical_cases: list[dict] | None = None,
    ) -> tuple[str, str]:
        """返回供 LLM 调用的 system_content 和 user_content。"""

        fd_table = PromptService._format_field_dicts(field_dicts)
        br_table = PromptService._format_business_rules(business_rules)
        sm_table = PromptService._format_state_machines(state_machines)
        tm_table = PromptService._format_term_mappings(term_mappings)

        # 将历史用例格式化为 few-shot 示例。
        few_shot = PromptService._format_historical_cases(historical_cases or [])

        # 格式化历史缺陷，突出回归预防要求。
        defect_text = "（无历史缺陷记录 — 按正常测试策略设计）"
        if defect_chunks:
            unique_texts = list(dict.fromkeys(d.get("text", "") for d in defect_chunks if d.get("text")))
            if unique_texts:
                items = [f"### 历史缺陷{i+1}\n{t[:400]}" for i, t in enumerate(unique_texts[:5])]
                defect_text = "\n\n".join(items)
                defect_text += "\n\n**重要：以上每个缺陷场景必须至少有1条回归用例覆盖！**"

        # 格式化 PRD 引用片段。
        prd_text = ""
        if prd_chunks:
            unique_texts = list(dict.fromkeys(d.get("text", "") for d in prd_chunks if d.get("text")))
            if unique_texts:
                prd_text = "\n## 相关PRD文档内容\n" + "\n---\n".join(t[:600] for t in unique_texts[:5])

        system_content = PromptService.SYSTEM_TEMPLATE.format(
            field_dicts=fd_table,
            business_rules=br_table,
            state_machines=sm_table,
            term_mappings=tm_table,
            defects=defect_text,
            historical_cases=few_shot,
        )

        # 用户需求和覆盖率提示。
        user_content = f"""## 需求内容
{requirement_text}

{prd_text}

## 生成指令
请生成充足的测试用例（至少 10-15 条），依次应用六种测试设计技术覆盖：

1. **等价类划分**：有效/无效等价类各至少 1 条
2. **边界值分析**：每个数值字段测试 min-1/min/min+1 和 max-1/max/max+1、0、负数、空值、超长
3. **决策表**：如有复杂条件组合，覆盖每种组合
4. **状态迁移**：合法路径 + 非法路径 + 并发冲突
5. **错误推测**：SQL注入、XSS、emoji、全角字符、重复提交
6. **组合测试**：多参数交互时覆盖两两组合

额外要求：
- 每个功能点正向+反向各至少 1 条
- 历史缺陷每条至少 1 条回归用例
- 术语映射歧义字段必须有映射验证用例

输出纯 JSON 数组（不要 markdown 代码块），最后用 JSON 格式附加覆盖率总结：
```json
{{
  "cases": [...],
  "coverage": {{
    "total": <数量>,
    "by_priority": {{"P0": <N>, "P1": <N>, "P2": <N>}},
    "by_type": {{"positive": <N>, "negative": <N>, "boundary": <N>, "exception": <N>, "security": <N>, "regression": <N>}},
    "gaps": ["未覆盖的场景1", "未覆盖的场景2"]
  }}
}}
```"""

        return system_content, user_content

    @staticmethod
    def _format_historical_cases(cases: list[dict]) -> str:
        if not cases:
            return "（无历史用例参考 — 按标准格式生成）"
        parts = []
        for i, c in enumerate(cases[:3]):
            steps_str = ""
            for s in c.get("steps", [])[:5]:
                steps_str += f"  {s.get('step_no','')}. {s.get('action','')} [{s.get('data','')}]\n"
            example = f"""### 示例{i+1}
- 标题：{c.get('title', '')}
- 前置条件：{c.get('precondition', '')}
- 步骤：
{steps_str}- 预期结果：{c.get('expected_result', '')}
- 场景：{c.get('scenario', '')}"""
            parts.append(example)
        return "\n\n".join(parts)

    @staticmethod
    def _format_field_dicts(items: list[dict]) -> str:
        if not items:
            return "（无字段字典数据 — 请先在知识库中配置，否则生成的用例可能出现字段幻觉）"
        rows = ["| 字段名 | 显示名 | 类型 | 枚举值 | 说明 |"]
        rows.append("|---|---|---|---|---|")
        for fd in items[:20]:
            enum = fd.get("enum_values", "") or "-"
            desc = (fd.get("description", "") or "-")[:80]
            rows.append(f"| {fd['field_name']} | {fd['display_name']} | {fd['data_type']} | {enum} | {desc} |")
        return "\n".join(rows)

    @staticmethod
    def _format_business_rules(items: list[dict]) -> str:
        if not items:
            return "（无业务规则 — 生成的预期结果可能不准确）"
        rows = ["| 规则名 | 类型 | 表达式 | 说明 |"]
        rows.append("|---|---|---|---|")
        for br in items[:15]:
            desc = (br.get("description", "") or "-")[:80]
            rows.append(f"| {br['rule_name']} | {br['rule_type']} | {br['expression']} | {desc} |")
        return "\n".join(rows)

    @staticmethod
    def _format_state_machines(items: list[dict]) -> str:
        if not items:
            return "（无状态机定义 — 状态相关的用例可能遗漏前置条件）"
        rows = ["| 实体 | 源状态 | 目标状态 | 条件 |"]
        rows.append("|---|---|---|---|")
        for sm in items[:15]:
            cond = sm.get("condition", "") or "-"
            rows.append(f"| {sm['entity']} | {sm['from_state']} | {sm['to_state']} | {cond} |")
        return "\n".join(rows)

    @staticmethod
    def _format_term_mappings(items: list[dict]) -> str:
        if not items:
            return "（无术语映射 — 页面命名可能产生歧义）"
        rows = ["| 页面术语 | 技术字段 | 映射说明 |"]
        rows.append("|---|---|---|")
        for tm in items[:15]:
            desc = (tm.get("mapping_desc", "") or "-")[:80]
            rows.append(f"| {tm['ui_term']} | {tm['tech_field']} | {desc} |")
        return "\n".join(rows)
