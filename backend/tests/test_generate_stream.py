"""generate_stream 全流程的事件序列回归测试（app/services/generator_service.py）。

这条流水线有 5 个阶段、3 处并发 agent，吐出的事件名与字段是前端唯一的契约
（stores/generation.ts 按 type 分派、按 index 归档到各 agent 卡片）。此前零测试覆盖，
任何重构都只能靠人眼比对——本文件把「跑一遍完整流水线会吐哪些事件、什么顺序」钉死，
让阶段拆分这类纯结构调整变得可验证。

做法：只替换外部依赖（LLM / 知识库检索 / 校验），PromptService、分组、去重、归位排序
全部跑真实实现。FakeLLM 按 prompt 内容分派到「模块拆分 / 生成 / 评审 / 补充」四种响应。

确定性：把 LLM_MODULE_STAGGER_DELAY 归零，且 FakeLLM 的 async generator 内不含真正会挂起
的 await（无界 Queue 的 put/get 与未满的 Semaphore 都不让出事件循环），于是每个 worker
被调度后一口气跑完，事件严格按下标顺序进队列。

需要 chromadb：generator_service 顶部 import ChromaStore（原因见 test_llm_parsing 文件头），
只装 pytest 的环境下本文件整体跳过。
"""
import asyncio
import json
import re

import pytest

pytest.importorskip("chromadb", reason="generator_service 顶部 import ChromaStore")
pytest.importorskip("sqlalchemy", reason="generator_service 依赖 AsyncSession 类型标注")

from app.services import generator_service as gs  # noqa: E402

RETRIEVAL = {
    "query_keywords": ["登录"],
    "field_dicts": [{"id": "f1", "field_name": "username", "display_name": "用户名",
                     "data_type": "string", "description": "登录账号"}],
    "business_rules": [{"id": "r1", "rule_name": "连续失败锁定", "rule_type": "constraint",
                        "expression": "fail_count >= 5", "description": "连续5次失败锁定账号"}],
    "state_machines": [{"id": "s1", "entity": "订单", "from_state": "待支付",
                        "to_state": "已支付", "condition": "支付成功"}],
    "term_mappings": [{"id": "t1", "ui_term": "下单", "tech_field": "create_order",
                       "mapping_desc": "创建订单"}],
    "prd_chunks": [{"id": "p1", "filename": "prd.pdf", "text": "PRD 片段", "distance": 0.2}],
    "defect_chunks": [{"id": "d1", "title": "历史缺陷", "text": "缺陷片段", "distance": 0.3}],
}


def _cases_json(module: str, n: int) -> str:
    return json.dumps([
        {"title": f"【{module}-功能{i}】用例{i}", "priority": "P1", "precondition": "已登录",
         "steps": [f"步骤{i}"], "expected_result": f"结果{i}"}
        for i in range(1, n + 1)
    ], ensure_ascii=False)


def _classify(system_content: str, user_content: str) -> str:
    """按 prompt 里的特征串判断这次调用属于哪个阶段（各 prompt 由 PromptService 真实构造）。"""
    if "测试需求分析师" in system_content:
        return "module_split"
    if "你现在是测试评审专家" in user_content:
        return "review"
    if "请勿重复它们" in user_content:
        return "supplement"
    return "generate"


class FakeLLM:
    """按阶段分派响应的假 LLM。last_finish_reason 恒为 stop，不触发续写兜底。"""

    handler = None  # 由各测试设置：(kind, user_content) -> str

    def __init__(self):
        self.last_finish_reason = "stop"

    async def generate(self, system_content, user_content):
        return "".join([p async for p in self.generate_stream(system_content, user_content)])

    async def generate_stream(self, system_content, user_content, on_reasoning=None):
        kind = _classify(system_content, user_content)
        if on_reasoning is not None:
            await on_reasoning(f"思考[{kind}]")
        yield FakeLLM.handler(kind, user_content)


async def _async(value):
    return value


def _install(monkeypatch, handler, *, warnings=None, split=True):
    """把外部依赖换成假实现，并让并发不错峰、小需求也走模块拆分。"""
    monkeypatch.setattr(FakeLLM, "handler", staticmethod(handler))
    monkeypatch.setattr(gs, "LLMService", FakeLLM)
    monkeypatch.setattr(gs.RetrievalService, "retrieve",
                        lambda db, text, kb_ids=None: _async(dict(RETRIEVAL)))
    monkeypatch.setattr(gs, "_get_historical_cases",
                        lambda text, keywords, kb_ids=None: _async([]))
    monkeypatch.setattr(gs.ValidationService, "validate_cases",
                        lambda db, cases: _async(list(warnings or [])))
    monkeypatch.setattr(gs.settings, "LLM_MODULE_STAGGER_DELAY", 0.0)
    monkeypatch.setattr(gs.settings, "LLM_ENABLE_MODULE_SPLIT", split)
    monkeypatch.setattr(gs.settings, "LLM_MODULE_SPLIT_MIN_CHARS", 10)


