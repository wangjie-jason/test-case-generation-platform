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
    "title": "【层级路径-功能点】验证点（前缀是功能所在的层级路径，不能是测试技术名。层级深时可用「-」多级分割，如【PC端-工作台-统计概览】验证问候语显示当前网格员姓名和日期）",
    "priority": "P0|P1|P2",
    "precondition": "前置条件（可留空或写 -）",
    "steps": "测试步骤（可留空或写 -；需要时用数字编号：1.操作 2.操作）",
    "expected_result": "预期结果（对应步骤时用相同数字编号）",
    "knowledge_refs": [{{"type": "field_dict|business_rule|state_machine|term_mapping", "id": "ID", "name": "名称"}}]
  }}
]

格式要求：
- title 前缀【】里是【层级路径-功能点】，如【PC端走访任务-新建走访】。前缀是"这条用例在测什么功能"，绝不是"用了什么测试技术"
- 前缀不限于两级：当模块/路径较深时，可用「-」多级分割，从大到小逐级细化，如【PC端-工作台-统计概览】【App-走访任务-任务列表-筛选】。层级取到能唯一定位功能点即可，不要冗余堆砌
- **前缀最后一级必须是「功能点」，不能停在页面/区块名**。页面上有多个独立功能点时，逐个下钻到功能点那一级，别把它们挤在同一个页面前缀下靠描述区分：
  - ✅ 正例：【App-走访流程-提交页-现场照片】数量上限9张边界值 / 【App-走访流程-提交页-走访类型】未选时提交提示必填
  - ❌ 反例：【App-走访流程-提交页】验证现场照片添加与删除 / 【App-走访流程-提交页】验证走访类型单选（4类）
  - 判断标准：同一前缀下的用例应该都在测**同一个**输入项/按钮/展示项；如果它们测的是页面上不同的东西，说明前缀还差一级
- **禁止**把测试技术名当前缀，例如 ❌【空值-null】❌【边界值】❌【等价类】❌【异常】❌【安全】❌【SQL注入】都是错的
- 边界值/空值/异常/注入等场景，必须归到它所属的功能点前缀下，把测试意图写进验证点描述：
  - ✅ 正例：【PC端走访任务-新建走访】关联户为空时提交，提示关联户必填
  - ❌ 反例：【空值-null】验证关联户为空时提交任务
- 同一个功能点会有多条用例（正向/反向/各种边界），它们共用同一个【层级路径-功能点】前缀，靠后面的验证点描述区分
- priority 分 P0(核心功能)、P1(重要)、P2(边缘)
- 每条覆盖单一验证点，不要合并多个场景
- 历史缺陷的缺陷描述和根因必须覆盖

## 步骤粒度自适应（按用例复杂度分档，避免废话步骤）
根据用例类型选择合适粒度，**不要一律套用多步骤模板**：

**A 档 · 极简型**（查询/展示/静态校验类）
- precondition 可写 "-"，steps 写 "-"
- 直接把验证点写进 expected_result
- 示例：
  - title：【实时视频-设备列表】验证列表显示当前用户所属设备
  - precondition：-
  - steps：-
  - expected_result：列表显示当前用户所属设备，含设备名、状态、最后在线时间三列

**B 档 · 单操作型**（一步操作+验证）
- steps 一句话说清操作即可，**不要拆成"打开页面→点击按钮"两步**
- 示例：
  - title：【实时视频-设备列表】筛选在线设备
  - precondition：存在混合状态的设备数据
  - steps：点击"仅显示在线"筛选器
  - expected_result：列表只保留状态=在线的设备

**C 档 · 多步流程型**（表单提交/状态流转/复杂交互）
- 才使用 1./2./3. 分步骤，expected_result 用**相同编号**引用对应步骤
- 允许某步没有预期（纯操作步）；但预期编号必须落在步骤编号范围内
- 示例：
  - steps：1.进入设备列表页  2.点击"新增"按钮  3.填写名称"test-01"并提交
  - expected_result：1.页面加载正常并显示当前用户设备  3.新设备出现在列表首行且状态为"离线"

**通用禁止项**（三档都适用）
- 禁止把"登录系统/进入 XX 页面/打开菜单"作为独立步骤——铺垫合并到 precondition，或省略
- 禁止为凑数写"页面加载成功""按钮可点击"这类无验证意义的预期
- 目标：用**最少字数**说清验证意图

## Few-shot 示例（参考以下历史优质用例的格式和粒度）
{historical_cases}

