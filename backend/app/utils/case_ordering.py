"""用例展示顺序的排序规则（生成流程与 resort_batch 运维脚本共用）。

抽到这里是为了让"生成时自动排"和"对已落库批次补排"走同一套逻辑——两处各写一份，
改了一边漏另一边，就会出现同一批用例在生成页和历史页顺序不一致。

规则分三层，与生成阶段的语义保持一致：
1. 按顶层模块切成连续块，块的先后**不变**——顶层顺序来自需求切割的 modules 列表，
   那是人给定的阅读顺序，不能按字母或标题重排。
2. 块内按标题【】的层级路径归位，于是补充用例归到自己所属子功能那一段。传了
   is_movable 就只插可动用例（place_by_path），否则整块层级排序（sort_block_by_path）。
3. 同一路径段内再按**功能点**聚合：路径最后一级往往只到页面/区块（「提交页」
   「统计概览」），真正的功能点（「现场照片」「本周走访」）写在标题正文里，光靠路径
   排不到一起。故在正文上做单向前移，见 forward_place。

is_movable 贯穿第 2、3 层：判 False 的用例位置一律不动，只作被吸附的锚点。第 2 层
同样要拦——路径排序自己就会把交错的路径并段，那也是在动原有用例。

函数都接受 `title_of` 取标题，因此既能排 ORM 对象（title 属性）也能排 dict（title 键）。
"""
import re
from typing import Callable, TypeVar

T = TypeVar("T")

# 判定「同一功能点」所需的正文共同前缀字数。取 3 有实测依据：在已落库批次上，真正同
# 功能点的用例对（本周走访…/逾期任务…/待走访…）共同前缀最少 3 字，而不该聚在一起的
# 跳转类用例对（「点击待走访跳转并筛选」⇔「点击逾期任务跳转并筛选」）最多 2 字，两者
# 可干净分开。放宽到子串匹配会把「点击/跳转/筛选」这类通用词也算成相似，反而误聚。
MIN_PREFIX = 3
# 正文开头的套话动词：功能点名紧跟其后，剥掉才能让共同前缀对齐到功能点本身。
_LEAD_VERB_RE = re.compile(r"^(验证|校验|确认|检查|测试)+")
_TAG_RE = re.compile(r"^\s*【([^】]+?)】")


def title_segs(title: str) -> tuple[str, ...]:
    """标题【模块-子模块-...】→ 层级路径元组；没有【】的返回空元组（排到块内原位）。"""
    m = _TAG_RE.match(title or "")
    return tuple(s.strip() for s in m.group(1).split("-")) if m else ()


def func_desc(title: str) -> str:
    """取标题里【】之后的正文并剥掉开头套话动词，用于比对功能点。
    如「【A-B】验证本周走访显示户数」→「本周走访显示户数」。"""
    body = _TAG_RE.sub("", title or "").strip()
    return _LEAD_VERB_RE.sub("", body).strip()


def common_prefix_len(a: str, b: str) -> int:
    """两段正文从头逐字比较，返回连续相同的字数（越长越可能是同一功能点）。"""
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def forward_place(cases: list[T], title_of: Callable[[T], str],
                  is_movable: Callable[[T], bool] | None = None) -> list[T]:
    """同一路径内按功能点聚合，只做**单向前移**：已排定的顺序永不改动，每条用例插到
    它前面共同前缀最长（且 >= MIN_PREFIX）那一簇的末尾；前面没有同功能点的就留在原位。

    单向是关键。双向重排（把整段按相似度重新串起来）会让总述型用例被挤到细则后面
    ——如「验证走访类型单选（4类）」跑到「走访类型为『日常走访』时提交成功」等 4 条
    之后。而总述天然先于细则出现，只允许后来者往前插，总述就不可能被移走。

    is_movable 限定哪些用例可以被挪：传入后，判 False 的用例一律留在原位（只作为
    被吸附的锚点）。生成流程用它锁住原有用例、只让补充用例归位——LLM 一次产出的用例
    本就按功能点聚好（实测 350 个子功能路径里仅 6 个被拆段），动它们收益小、风险大：
    共同前缀是字面启发式，会把「点击X跳转」这类同句式的跨功能点用例误吸到一起。
    """
    if len(cases) < 2:
        return list(cases)
    descs = [func_desc(title_of(c)) for c in cases]
    out: list[int] = [0]  # 存 cases 的下标，保持已排定顺序
    for i in range(1, len(cases)):
        if is_movable is not None and not is_movable(cases[i]):
            out.append(i)  # 锁定：保持原有相对位置，仅供后面的用例作锚点
            continue
        scores = [(common_prefix_len(descs[i], descs[j]), pos) for pos, j in enumerate(out)]
        best = max(s for s, _ in scores)
        if best < MIN_PREFIX:
            out.append(i)  # 前面没有同功能点的用例，维持原有位置
            continue
        # 插到该簇最靠后的一条之后，使同功能点的多条用例连成一段
        out.insert(max(pos for s, pos in scores if s == best) + 1, i)
    return [cases[i] for i in out]