def _collect(requirement_text: str = "需求：登录与订单管理，需覆盖两个模块。") -> list[dict]:
    async def run():
        return [ev async for ev in gs.GeneratorService.generate_stream(None, requirement_text)]
    return asyncio.run(run())


def _shape(events: list[dict]) -> list[tuple]:
    """事件序列的结构投影：(type, index)；progress 用 stage 代替 index 以便看清阶段。"""
    return [(ev["type"], ev.get("stage") if ev["type"] == "progress" else ev.get("index"))
            for ev in events]


# ── 模块拆分路径：生成 / 评审 / 补充三处并发 agent 全部走到 ──

def _full_handler(kind: str, user: str) -> str:
    if kind == "module_split":
        return json.dumps({"modules": ["登录", "订单"], "covers_all": True}, ensure_ascii=False)
    if kind == "generate":
        m = re.search(r"只生成属于【(.+?)】", user)
        return _cases_json(m.group(1) if m else "单批", 3)
    if kind == "review":
        # 每组删掉第一条，并各报一个遗漏场景。
        return json.dumps({"reviews": [{"index": 0, "verdict": "delete", "reason": "与其它用例重复"}],
                           "gaps": ["异常网络下的重试"]}, ensure_ascii=False)
    # 补充：被删场景任务照抄被删标题的前缀，遗漏场景任务另起一个功能点。
    m = re.search(r"被删除（需用合格用例覆盖这些场景）：\n- 【(.+?)】", user)
    title = f"【{m.group(1)}】补齐用例" if m else "【登录-网络异常】断网重试"
    return json.dumps([{"title": title, "priority": "P2", "precondition": "-",
                        "steps": ["步骤1"], "expected_result": "结果"}], ensure_ascii=False)


def test_模块拆分路径的完整事件序列(monkeypatch):
    _install(monkeypatch, _full_handler,
             warnings=[{"case_index": 1, "warnings": ["引用了不存在的字段"]}])
    events = _collect()

    assert _shape(events) == [
        ("progress", "retrieving"),
        ("progress", "constructing"),
        ("knowledge", None),
        ("progress", "splitting"),
        ("modules", None),
        ("progress", "generating"),
        # 模块 0：开始 → 思考流 → 正文流 → 完成 → 进度
        ("module_start", 0), ("module_thinking", 0), ("module_chunk", 0), ("module_done", 0),
        ("progress", "generating"),
        ("module_start", 1), ("module_thinking", 1), ("module_chunk", 1), ("module_done", 1),
        ("progress", "generating"),
        ("progress", "validating"),
        ("progress", "reviewing"),
        ("review_start", 0), ("review_thinking", 0), ("review_chunk", 0), ("review_done", 0),
        ("review_start", 1), ("review_thinking", 1), ("review_chunk", 1), ("review_done", 1),
        ("progress", "reviewing"),
        ("progress", "supplementing"),
        # 补充任务：登录（补被删场景）/ 订单（补被删场景）/ 遗漏场景补充
        ("supplement_start", 0), ("supplement_thinking", 0), ("supplement_chunk", 0), ("supplement_done", 0),
        ("supplement_start", 1), ("supplement_thinking", 1), ("supplement_chunk", 1), ("supplement_done", 1),
        ("supplement_start", 2), ("supplement_thinking", 2), ("supplement_chunk", 2), ("supplement_done", 2),
        ("progress", "supplementing"),
        ("complete", None),
    ]

    # 内部收口约定不能漏给前端
    assert not any(ev["type"] == "_results" for ev in events)

    messages = [ev["message"] for ev in events if ev["type"] == "progress"]
    assert messages == [
        "正在检索知识库...",
        "检索到 6 条相关知识",
        "正在分析模块结构...",
        "已拆分为 2 个模块，开始并行生成：登录、订单",
        "模块生成进度 1/2：登录",
        "模块生成进度 2/2：订单",
        "正在校验...",
        "测试专家正在分模块并行评审用例...",
        "评审删除 2 条问题用例，保留 4 条",
        "正在分模块并行补充遗漏场景的用例...",
        "补充 3 条用例，共 7 条",
    ]


