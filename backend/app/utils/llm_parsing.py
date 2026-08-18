"""LLM 输出的 JSON 解析与截断抢救（纯标准库，可轻量测试）。

从 generator_service 抽出来的原因与 case_grouping / case_ordering 一致：
那个模块顶部 import 了 sqlalchemy / ChromaStore / settings，而 CI 只装 pytest
（不装 chromadb 433MB 与带 torch 的 sentence-transformers），测试一旦 import 到
generator_service 就会 ModuleNotFoundError。这里只依赖 json / re / logging。

这组函数处理的是同一个现实问题：LLM 的输出不保证是干净 JSON。实际遇到过的形态——
    1. 直接可解析的 JSON                       → json.loads 一把过
    2. 裹在 ```json ... ``` 代码块里            → CODE_BLOCK_RE 剥壳
    3. 前后夹自然语言解说、中间一个数组         → extract_first_array 逐个 `[` 试解
    4. 合法空结果 {"cases": [], "gaps": [...]}  → empty_result_reason 透传原因
    5. 撞 max_tokens 被截断、顶层不闭合         → scan_json_objects 逐个抢救已闭合对象
    6. 只吐了 reasoning_content，正文为空       → parse_cases 首个分支直接给可行动提示

parse_cases 里的解析顺序即上表顺序：前面的路径更精确、后面的更宽容，不能调换——
把截断抢救提前会在正常输出里**漏掉**用例：scan_json_objects 只认带 title 的顶层对象，
同一数组里没有 title 的元素（模型偶尔混进来的备注/统计对象）会被悄悄吞掉，而精确路径
的 extract_cases 是原样保留整个数组的。
"""
import json
import logging
import re

logger = logging.getLogger(__name__)

