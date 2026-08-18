"""LLM 输出解析与截断抢救的测试（app/utils/llm_parsing.py）。

这组函数原在 generator_service 里，因该模块顶部 import sqlalchemy / ChromaStore / settings
而无法在只装 pytest 的 CI 下测试，随本次清理抽出——与 case_grouping / case_ordering 同一思路。

重点钉住三件容易被"顺手优化"改坏的事：
  1. parse_cases 的解析顺序（精确路径在前、宽容路径在后）。把截断抢救提前会在正常
     输出里漏掉用例——salvage 只认带 title 的顶层对象，同数组里没有 title 的元素会被吞掉。
  2. parse_json_object 的 require_key。少了它，截断时会解出内层的第一个子对象当顶层
     返回——线上就是这么让整组评审判定静默归零的（调用方 .get("reviews") 拿到空列表，
     说删了却一条没删）。
  3. 解析失败返回 [{"error": ...}] 而非抛异常，且不同失败模式给不同的可行动提示。
"""
import pytest

from app.utils.llm_parsing import (
    empty_result_reason,
    extract_cases,
    extract_first_array,
    parse_cases,
    parse_json_object,
    salvage_reviews,
    salvage_truncated_cases,
    scan_json_objects,
)


# ── parse_cases：六种真实输入形态 ──

@pytest.mark.parametrize("name, raw, expected_titles", [
    ("裸数组", '[{"title": "A"}, {"title": "B"}]', ["A", "B"]),
    ("cases 包裹", '{"cases": [{"title": "A"}]}', ["A"]),
    ("markdown 代码块", '```json\n[{"title": "A"}]\n```', ["A"]),
    ("不带 json 标记的代码块", '```\n[{"title": "A"}]\n```', ["A"]),
    ("前后夹自然语言", '好的，以下是用例：\n[{"title": "A"}]\n以上共 1 条。', ["A"]),
    ("代码块内 cases 包裹", '```json\n{"cases": [{"title": "A"}]}\n```', ["A"]),
])
def test_parse_cases识别各种包裹形态(name, raw, expected_titles):
    assert [c["title"] for c in parse_cases(raw)] == expected_titles


def test_parse_cases在截断时抢救已完整的用例():
    """撞 max_tokens 时顶层数组不闭合，整体解析必失败，但已吐完的用例要保住。"""
    raw = '[{"title": "A", "steps": ["s1"]}, {"title": "B", "steps": ["s2"]}, {"title": "C'
    assert [c["title"] for c in parse_cases(raw)] == ["A", "B"]


def test_parse_cases空串给出可行动提示():
    """模型只吐 reasoning_content 就结束——提示调推理强度/max_tokens，别说"格式错误"。"""
    result = parse_cases("")
    assert len(result) == 1
    assert "LLM_REASONING_EFFORT" in result[0]["error"]


def test_parse_cases纯自然语言给出可行动提示():
    """整段都是拒答文本、一个 JSON 起始符都没有，走同一条提示分支。"""
    result = parse_cases("抱歉，我无法完成这个请求。")
    assert len(result) == 1
    assert "LLM_REASONING_EFFORT" in result[0]["error"]


def test_parse_cases把合法空结果的原因透传给用户():
    """模型正确判定"无可测功能点"不是故障，别误报"请重试"。"""
    raw = '{"cases": [], "coverage": {"gaps": ["需求仅为无意义字符，无可提取功能点"]}}'
    result = parse_cases(raw)
    assert len(result) == 1
    assert "无可提取功能点" in result[0]["error"]
    assert "请重试" not in result[0]["error"]


def test_parse_cases彻底失败时才回落到格式错误():
    raw = '{"unexpected": {"nested": 1}}'
    result = parse_cases(raw)
    assert result == [{"error": "模型输出格式错误，请重试"}]


def test_parse_cases的解析顺序_精确路径必须在截断抢救之前():
    """守卫解析顺序。诱饵是「同一数组里混着没有 title 的元素」：正常路径整段 json.loads
    后原样保留 2 条，而 salvage 逐个扫顶层对象、只认带 title 的，会把第一条悄悄吞掉。

    这条原本用的输入是 `{"cases":[{"title":..,"steps":[{"title":..}]}]}`，守不住任何东西——
    salvage 对它返回 `[]`（scan_json_objects 解出的顶层对象没有 title 就跳过，且会跳过整段
    嵌套），于是抢救路径提前也会落回正常路径，两种顺序结果相同。已实测：把 salvage 挪到
    parse_cases 最前面，旧输入下全部测试照样通过。
    """
    raw = '[{"note": "x", "sub": {"title": "decoy"}}, {"title": "A"}]'
    assert len(parse_cases(raw)) == 2
    # 单独跑抢救路径只剩 1 条——这正是它必须排在后面的原因。
    assert len(salvage_truncated_cases(raw)) == 1