def test_模块事件带上前端要的字段(monkeypatch):
    _install(monkeypatch, _full_handler)
    events = _collect()
    by_type: dict[str, list[dict]] = {}
    for ev in events:
        by_type.setdefault(ev["type"], []).append(ev)

    assert by_type["modules"][0]["modules"] == ["登录", "订单"]
    # module_done 必须带解析好的用例（前端据此把卡片从流式文本切成用例列表）与耗时
    done = by_type["module_done"][0]
    assert [c["title"] for c in done["cases"]] == [
        "【登录-功能1】用例1", "【登录-功能2】用例2", "【登录-功能3】用例3"]
    assert done["module"] == "登录" and isinstance(done["elapsed"], float)
    # 评审/补充卡片的汇总字段
    assert by_type["review_done"][0]["kept"] == 2 and by_type["review_done"][0]["deleted"] == 1
    assert by_type["supplement_done"][0]["count"] == 1
    assert by_type["module_chunk"][0]["text"].startswith("[{")
    assert by_type["module_thinking"][0]["text"] == "思考[generate]"


def test_知识与complete事件的载荷(monkeypatch):
    _install(monkeypatch, _full_handler)
    events = _collect()
    knowledge = next(ev for ev in events if ev["type"] == "knowledge")
    complete = next(ev for ev in events if ev["type"] == "complete")

    assert knowledge["knowledge_used"] == {
        "field_dicts_count": 1, "business_rules_count": 1, "state_machines_count": 1,
        "term_mappings_count": 1, "prd_chunks_count": 1, "defect_chunks_count": 1,
        "historical_cases_count": 0,
    }
    assert knowledge["knowledge_matches"]["field_dicts"][0]["field_name"] == "username"
    # complete 重复带这两个字段作为断线重连兜底
    assert complete["knowledge_used"] == knowledge["knowledge_used"]
    assert complete["knowledge_matches"] == knowledge["knowledge_matches"]
    assert isinstance(complete["elapsed"], float)

    # 每组第一条被删 → 各剩 2 条；补充用例打 origin 标记并就近归位到同功能点后面
    assert [(c["title"], c.get("origin")) for c in complete["cases"]] == [
        ("【登录-功能2】用例2", None),
        ("【登录-功能3】用例3", None),
        ("【登录-功能1】补齐用例", "supplement"),
        ("【登录-网络异常】断网重试", "supplement"),
        ("【订单-功能2】用例2", None),
        ("【订单-功能3】用例3", None),
        ("【订单-功能1】补齐用例", "supplement"),
    ]


# ── 单批路径 ──

def test_关闭模块拆分时走单批生成(monkeypatch):
    def handler(kind, user):
        if kind == "generate":
            assert "只生成属于【" not in user  # 单批不带 module_focus
            return _cases_json("登录", 2)
        if kind == "review":
            return json.dumps({"reviews": [], "gaps": []}, ensure_ascii=False)
        return "[]"

    _install(monkeypatch, handler, split=False)
    events = _collect()

    assert _shape(events) == [
        ("progress", "retrieving"),
        ("progress", "constructing"),
        ("knowledge", None),
        ("progress", "generating"),
        ("progress", "validating"),
        ("progress", "reviewing"),
        ("review_start", 0), ("review_thinking", 0), ("review_chunk", 0), ("review_done", 0),
        ("complete", None),
    ]
    # 无删除、无遗漏 → 不进补充阶段
    assert [c["title"] for c in events[-1]["cases"]] == ["【登录-功能1】用例1", "【登录-功能2】用例2"]


def test_模块拆分只给一个模块时退化为单批(monkeypatch):
    def handler(kind, user):
        if kind == "module_split":
            return json.dumps({"modules": ["登录"], "covers_all": True}, ensure_ascii=False)
        if kind == "generate":
            assert "只生成属于【" not in user
            return _cases_json("登录", 1)
        if kind == "review":
            return json.dumps({"reviews": [], "gaps": []}, ensure_ascii=False)
        return "[]"

    _install(monkeypatch, handler)
    events = _collect()
    assert _shape(events) == [
        ("progress", "retrieving"), ("progress", "constructing"), ("knowledge", None),
        ("progress", "splitting"),
        ("progress", "generating"),
        ("progress", "validating"), ("progress", "reviewing"),
        ("review_start", 0), ("review_thinking", 0), ("review_chunk", 0), ("review_done", 0),
        ("complete", None),
    ]


# ── 失败路径 ──

def test_一条有效用例都没有时报error而不是complete(monkeypatch):
    """不能 emit complete：否则 task_service 会把空结果当成功落库，前端显示"成功，共 0 条"。

    且报错要带 parse_cases 给出的**可行动原因**（这里是"只吐了思考过程"），不是笼统一句
    "生成失败"——`_generate_one_batch` 曾把 error 占位在返回前就滤掉，使原因永远到不了前端。
    """
    _install(monkeypatch, lambda kind, user: "" if kind == "generate" else "[]", split=False)
    events = _collect()

    assert _shape(events) == [
        ("progress", "retrieving"), ("progress", "constructing"), ("knowledge", None),
        ("progress", "generating"),
        ("error", None),
    ]
    assert events[-1]["message"] == \
        "模型只输出了思考过程未产出用例（建议调低 LLM_REASONING_EFFORT 或调大 LLM_MAX_TOKENS）"