## 质量自检（生成每条用例后自查）
- [ ] 该用例引用的字段是否都在字段字典中？
- [ ] 预期结果是否与业务规则一致（不违背）？
- [ ] 状态变更是否在状态机中有合法路径？
- [ ] 是否覆盖了历史缺陷中提到的风险点？
- [ ] 测试步骤是否具体可执行（含测试数据）？"""

    # 需求补全（澄清）阶段的系统提示：不写用例，只把简略需求结合知识库补成结构化完整需求。
    CLARIFY_SYSTEM = """你是一名资深业务分析师兼测试专家。你的任务不是编写测试用例，而是把用户提供的、可能比较简略的需求，结合知识库补全成一份【结构化的完整需求说明】，供后续设计测试用例使用。

## 可用知识库信息
### 字段字典
{field_dicts}

### 业务规则
{business_rules}

### 状态机
{state_machines}

### 术语映射
{term_mappings}

### 历史缺陷
{defects}

### 相关历史用例（仅供理解业务粒度）
{historical_cases}

## 补全要求
1. 保留用户原始需求的意图，不得改变或缩小其范围
2. 结合知识库补出需求中【隐含但重要】的逻辑：涉及的字段及取值约束、必须遵守的业务规则、相关状态流转、异常与边界场景、历史上出过问题的风险点
3. 只能依据上述知识库与常识补充，【严禁编造】知识库中不存在的字段、规则或状态
4. 对你补充的（原始需求未明确提及的）内容，在该条目末尾标注「（补充）」，方便用户识别与修改
5. 某类信息知识库中没有，就不写该部分，不要硬凑

## 输出格式（Markdown，禁止输出 JSON，禁止输出测试用例）
## 功能概述
（一段话说明这个需求做什么）

## 输入与字段约束
- 字段名（页面名）：类型 / 取值约束

## 业务规则
- 规则描述

## 状态流转
- 实体：源状态 → 目标状态（触发条件）

## 异常与边界场景
- 场景描述

## 需重点回归的风险点
- 来自历史缺陷的风险点"""

    @staticmethod
    def build_clarify(
        requirement_text: str,
        field_dicts: list[dict],
        business_rules: list[dict],
        state_machines: list[dict],
        term_mappings: list[dict],
        defect_chunks: list[dict] | None = None,
        prd_chunks: list[dict] | None = None,
        historical_cases: list[dict] | None = None,
    ) -> tuple[str, str]:
        """构造「需求补全」调用的 system/user。产出结构化完整需求，而非测试用例。"""
        fd_table = PromptService._format_field_dicts(field_dicts)
        br_table = PromptService._format_business_rules(business_rules)
        sm_table = PromptService._format_state_machines(state_machines)
        tm_table = PromptService._format_term_mappings(term_mappings)
        few_shot = PromptService._format_historical_cases(historical_cases or [])

        defect_text = "（无历史缺陷记录）"
        if defect_chunks:
            unique_texts = list(dict.fromkeys(d.get("text", "") for d in defect_chunks if d.get("text")))
            if unique_texts:
                defect_text = "\n".join(f"- {t[:300]}" for t in unique_texts[:5])

        prd_text = ""
        if prd_chunks:
            unique_texts = list(dict.fromkeys(d.get("text", "") for d in prd_chunks if d.get("text")))
            if unique_texts:
                prd_text = "\n## 相关PRD文档内容\n" + "\n---\n".join(t[:800] for t in unique_texts[:5])

        system_content = PromptService.CLARIFY_SYSTEM.format(
            field_dicts=fd_table, business_rules=br_table, state_machines=sm_table,
            term_mappings=tm_table, defects=defect_text, historical_cases=few_shot,
        )
        user_content = f"""## 原始需求（可能较简略，请结合知识库补全）
{requirement_text}
{prd_text}

请输出补全后的结构化需求说明（Markdown），不要输出测试用例。"""
        return system_content, user_content

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
        module_focus: str | None = None,
    ) -> tuple[str, str]:
        """返回供 LLM 调用的 system_content 和 user_content。

        module_focus 非空时进入「模块分批」模式：知识库/系统提示不变，只在生成指令里
        约束本批**只聚焦该模块**，不要输出其它模块的用例。用于把大需求拆成多批生成，
        每批规模更小，从源头降低单次撞满 max_tokens 的概率。
        """

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
        module_clause = ""
        if module_focus:
            module_clause = f"""
