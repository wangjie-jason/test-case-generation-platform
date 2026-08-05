"""标题前缀解析与补充用例就近插入的测试（app/utils/case_grouping.py）。

这些函数原在 generator_service 里，因该模块顶部 import ChromaStore 而无法轻量测试，
随 CI 一并抽出。搬迁时已用真实数据验证与旧实现逐条等价，这里补的是**行为守卫**，
尤其钉住两处容易被"顺手统一"改坏的语义差异（见 test_与_case_ordering_的路径语义不同）。
"""
import pytest

from app.utils.case_grouping import (
    common_path_len,
    merge_supplements,
    title_path,
    title_prefix,
)


# ------------------------------------------------------------ title_prefix

@pytest.mark.parametrize("title, expected", [
    ("【PC端-工作台-统计概览】验证问候语", "PC端"),
    ("【单层模块】用例", "单层模块"),
    ("【 A - B 】两侧留白", "A"),
    ("  【前有空格-B】用例", "前有空格"),
    ("没有前缀的标题", ""),
    ("", ""),
])
def test_title_prefix只取最顶层模块(title, expected):
    assert title_prefix(title) == expected


# -------------------------------------------------------------- title_path

@pytest.mark.parametrize("title, expected", [
    ("【PC端-工作台-统计概览】xxx", ["PC端", "工作台", "统计概览"]),
    ("【单层】v", ["单层"]),
    ("【 A - B 】留白逐级 strip", ["A", "B"]),
    ("没有前缀", []),
    ("", []),
])
def test_title_path逐级拆分(title, expected):
    assert title_path(title) == expected


def test_title_path丢弃空段():
    """【A--B】的中间空段被丢弃——这是归位逻辑的既有语义，不是笔误。"""
    assert title_path("【A--B】z") == ["A", "B"]


def test_与_case_ordering_的路径语义不同():
    """钉住一处易被误合并的差异：归位丢空段，排序保留空段。

    两者是各自独立的既有行为。若哪天有人"顺手统一"成同一个函数，这条会挂——那不是
    重复代码清理，而是悄悄改动了其中一条链路的行为。
    """
    from app.utils.case_ordering import title_segs

    assert title_path("【A--B】z") == ["A", "B"]
    assert title_segs("【A--B】z") == ("A", "", "B")


# ---------------------------------------------------------- common_path_len

@pytest.mark.parametrize("a, b, expected", [
    (["A", "B", "C"], ["A", "B", "D"], 2),
    (["A"], ["A", "B"], 1),
    (["A", "B"], ["X", "B"], 0),
    ([], ["A"], 0),
    ([], [], 0),
    (["A", "B"], ["A", "B"], 2),
])
def test_common_path_len只算从顶层起连续相同的层数(a, b, expected):
    assert common_path_len(a, b) == expected


# -------------------------------------------------------- merge_supplements

def test_补充插到同子模块最后一条之后():
    kept = [
        {"title": "【PC端-工作台】用例1"},
        {"title": "【PC端-工作台】用例2"},
        {"title": "【PC端-任务】用例3"},
    ]
    out = merge_supplements(kept, [{"title": "【PC端-工作台】补充"}])
    assert [c["title"] for c in out] == [
        "【PC端-工作台】用例1",
        "【PC端-工作台】用例2",
        "【PC端-工作台】补充",  # 同子模块末尾，而非顶层模块末尾
        "【PC端-任务】用例3",
    ]


def test_同子模块优先于仅同顶层():
    kept = [
        {"title": "【PC端-任务】用例1"},
        {"title": "【PC端-工作台】用例2"},
    ]
    out = merge_supplements(kept, [{"title": "【PC端-任务】补充"}])
    # 公共前缀更长的「任务」胜过仅顶层相同的「工作台」
    assert [c["title"] for c in out][1] == "【PC端-任务】补充"


def test_全新顶层模块的补充追加到末尾():
    kept = [{"title": "【PC端-工作台】用例1"}]
    out = merge_supplements(kept, [{"title": "【移动端-首页】全新"}])
    assert [c["title"] for c in out] == ["【PC端-工作台】用例1", "【移动端-首页】全新"]


def test_无前缀的补充追加到末尾():
    kept = [{"title": "【PC端-工作台】用例1"}]
    out = merge_supplements(kept, [{"title": "没有前缀的补充"}])
    assert [c["title"] for c in out] == ["【PC端-工作台】用例1", "没有前缀的补充"]


def test_多条补充各自归位且保持相对顺序():
    kept = [
        {"title": "【A-甲】用例1"},
        {"title": "【B-乙】用例2"},
    ]
    supps = [
        {"title": "【A-甲】补充1"},
        {"title": "【B-乙】补充2"},
        {"title": "【A-甲】补充3"},
    ]
    out = [c["title"] for c in merge_supplements(kept, supps)]
    assert out.index("【A-甲】补充1") < out.index("【A-甲】补充3"), "同模块的多条补充保持原相对顺序"
    assert out.index("【A-甲】补充3") < out.index("【B-乙】用例2"), "都归到 A-甲 那一段"


def test_不修改传入的列表():
    """generator_service 会拿返回值覆盖 all_cases，就地改会让调用方状态难以推断。"""
    kept = [{"title": "【A-甲】用例1"}]
    supps = [{"title": "【A-甲】补充"}]
    merge_supplements(kept, supps)
    assert len(kept) == 1 and len(supps) == 1


def test_空输入():
    assert merge_supplements([], []) == []
    assert [c["title"] for c in merge_supplements([], [{"title": "【A】孤儿补充"}])] == ["【A】孤儿补充"]
