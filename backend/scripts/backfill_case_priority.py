"""为历史缺失 priority 的用例按标题关键词回填 P0/P1/P2。

用法：
    cd backend
    python scripts/backfill_case_priority.py           # 预演，只统计分档不落库
    python scripts/backfill_case_priority.py --apply   # 实际写入

分档规则按覆盖优先级从高到低匹配：
- P0：安全、并发、必填、核心提交（一旦漏测直接影响数据完整或安全）
- P2：纯展示、只读、UI 徽标、分页/折叠等边缘交互
- P1：其它（正向流程、筛选、搜索、编辑等主流业务）

只会更新 priority IS NULL 或空串的记录，已有等级的不覆盖。
"""

import argparse
import sqlite3
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "testcase_platform.db"


# 分档规则：(等级, 关键词列表)。按顺序匹配，先命中的优先。
# 放在最前的是"强信号"（安全/并发/破坏性），最后兜底 P1。
RULES: list[tuple[str, list[str]]] = [
    ("P0", [
        # 安全类
        "SQL注入", "SQL 注入", "XSS", "注入攻击", "越权",
        # 并发/数据完整
        "并发冲突", "并发", "重复提交",
        # 关键提交/建档动作
        "生成流水号", "完成建档", "保存后写入", "同步冲突",
        # 必填字段（缺失直接阻塞业务）
        "必填",
        # 特殊字符类反向用例
        "特殊字符", "Emoji", "emoji",
    ]),
    ("P2", [
        # 纯只读/展示
        "只读", "只读无编辑", "无编辑入口", "查看态", "显示正确", "显示最近",
        # UI 细节
        "徽标", "编辑态标题", "编辑态取消", "编辑态底部按钮", "查看态底部按钮",
        "折叠", "展开", "占位", "提示条", "橙标",
        # 分页/排序等边缘操作
        "分页", "每页条数", "跳转正确", "网格选择器",
        # 空态/提示
        "无社会关系提示", "暂无提示",
    ]),
]


def classify(title: str) -> str:
    """按 RULES 顺序匹配，返回 P0/P1/P2。未命中兜底 P1。"""
    if not title:
        return "P1"
    for level, keywords in RULES:
        for kw in keywords:
            if kw in title:
                return level
    return "P1"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="真正写入数据库；不加只做预演")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"数据库不存在: {DB_PATH}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT id, title FROM test_cases WHERE priority IS NULL OR priority = ''")
    rows = cur.fetchall()
    if not rows:
        print("没有需要补齐的用例，退出。")
        return 0

    plan: dict[str, list[tuple[str, str]]] = {"P0": [], "P1": [], "P2": []}
    for cid, title in rows:
        level = classify(title)
        plan[level].append((cid, title))

    print(f"共 {len(rows)} 条待补齐：")
    for level in ("P0", "P1", "P2"):
        items = plan[level]
        print(f"  {level}: {len(items)} 条")
        # 每档抽 3 条样例便于人工验证分档合理性
        for cid, title in items[:3]:
            print(f"    - {title}")
        if len(items) > 3:
            print(f"    ...（省略 {len(items) - 3} 条）")

    if not args.apply:
        print("\n[预演模式] 未写入。加 --apply 真正落库。")
        return 0

    # 落库：只更新 priority 仍为空的记录，避免与并发新写入冲突
    updated = 0
    for level, items in plan.items():
        for cid, _title in items:
            cur.execute(
                "UPDATE test_cases SET priority = ? WHERE id = ? AND (priority IS NULL OR priority = '')",
                (level, cid),
            )
            updated += cur.rowcount
    conn.commit()
    print(f"\n已更新 {updated} 条。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