def test_parse_cases不把steps里的子对象当成用例():
    """steps 里的结构也含 title，不能被展平成额外的用例（守 extract_cases 不递归）。"""
    raw = '{"cases": [{"title": "外层", "steps": [{"title": "这是步骤里的字段"}]}]}'
    result = parse_cases(raw)
    assert len(result) == 1
    assert result[0]["title"] == "外层"


# ── parse_json_object：require_key 是防静默归零的关键 ──

def test_parse_json_object正常解析():
    assert parse_json_object('{"reviews": [{"index": 0}]}', require_key="reviews") == {"reviews": [{"index": 0}]}


def test_parse_json_object剥掉代码块():
    assert parse_json_object('```json\n{"modules": ["A"]}\n```', require_key="modules") == {"modules": ["A"]}


def test_require_key挡住截断时解出的内层对象():
    """核心回归：顶层 {"reviews": [...]} 被截断未闭合时，raw_decode 会从第二个 `{`
    解出内层的 verdict 对象。没有 require_key 就会把它当顶层返回，调用方
    .get("reviews") 拿到空列表 → 整组判定静默归零。"""
    truncated = '{"reviews": [{"index": 0, "verdict": "delete", "reason": "重复"}'
    assert parse_json_object(truncated, require_key="reviews") is None
    # 不传 require_key 时确实会解出内层对象——这正是为什么调用方必须传。
    assert parse_json_object(truncated) == {"index": 0, "verdict": "delete", "reason": "重复"}


def test_parse_json_object无匹配返回None():
    assert parse_json_object("完全不是 JSON", require_key="cases") is None


# ── scan_json_objects 与两个 salvage 包装 ──

def test_scan_json_objects按判据过滤():
    raw = '[{"a": 1}, {"b": 2}, {"a": 3}]'
    assert scan_json_objects(raw, lambda o: "a" in o) == [{"a": 1}, {"a": 3}]


def test_scan_json_objects跳过内部嵌套避免误抓():
    """解出一个对象后要从它结束的位置继续找，否则会把嵌套的子对象也抓出来。"""
    raw = '[{"id": 1, "inner": {"id": 99}}, {"id": 2}]'
    assert [o["id"] for o in scan_json_objects(raw, lambda o: "id" in o)] == [1, 2]


def test_salvage_reviews认index():
    raw = '{"reviews": [{"index": 0, "verdict": "keep"}, {"index": 1, "verdict": "delete"}, {"ind'
    assert [r["index"] for r in salvage_reviews(raw)] == [0, 1]


def test_salvage_truncated_cases认title():
    raw = '[{"title": "A"}, {"title": "B"}, {"titl'
    assert [c["title"] for c in salvage_truncated_cases(raw)] == ["A", "B"]


def test_salvage在无可抢救内容时返回空列表():
    assert salvage_reviews("没有任何 JSON") == []
    assert salvage_truncated_cases("{") == []


# ── extract_cases / extract_first_array ──

@pytest.mark.parametrize("parsed, expected", [
    ([{"title": "A"}], [{"title": "A"}]),
    ({"cases": [{"title": "A"}]}, [{"title": "A"}]),
    ([], None),                                     # 空数组不算用例
    ([{"no_title": 1}], None),                      # 一条都没 title，无法与别的数组区分
    (["字符串", {"title": "A"}], [{"title": "A"}]),   # 非 dict 元素被过滤
    ({"other": 1}, None),
    ("不是容器", None),
])
def test_extract_cases的接受条件(parsed, expected):
    assert extract_cases(parsed) == expected


def test_extract_first_array跳过不合格的数组():
    """先出现的 ["a","b"] 不含 title，应继续找到后面真正的用例数组。"""
    raw = '标签: ["a", "b"]\n用例: [{"title": "A"}]'
    assert extract_first_array(raw) == [{"title": "A"}]


def test_extract_first_array无合格数组返回None():
    assert extract_first_array('["a", "b"]') is None


# ── empty_result_reason ──

def test_empty_result_reason从顶层gaps取原因():
    raw = '{"cases": [], "gaps": ["缺少功能描述", "无可测点"]}'
    assert empty_result_reason(raw) == "未生成用例：缺少功能描述；无可测点"


def test_empty_result_reason从coverage_gaps取原因():
    raw = '{"cases": [], "coverage": {"gaps": ["需求过于简单"]}}'
    assert empty_result_reason(raw) == "未生成用例：需求过于简单"


def test_empty_result_reason无gaps时给兜底文案():
    assert "无可提取的可测功能点" in empty_result_reason('{"cases": []}')


def test_empty_result_reason对非空cases返回None():
    """cases 非空说明不是空结果，要交回上层继续走正常路径。"""
    assert empty_result_reason('{"cases": [{"title": "A"}]}') is None


def test_empty_result_reason对无法确认的输入返回None():
    """返回 None 才能让上层继续尝试截断抢救，不能在这里误判为空结果。"""
    assert empty_result_reason("不是 JSON") is None
    assert empty_result_reason('{"cases": "不是数组"}') is None
