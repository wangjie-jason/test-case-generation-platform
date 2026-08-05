"""标题【】前缀的解析与补充用例的就近插入（纯字符串逻辑，无外部依赖）。

从 generator_service 抽出来，为的是让排序/归位这条逻辑可测：generator_service 顶部
import 了 ChromaStore，测试一 import 就连带拉起 chromadb（约 433 MB），CI 里装依赖既慢
又脆。这里的函数只做字符串与列表处理，测试和 CI 都不必碰向量库。

注意本模块的 title_path 与 case_ordering.title_segs 并非同一语义：前者丢弃空段
（【A--B】→ ['A','B']），后者保留（→ ('A','','B')）。搬迁时刻意保持各自原样，未"顺手
统一"——归位与排序是两条独立的既有行为，合并语义等于悄悄改动其中一条。
"""
import re

_TAG_RE = re.compile(r"\s*【\s*([^】]+?)\s*】")


def title_prefix(title: str) -> str:
    """取标题里【】内的模块前缀（去掉 - 后的功能点，只留最顶层模块用于就近归组）。
    如【PC端-工作台-统计概览】xxx → 'PC端'；无前缀则返回空串。"""
    m = _TAG_RE.match(title or "")
    if not m:
        return ""
    return m.group(1).split("-")[0].strip()


def title_path(title: str) -> list[str]:
    """取标题里【】内的完整模块层级路径（按 - 逐级拆分），用于子模块级就近归组。
    如【PC端-工作台-统计概览】xxx → ['PC端', '工作台', '统计概览']；无前缀则返回 []。"""
    m = _TAG_RE.match(title or "")
    if not m:
        return []
    return [seg.strip() for seg in m.group(1).split("-") if seg.strip()]


def common_path_len(a: list[str], b: list[str]) -> int:
    """两条模块路径逐级比较，返回从顶层开始连续相同的层数（越大越同属细分子模块）。"""
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def merge_supplements(kept: list[dict], supplements: list[dict]) -> list[dict]:
    """把补充用例就近插到同模块用例后面，而不是一律追加到末尾。

    以标题【】里的模块层级路径为归组依据（细化到子模块）：为每条补充用例在 kept 中
    找与其路径公共前缀最长的那些用例，插到其中最后一条之后——同顶层模块里优先挨着
    同一子功能。顶层模块都对不上（全新模块）的补充按原顺序追加到末尾。
    """
    result = list(kept)
    for supp in supplements:
        supp_path = title_path(supp.get("title", ""))
        insert_at = None
        best_score = 0
        if supp_path:
            for i, c in enumerate(result):
                score = common_path_len(title_path(c.get("title", "")), supp_path)
                # 至少顶层模块相同（score>=1）才算同模块；公共前缀更长的（同子模块）优先，
                # 同分时取更靠后的位置，保证插到该（子）模块最后一条之后。
                if score >= 1 and score >= best_score:
                    best_score = score
                    insert_at = i + 1
        if insert_at is None:
            result.append(supp)
        else:
            result.insert(insert_at, supp)
    return result
