"""清理已入库用例中 expected_result 开头残留的步骤号。

用法：
    cd backend
    python scripts/clean_expected_step_no.py           # 预演，只打印将要改动的内容
    python scripts/clean_expected_step_no.py --apply   # 实际写入

背景：提示词的 C 档（多步流程型）要求「预期用相同编号引用对应步骤」，模型在
只有一条预期时也照编号写了（如步骤 4 对应 `4. 提示"密码修改成功"`）。这个前缀
没有对应关系可表达，属于噪音。提示词已补充约束，本脚本用于回洗历史数据。

只处理「通篇仅一个编号」的情况；预期本身分条编号的（1. …  2. …）编号承载
「哪一步对应哪条预期」，去掉会丢信息，一律不动。
"""

import argparse
import re
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "testcase_platform.db"

# 预期开头的步骤号：1. / 2、 / 3)
LEAD_NO_RE = re.compile(r"^\s*\d{1,2}[.、)]\s*")

# 全文枚举号计数。前面不紧跟数字或小数点、后面不紧跟数字，
# 以排除 3.5（小数）、135****1234（脱敏号）、网格1（编号后缀）这类误判。
ENUM_NO_RE = re.compile(r"(?<![0-9.])\d{1,2}[.、)](?![0-9])")


def strip_leading_step_no(expected: str) -> str:
    """剥离预期结果开头的残留步骤号；分条预期原样返回。"""
    if not expected or not LEAD_NO_RE.match(expected):
        return expected
    # 两个及以上编号说明预期本身按步骤分条，编号有意义，不能动。
    if len(ENUM_NO_RE.findall(expected)) > 1:
        return expected
    return LEAD_NO_RE.sub("", expected, count=1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="真正写入数据库；不加只做预演")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"数据库不存在: {DB_PATH}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, title, expected_result FROM test_cases WHERE expected_result IS NOT NULL")

    changes = []
    for cid, title, exp in cur.fetchall():
        cleaned = strip_leading_step_no(exp)
        if cleaned != exp:
            changes.append((cid, title, exp, cleaned))

    if not changes:
        print("没有需要清理的用例，退出。")
        return 0

    print(f"共 {len(changes)} 条待清理：\n")
    for _cid, title, exp, cleaned in changes:
        print(f"  {title}")
        print(f"    - {exp}")
        print(f"    + {cleaned}\n")

    if not args.apply:
        print("[预演模式] 未写入。加 --apply 真正落库。")
        return 0

    # 带上原值做条件，避免与并发编辑互相覆盖。
    updated = 0
    for cid, _title, exp, cleaned in changes:
        cur.execute(
            "UPDATE test_cases SET expected_result = ? WHERE id = ? AND expected_result = ?",
            (cleaned, cid, exp),
        )
        updated += cur.rowcount
    conn.commit()
    print(f"已更新 {updated} 条。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