# LLM 常把 JSON 裹在 markdown 代码块里（```json ... ```）。解析前先剥壳，
# 对象与数组两条解析路径都要用，所以提到模块级编译一次。
CODE_BLOCK_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```")


def scan_json_objects(raw: str, keep) -> list[dict]:
    """从残缺的 LLM 输出里逐个抓出完整的 JSON 对象。

    典型触发场景：LLM 已经吐了 N 个完整对象 + 半个不完整的，然后被 max_tokens 截断，
    整个数组/代码块都没闭合。这时 json.loads 整体解析必然失败，但每个已吐完的对象
    本身还是合法 JSON，json.JSONDecoder.raw_decode 可以从任意位置起解一个对象。

    策略：光标定位到第一个 `{`，循环 raw_decode + 跳到下一个 `{`。解不出来的位置
    （最后那个被切断的对象）直接丢弃，只保留 keep() 认可的 dict。

    keep 用来区分调用场景：评审判定认 index、用例认 title——都是各自的必备字段，
    用它挡掉顺带解出来的内层子对象。
    """
    decoder = json.JSONDecoder()
    out: list[dict] = []
    i = raw.find("{")
    while i != -1:
        try:
            obj, end = decoder.raw_decode(raw[i:])
        except json.JSONDecodeError:
            # 当前位置解不出来（比如最后被切断的那个）—— 跳到下一个 `{` 重试。
            i = raw.find("{", i + 1)
            continue
        if isinstance(obj, dict) and keep(obj):
            out.append(obj)
        # 从这个对象结束的位置继续找，跳过内部嵌套避免误抓。
        i = raw.find("{", i + end)
    return out


def parse_json_object(raw: str, require_key: str | None = None) -> dict | None:
    """从 LLM 输出中解析出一个 JSON 对象（容忍 markdown 代码块包裹）。

    require_key：调用方期望的顶层键，给了就只接受含该键的对象。末端的 raw_decode 兜底会
    从每一个 `{` 起试解，响应被截断（顶层对象未闭合）时极易解出**内层**的某个子对象并
    当成顶层返回——评审就踩过这个坑：截断后它返回了第一条 verdict 对象，调用方
    .get("reviews") 拿到空列表，整组判定静默归零、一条都没删。
    """
    def usable(obj) -> bool:
        return isinstance(obj, dict) and (require_key is None or require_key in obj)

    try:
        parsed = json.loads(raw)
        if usable(parsed):
            return parsed
    except json.JSONDecodeError:
        pass
    m = CODE_BLOCK_RE.search(raw)
    if m:
        try:
            parsed = json.loads(m.group(1))
            if usable(parsed):
                return parsed
        except json.JSONDecodeError:
            pass
    decoder = json.JSONDecoder()
    start = raw.find("{")
    while start != -1:
        try:
            parsed, _ = decoder.raw_decode(raw[start:])
            if usable(parsed):
                return parsed
        except json.JSONDecodeError:
            pass
        start = raw.find("{", start + 1)
    return None


def salvage_reviews(raw: str) -> list[dict]:
    """从残缺的评审输出里逐个抓完整的判定对象。

    评审撞满 max_tokens 时顶层 JSON 不闭合，整体解析必然失败，但每条已吐完的判定本身
    还是合法 JSON。判据用 index —— 判定条目的必备字段。这样至少保住截断前已经判完的
    那部分，而不是整组归零。
    """
    return scan_json_objects(raw, lambda o: "index" in o)


def salvage_truncated_cases(raw: str) -> list[dict]:
    """从残缺的 LLM 输出里逐个抓完整的 case 对象。

    典型触发场景：LLM 已经吐了 N 条完整用例 + 半条不完整，然后被 max_tokens 截断，
    整个数组/代码块都没闭合。判据用 title —— case 的必备字段，用它挡掉顺带解出来的
    内层子对象（比如 steps 里的结构）。
    """
    return scan_json_objects(raw, lambda o: "title" in o)


def extract_cases(parsed) -> list[dict] | None:
    """从已解析的 JSON 里取出用例数组。接受裸数组或 {"cases": [...]} 两种形态。

    要求数组里至少有一条带 title——否则无法与"恰好也是数组的别的东西"区分开。
    """
    if isinstance(parsed, dict) and "cases" in parsed:
        parsed = parsed["cases"]
    if isinstance(parsed, list):
        cases = [case for case in parsed if isinstance(case, dict)]
        if cases and any("title" in c for c in cases):
            return cases
    return None


def extract_first_array(raw: str) -> list[dict] | None:
    """逐个 `[` 试解，取出第一个能当成用例数组的。

    应对"前后夹自然语言解说、中间一个数组"的输出形态。
    """
    decoder = json.JSONDecoder()
    start = raw.find("[")
    while start != -1:
        try:
            parsed, _ = decoder.raw_decode(raw[start:])
            cases = extract_cases(parsed)
            if cases is not None:
                return cases
        except json.JSONDecodeError:
            pass
        start = raw.find("[", start + 1)
    return None


def empty_result_reason(raw: str) -> str | None:
    """识别"模型合法地判定无可测内容"的空结果，返回面向用户的原因说明。

    模型对无功能点的需求（如"哈哈哈"）会正确返回 {"cases": [], "coverage": {"gaps": [...]}}
    这类空数组结果。此前解析器只认"含 title 的非空数组"，会把这种情况误报成"格式错误，请重试"，
    误导用户以为是系统故障。这里在解析末端兜底：只有当 raw 是合法 JSON 对象、且 cases 显式为空数组
    时才判定为空结果（返回非 None），从 gaps / coverage.gaps 提取原因；无法确认则返回 None，
    交回上层继续走截断抢救等后续路径。
    """
    parsed = parse_json_object(raw, require_key="cases")
    if not isinstance(parsed, dict) or not isinstance(parsed.get("cases"), list) or parsed["cases"]:
        return None
    gaps = parsed.get("gaps")
    if not isinstance(gaps, list) or not gaps:
        coverage = parsed.get("coverage")
        gaps = coverage.get("gaps") if isinstance(coverage, dict) else None
    if isinstance(gaps, list) and gaps:
        reason = "；".join(str(g) for g in gaps if g)
        if reason:
            return f"未生成用例：{reason}"
    return "未生成用例：模型判定该需求无可提取的可测功能点，请补充更明确的功能描述后重试"


def parse_cases(raw: str) -> list[dict]:
    """把 LLM 的原始输出解析成用例列表。

    解析失败时返回单条 {"error": ...} 而不抛异常——上层据此把可行动的原因直接展示给
    用户（"调大 max_tokens" / "需求无可测功能点"），而不是笼统一句"生成失败"。
    """
    # 空串 = 模型只吐了 reasoning_content 就结束（多为推理强度过高、思考爆了 max_tokens），
    # 一个 JSON 起始符都没有则说明整段都是自然语言（拒答/思考流兜底）。这两种情况都不该
    # 走后面的 JSON 分支——直接给用户可行动的提示，别再让人猜"格式错误"是啥意思。
    if not raw or ("{" not in raw and "[" not in raw):
        logger.warning("LLM 未产出结构化正文（len=%d），可能是推理强度过高或 max_tokens 不足", len(raw))
        return [{"error": "模型只输出了思考过程未产出用例（建议调低 LLM_REASONING_EFFORT 或调大 LLM_MAX_TOKENS）"}]
    try:
        parsed = json.loads(raw)
        cases = extract_cases(parsed)
        if cases is not None:
            return cases
    except json.JSONDecodeError:
        logger.debug("LLM 输出不是直接可解析的 JSON，尝试从代码块提取")
    m = CODE_BLOCK_RE.search(raw)
    if m:
        try:
            parsed = json.loads(m.group(1))
            cases = extract_cases(parsed)
            if cases is not None:
                return cases
        except json.JSONDecodeError:
            logger.debug("代码块中的 LLM 输出不是合法 JSON，尝试提取数组")
    array_cases = extract_first_array(raw)
    if array_cases is not None:
        return array_cases
    # 合法空结果：模型正确判定"无可测内容"，返回了 {"cases": []} 并在 gaps 里说明原因
    # （典型：需求过于简单/无功能点）。这不是格式错误，把原因透传给用户，别误报"请重试"。
    empty_reason = empty_result_reason(raw)
    if empty_reason is not None:
        logger.info("LLM 判定无可测内容，未生成用例：%s", empty_reason)
        return [{"error": empty_reason}]
    # 前面几条路径都失败，通常是响应被 max_tokens 截断导致 JSON 未闭合。
    # 用 raw_decode 逐个抓取已闭合的 case 对象，保住已经完整生成的部分，避免整批丢失。
    salvaged = salvage_truncated_cases(raw)
    if salvaged:
        logger.warning("LLM 输出疑似被截断，抢救出 %s 条完整用例（考虑调大 LLM_MAX_TOKENS）", len(salvaged))
        return salvaged
    # 所有路径都失败：把 raw 的规模与首尾片段打出来，区分空串 / 拒答文本 / 完全非 JSON 的失败模式。
    # 之前只 debug 级别 log，等于什么线索都没有，复现一次要猜半天。
    logger.warning(
        "LLM 输出无法解析为用例数组（len=%d, head=%r, tail=%r）",
        len(raw), raw[:200], raw[-200:] if len(raw) > 200 else "",
    )
    return [{"error": "模型输出格式错误，请重试"}]