## 本批聚焦模块（重要）
本次**只生成属于【{module_focus}】这一模块/功能域的测试用例**，其它模块的用例本批一律不要输出。
所有用例的 title 前缀【层级路径-功能点】里最顶层的"模块"部分应与「{module_focus}」一致或从属于它；其下可继续用「-」细分出更深的子路径与功能点。
"""
        user_content = f"""## 需求内容
{requirement_text}

{prd_text}
{module_clause}
## 生成指令
请依据下面的知识库、需求和历史缺陷，按"覆盖率而非条数"的原则生成测试用例——
需求里涉及多少个字段、规则、状态、缺陷模式、边界组合，就生成多少条用例，**不要为了控制条数而合并场景或省略边界值**。
依次应用六种测试设计技术覆盖：

1. **等价类划分**：每个字段的有效/无效等价类**各至少 1 条**（不是"整个需求各 1 条"）
2. **边界值分析**：每个数值字段测试 min-1/min/min+1 和 max-1/max/max+1、0、负数、空值、超长——**每个边界一条**
3. **决策表**：如有复杂条件组合，覆盖每种组合——**每种组合一条**
4. **状态迁移**：合法路径 + 非法路径 + 并发冲突——**每条路径一条**
5. **错误推测**：SQL注入、XSS、emoji、全角字符、重复提交——**每类模式一条**
6. **组合测试**：多参数交互时覆盖两两组合（Pairwise）——**每对组合一条**

额外要求：
- 每个功能点正向+反向各至少 1 条
- 历史缺陷每条至少 1 条回归用例
- 术语映射歧义字段必须有映射验证用例
- **不要预设最终条数**：需求简单可能只需 10-20 条，需求复杂且知识库丰富时上百条也正常，不要为了"看起来适量"而人为压缩

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
    def build_module_split(requirement_text: str, prd_chunks: list[dict] | None = None) -> tuple[str, str]:
        """构造「模块拆分」提示词，让 LLM 从需求中提取【模块/功能域】清单。

        返回 (system_content, user_content)。输出是一个 JSON 对象：
        {
          "modules": ["模块A", "模块B", ...],
          "covers_all": true|false,
          "reason": "如果 covers_all=false，说明遗漏了哪些未覆盖的章节"
        }
        """
        prd_text = ""
        if prd_chunks:
            unique_texts = list(dict.fromkeys(d.get("text", "") for d in prd_chunks if d.get("text")))
            if unique_texts:
                prd_text = "\n## 相关PRD文档内容\n" + "\n---\n".join(t[:800] for t in unique_texts[:5])

        system_content = """你是一名测试需求分析师。请阅读下面的需求内容，提取出其中所有可独立测试的【模块/功能域】清单。

## 要求
1. 模块粒度适中：一个"模块"对应一个可以独立生成测试用例的功能域（如"用户登录"、"订单管理"、"报表导出"）。
2. 不要拆分过细（如"登录按钮"不应作为独立模块），也不要合并过粗（如"整个系统"不应作为唯一模块）。
3. 覆盖需求中**所有章节和功能领域**，不得遗漏。
4. output 严格为 JSON 对象（不要 markdown 代码块），含三个字段：
   - "modules": 有序的模块名列表（数组）
   - "covers_all": boolean，是否覆盖了需求的所有章节。不确定时优先 false。
   - "reason": 如果 covers_all=false，说明遗漏了哪些未覆盖的章节或原因"""

        user_content = f"""## 需求内容
{requirement_text}

{prd_text}

请输出模块清单 JSON。"""
        return system_content, user_content

    @staticmethod
    def build_continuation(existing_titles: list[str]) -> str:
        """构造「续写」提示词，让 LLM 接着已生成的用例继续输出。

        existing_titles: 已生成的用例标题列表，让模型避免重复。
        返回 user_content 字符串，与 PromptService.build() 输出的 system_content 配对使用。
        """
        titles_str = "\n".join(f"- {t}" for t in existing_titles) if existing_titles else "（无已有用例）"
        return f"""你继续生成上一轮输出被截断的测试用例。

## 规则
1. 不要重复下面已生成的用例标题
2. 直接续写 JSON 数组，保持与之前一致的格式（title/priority/precondition/steps/expected_result/knowledge_refs）
3. 不需要重新输出之前的用例，只需要输出**新增的**用例
4. 不要用 markdown 代码块包裹，直接输出纯 JSON 数组

## 当前已生成的用例标题（以下标题请勿重复）
{titles_str}"""

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
