"""重排指定批次（batch_id）用例的展示顺序，让同一子功能的用例挨在一起。

用法（在 backend 目录下，使用装好依赖的解释器）：
    python -m scripts.resort_batch <batch_id> [--dry-run]

列表接口按 created_at 升序返回（routers/generation.py），所以"排序"就是按目标顺序
重写 created_at（起始时间沿用该批次原最早时间，逐条 +1 秒）。

排序规则分三层，与生成阶段的语义保持一致：
1. 先按顶层模块把用例切成连续块，块的先后不变——顶层顺序来自需求切割的 modules
   列表，那是人给定的阅读顺序，不能按字母或标题重排。
2. 块内按模块层级路径（标题【】里以 - 分隔的各级）做层级化稳定排序，每级的次序取
   该级路径在块内的首次出现位置。于是补充用例会归到自己所属子功能的那一段里，而
   不是堆在模块块尾部；同一子功能内部仍保持原有相对顺序。
3. 同一路径内再按**功能点**聚合：路径最后一级往往只到页面/区块（如「提交页」
   「统计概览」），真正的功能点（「现场照片」「本周走访」）写在标题正文里，光靠
   路径排不到一起。故在正文上做单向前移，见 _forward_place。
"""
import asyncio
import logging
import re
import sys
from datetime import timedelta

from sqlalchemy import select

from app.database import async_session
from app.models.test_case import TestCase

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("resort_batch")

# 判定「同一功能点」所需的正文共同前缀字数。取 3 有实测依据：在已落库批次上，真正同
# 功能点的用例对（本周走访…/逾期任务…/待走访…）共同前缀最少 3 字，而不该聚在一起的
# 跳转类用例对（「点击待走访跳转并筛选」⇔「点击逾期任务跳转并筛选」）最多 2 字，两者
# 可干净分开。放宽到子串匹配会把「点击/跳转/筛选」这类通用词也算成相似，反而误聚。
MIN_PREFIX = 3
# 正文开头的套话动词：功能点名紧跟其后，剥掉才能让共同前缀对齐到功能点本身。
_LEAD_VERB_RE = re.compile(r"^(验证|校验|确认|检查|测试)+")


def _title_segs(title: str) -> tuple[str, ...]:
    """标题【模块-子模块-...】→ 层级路径元组；没有【】的返回空元组（排到块内原位）。"""
    m = re.match(r"^【(.+?)】", title or "")
    return tuple(s.strip() for s in m.group(1).split("-")) if m else ()


def _func_desc(title: str) -> str:
    """取标题里【】之后的正文并剥掉开头套话动词，用于比对功能点。
    如「【A-B】验证本周走访显示户数」→「本周走访显示户数」。"""
    body = re.sub(r"^\s*【[^】]*】\s*", "", title or "").strip()
    return _LEAD_VERB_RE.sub("", body).strip()


def _common_prefix_len(a: str, b: str) -> int:
    """两段正文从头逐字比较，返回连续相同的字数（越长越可能是同一功能点）。"""
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def _forward_place(cases: list[TestCase]) -> list[TestCase]:
    """同一路径内按功能点聚合，只做**单向前移**：已排定的顺序永不改动，每条用例插到
    它前面共同前缀最长（且 >= MIN_PREFIX）那一簇的末尾；前面没有同功能点的就留在原位。

    单向是关键。双向重排（把整段按相似度重新串起来）会让总述型用例被挤到细则后面
    ——如「验证走访类型单选（4类）」跑到「走访类型为『日常走访』时提交成功」等 4 条
    之后。而总述天然先于细则出现，只允许后来者往前插，总述就不可能被移走。
    """
    if len(cases) < 2:
        return list(cases)
    descs = [_func_desc(c.title) for c in cases]
    out: list[int] = [0]  # 存 cases 的下标，保持已排定顺序
    for i in range(1, len(cases)):
        scores = [(_common_prefix_len(descs[i], descs[j]), pos) for pos, j in enumerate(out)]
        best = max(s for s, _ in scores)
        if best < MIN_PREFIX:
            out.append(i)  # 前面没有同功能点的用例，维持原有位置
            continue
        # 插到该簇最靠后的一条之后，使同功能点的多条用例连成一段
        out.insert(max(pos for s, pos in scores if s == best) + 1, i)
    return [cases[i] for i in out]