def test_模型判定无可测功能点时把原因透传给用户(monkeypatch):
    """模型正确返回 {"cases": []} 并在 gaps 里说明原因，这不是故障，别误报"请重试"。"""
    raw = '{"cases": [], "coverage": {"gaps": ["需求仅为无意义字符，无可提取功能点"]}}'
    _install(monkeypatch, lambda kind, user: raw if kind == "generate" else "[]", split=False)
    events = _collect()

    assert events[-1]["type"] == "error"
    assert events[-1]["message"] == "未生成用例：需求仅为无意义字符，无可提取功能点"


def test_原因占位不会混进正常结果(monkeypatch):
    """部分模块解析失败时，各留下的 error 占位只服务于「全空」判定，绝不能流进
    评审分组 / 补充 prompt / complete 事件，也不能出现在该模块的 module_done 卡片里。"""
    def handler(kind, user):
        if kind == "module_split":
            return json.dumps({"modules": ["登录", "订单"], "covers_all": True}, ensure_ascii=False)
        if kind == "generate":
            # 「订单」模块只吐思考、一条都解析不出来
            return "" if "只生成属于【订单】" in user else _cases_json("登录", 2)
        if kind == "review":
            return json.dumps({"reviews": [], "gaps": []}, ensure_ascii=False)
        return "[]"

    _install(monkeypatch, handler)
    events = _collect()
    complete = events[-1]
    assert complete["type"] == "complete"
    assert [c["title"] for c in complete["cases"]] == ["【登录-功能1】用例1", "【登录-功能2】用例2"]
    assert not any("error" in c for c in complete["cases"])
    # 失败模块的卡片收到空用例列表，而不是一条无 title 的空白用例
    done = {ev["index"]: ev for ev in events if ev["type"] == "module_done"}
    assert done[1]["cases"] == []
    # 评审只看到 2 条真用例（占位若混进去会多出一组「其它」）
    assert len([ev for ev in events if ev["type"] == "review_start"]) == 1


def test_全部模块都解析不出用例时透传首个原因(monkeypatch):
    def handler(kind, user):
        if kind == "module_split":
            return json.dumps({"modules": ["登录", "订单"], "covers_all": True}, ensure_ascii=False)
        return "" if kind == "generate" else "[]"

    _install(monkeypatch, handler)
    events = _collect()
    assert events[-1]["type"] == "error"
    assert "LLM_REASONING_EFFORT" in events[-1]["message"]


def test_模块全部失败时报error(monkeypatch):
    """并发 worker 抛异常只应让该模块跳过；全挂时按「无有效用例」收场。"""
    def handler(kind, user):
        if kind == "module_split":
            return json.dumps({"modules": ["登录", "订单"], "covers_all": True}, ensure_ascii=False)
        if kind == "generate":
            raise RuntimeError("模拟 LLM 故障")
        return "[]"

    _install(monkeypatch, handler)
    events = _collect()

    assert _shape(events) == [
        ("progress", "retrieving"), ("progress", "constructing"), ("knowledge", None),
        ("progress", "splitting"), ("modules", None), ("progress", "generating"),
        ("module_start", 0), ("module_thinking", 0), ("module_failed", 0), ("progress", "generating"),
        ("module_start", 1), ("module_thinking", 1), ("module_failed", 1), ("progress", "generating"),
        ("error", None),
    ]
    assert [ev["message"] for ev in events if ev["type"] == "progress"][-2:] == [
        "模块生成进度 1/2（模块「登录」失败已跳过）",
        "模块生成进度 2/2（模块「订单」失败已跳过）",
    ]


def test_评审把用例全删时全部保留(monkeypatch):
    """判定不可信就整组回滚，否则一次评审事故会把整批用例清空。"""
    def handler(kind, user):
        if kind == "generate":
            return _cases_json("登录", 2)
        if kind == "review":
            return json.dumps({"reviews": [{"index": 0, "verdict": "delete", "reason": "x"},
                                           {"index": 1, "verdict": "delete", "reason": "x"}],
                               "gaps": []}, ensure_ascii=False)
        return "[]"

    _install(monkeypatch, handler, split=False)
    events = _collect()
    complete = events[-1]
    assert complete["type"] == "complete"
    assert [c["title"] for c in complete["cases"]] == ["【登录-功能1】用例1", "【登录-功能2】用例2"]
    # deleted 被清空 → 不该出现"评审删除 N 条"，也不该进补充阶段
    assert not any("评审删除" in ev.get("message", "") for ev in events)
    assert not any(ev["type"].startswith("supplement") for ev in events)