def split_top_blocks(cases: list[T], title_of: Callable[[T], str]) -> list[list[T]]:
    """按顶层模块切成连续块，保持块与块之间的原有先后。

    只识别块边界、不重排块序：生成流程里 all_cases 已按切割模块下标拼接（同模块连续、
    块序=切割顺序），这里按"连续相同顶层名"切一刀即可，顶层顺序天然被保住。

    不改成"按顶层名首次出现归组"：那样会把同一顶层模块散落在多处的用例强行并到一块，
    在已落库数据上实测会额外挪动 374 条——顶层模块本身分散是既有事实（人工插入、多次
    补排都可能造成），归组等于替用户重新决定模块边界，超出"让子功能挨在一起"的诉求。
    """
    blocks: list[list[T]] = []
    prev = object()
    for c in cases:
        top = title_segs(title_of(c))[:1]
        if top != prev:
            blocks.append([c])
            prev = top
        else:
            blocks[-1].append(c)
    return blocks


def place_by_path(block: list[T], title_of: Callable[[T], str],
                  is_movable: Callable[[T], bool]) -> list[T]:
    """按路径归位，但只挪可动用例：锁定用例按原序构成骨架，一条都不重排。

    这是 sort_block_by_path 的"只插不排"版本。层级排序哪怕整块只有锁定用例，也会把
    交错的路径并段（【A-登录】【A-注册】【A-登录】→ 两条登录并到一起），那等于替用户
    重排他原有的用例；而 is_movable 的承诺是"原有用例位置一律不动"。

    先摆骨架再逐条插入（而非边遍历边插），实测骨架版与流式版在 300 组随机补充上输出
    完全相同，两种写法等价。保留先摆骨架是因其更易读。
    """
    out = [c for c in block if not is_movable(c)]
    for c in block:
        if not is_movable(c):
            continue
        segs = title_segs(title_of(c))
        scores = [(_affinity(title_segs(title_of(o)), segs), pos)
                  for pos, o in enumerate(out)]
        best = max((s for s, _ in scores), default=(0, 0))
        if best[0] < 1:
            out.append(c)  # 连顶层都对不上（或无【】前缀）：留在块尾
        else:
            # 插到最佳档位里最靠后那条之后，于是同路径的多条连成一段。
            out.insert(max(pos for s, pos in scores if s == best) + 1, c)
    return out


def _affinity(cand: tuple[str, ...], supp: tuple[str, ...]) -> tuple[int, int]:
    """骨架用例 cand 对待插用例 supp 的吸附力，越大越该插到它后面。

    第一维是路径公共层数（同子功能胜过仅同模块）。第二维压低 supp 的**后代**：
    光比公共层数分不出"路径完全相同"和"我是你的祖先"——总纲【提交页】与细则
    【提交页-日常走访】对一条【提交页】补充的公共层数都是 2，同分取更靠后就把补充推到
    了细则之后，总纲与总纲被细则隔开。后代降一档，补充才会紧跟在同级的总纲之后。
    """
    n = len_common_segs(cand, supp)
    is_descendant = n == len(supp) and len(cand) > len(supp)
    return (n, 0 if is_descendant else 1)


def len_common_segs(a: tuple[str, ...], b: tuple[str, ...]) -> int:
    """两条层级路径逐级比较，返回从顶层起连续相同的层数（越大越同属细分子功能）。"""
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def sort_block_by_path(block: list[T], title_of: Callable[[T], str]) -> list[T]:
    """块内层级化稳定排序：各级路径按其在块内首次出现位置，同级内保持原相对顺序。"""
    rank: dict[tuple[str, ...], int] = {}
    for i, c in enumerate(block):
        segs = title_segs(title_of(c))
        for depth in range(1, len(segs) + 1):
            rank.setdefault(segs[:depth], i)

    def sort_key(item: tuple[int, T]):
        i, c = item
        segs = title_segs(title_of(c))
        # 逐级 rank + 原下标兜底：同一子功能内保持原相对顺序（稳定）
        return tuple(rank[segs[:depth]] for depth in range(1, len(segs) + 1)) + (i,)

    return [c for _, c in sorted(enumerate(block), key=sort_key)]


def resort_block(block: list[T], title_of: Callable[[T], str],
                 is_movable: Callable[[T], bool] | None = None) -> list[T]:
    """块内两步：先按路径归位（第2层），再在同路径段内按功能点前移聚合（第3层）。

    第2层按 is_movable 二选一——不传就整块层级排序（运维脚本补排历史批次），传了就只
    插可动用例、锁定用例的相对顺序原样保留（生成流程）。两层都必须尊重 is_movable，
    只在第3层拦是不够的：路径排序自己就会重排锁定用例。
    """
    ordered = (sort_block_by_path(block, title_of) if is_movable is None
               else place_by_path(block, title_of, is_movable))
    # 路径排完后，同一路径的用例已连成一段，段内再按正文功能点做单向前移聚合。
    out: list[T] = []
    start = 0
    for i in range(1, len(ordered) + 1):
        if i == len(ordered) or title_segs(title_of(ordered[i])) != title_segs(title_of(ordered[start])):
            out.extend(forward_place(ordered[start:i], title_of, is_movable))
            start = i
    return out


def order_cases(cases: list[T], title_of: Callable[[T], str],
                is_movable: Callable[[T], bool] | None = None) -> list[T]:
    """完整三层排序：顶层块序不变 → 块内路径归位 → 路径段内功能点前移。

    is_movable 见 place_by_path / forward_place：生成流程传它来锁住原有用例、只让补充
    用例归位（第2、3层都受约束）；运维脚本补排历史批次时不传（整批一起整理）。
    """
    return [c for block in split_top_blocks(cases, title_of)
            for c in resort_block(block, title_of, is_movable)]