def _split_top_blocks(cases: list[TestCase]) -> list[list[TestCase]]:
    """按顶层模块切成连续块，保持块与块之间的原有先后。"""
    blocks: list[list[TestCase]] = []
    prev = object()
    for c in cases:
        top = _title_segs(c.title)[:1]
        if top != prev:
            blocks.append([c])
            prev = top
        else:
            blocks[-1].append(c)
    return blocks


def _resort_block(block: list[TestCase]) -> list[TestCase]:
    """块内层级化稳定排序：各级路径按其在块内的首次出现位置排。"""
    rank: dict[tuple[str, ...], int] = {}
    for i, c in enumerate(block):
        segs = _title_segs(c.title)
        for depth in range(1, len(segs) + 1):
            rank.setdefault(segs[:depth], i)

    def sort_key(item: tuple[int, TestCase]):
        i, c = item
        segs = _title_segs(c.title)
        # 逐级 rank + 原下标兜底：同一子功能内保持原相对顺序（稳定）
        return tuple(rank[segs[:depth]] for depth in range(1, len(segs) + 1)) + (i,)

    ordered = [c for _, c in sorted(enumerate(block), key=sort_key)]
    # 路径排完后，同一路径的用例已连成一段，段内再按正文功能点做单向前移聚合。
    out: list[TestCase] = []
    start = 0
    for i in range(1, len(ordered) + 1):
        if i == len(ordered) or _title_segs(ordered[i].title) != _title_segs(ordered[start].title):
            out.extend(_forward_place(ordered[start:i]))
            start = i
    return out


async def main(batch_id: str, dry_run: bool) -> None:
    async with async_session() as db:
        cases = (
            await db.execute(
                select(TestCase)
                .where(TestCase.batch_id == batch_id)
                .order_by(TestCase.created_at.asc(), TestCase.id.asc())
            )
        ).scalars().all()
        if not cases:
            logger.warning("未找到批次 %s 的任何用例", batch_id)
            return

        blocks = _split_top_blocks(cases)
        ordered = [c for b in blocks for c in _resort_block(b)]
        assert len(ordered) == len(cases) and {c.id for c in ordered} == {c.id for c in cases}

        moved = sum(1 for a, b in zip(cases, ordered) if a.id != b.id)
        logger.info(
            "批次 %s：%d 条用例，%d 个顶层模块块，%d 条位置变化",
            batch_id, len(cases), len(blocks), moved,
        )
        if dry_run:
            # 标出每条的原位置，便于核对「哪些被移动、移到了哪」——全量平铺打印上千行
            # 却看不出变化，等于没法验收。★ 标记位置有变化的条目。
            orig_pos = {c.id: i for i, c in enumerate(cases)}
            for i, c in enumerate(ordered):
                was = orig_pos[c.id]
                mark = f"  ← 原 {was}" if was != i else ""
                logger.info("%s%4d  %s%s", "★" if was != i else " ", i, c.title, mark)
            logger.info("dry-run，未写库：%d 条位置变化", moved)
            return
        if not moved:
            logger.info("顺序已正确，无需写库")
            return

        base = cases[0].created_at
        for i, c in enumerate(ordered):
            c.created_at = base + timedelta(seconds=i)
        await db.commit()
        logger.info("写库完成：created_at 自 %s 起逐条 +1 秒", base)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    if len(args) != 1:
        print("用法: python -m scripts.resort_batch <batch_id> [--dry-run]")
        sys.exit(1)
    asyncio.run(main(args[0], "--dry-run" in sys.argv[1:]))
