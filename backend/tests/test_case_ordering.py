"""用例排序规则的回归测试（app/utils/case_ordering.py）。

为什么专门给排序补测试：「只挪补充用例、原有用例位置一律不动」这个承诺**连漏了两次**
——#52 只把 is_movable 传到功能点层，路径层仍在全量重排；#53 修了路径层，但吸附力只比
公共前缀长度，分不出「路径相同」与「我是你的祖先」，总纲级补充被自己的细则隔开。两次都
靠人工追问才发现。故按「承诺」而非「函数」组织断言：每个 test 对应一条对用户的保证。

不连数据库、不调 LLM，纯内存排序，故用普通 pytest 函数即可。
"""
import pytest

from app.services.generator_service import _merge_supplements
from app.utils.case_ordering import order_cases

# ---------------------------------------------------------------- helpers

TITLE = lambda c: c["title"]  # noqa: E731
IS_SUPP = lambda c: c.get("origin") == "supplement"  # noqa: E731


def case(title: str) -> dict:
    """原有用例（锁定，排序不得改动其相对位置）。"""
    return {"title": title}


def supp(title: str) -> dict:
    """补充用例（可动，应归位到相关功能点旁）。"""
    return {"title": title, "origin": "supplement"}


def titles(cases: list[dict]) -> list[str]:
    return [c["title"] for c in cases]


def locked_titles(cases: list[dict]) -> list[str]:
    return [c["title"] for c in cases if not IS_SUPP(c)]


def gen_order(cases: list[dict]) -> list[dict]:
    """生成流程的排序（锁定原有用例）。"""
    return order_cases(cases, TITLE, IS_SUPP)


def batch_order(cases: list[dict]) -> list[dict]:
    """运维脚本 resort_batch 的排序（整批一起整理，不锁定）。"""
    return order_cases(cases, TITLE)


# ------------------------------------------------- 承诺一：原有用例位置一律不动

def test_零补充时原有用例一条都不动():
    """回归 #52：路径层曾是全量重排，交错的同路径用例会被并段。

    即便一条补充用例都没有，【登录】【注册】【登录】也会被排成 登录、登录、注册。
    """
    cases = [
        case("【模块-登录】记住密码"),
        case("【模块-注册】手机号校验"),
        case("【模块-登录】验证码错误"),
    ]
    assert titles(gen_order(cases)) == titles(cases)


def test_有补充时原有用例的相对顺序不变():
    cases = [
        case("【模块-登录】记住密码"),
        case("【模块-注册】手机号校验"),
        case("【模块-登录】验证码错误"),
    ]
    out = gen_order(cases + [supp("【模块-登录】密码错误锁定")])
    assert locked_titles(out) == titles(cases)


def test_顶层块的先后顺序不变():
    """顶层顺序来自需求切割的 modules 列表，是人给定的阅读顺序，不能按字母重排。"""
    cases = [
        case("【Z模块-页面】用例1"),
        case("【A模块-页面】用例2"),
        case("【M模块-页面】用例3"),
    ]
    out = gen_order(cases + [supp("【A模块-页面】补充")])
    assert [t.split("-")[0] for t in locked_titles(out)] == ["【Z模块", "【A模块", "【M模块"]


# ------------------------------------------------- 承诺二：补充用例归位且不造成倒置

def test_补充用例归到所属子功能那一段():
    cases = [
        case("【模块-登录】记住密码"),
        case("【模块-注册】手机号校验"),
    ]
    out = gen_order(cases + [supp("【模块-登录】验证码错误")])
    # 补充应紧跟同路径的「登录」之后，而不是落到末尾
    assert titles(out) == [
        "【模块-登录】记住密码",
        "【模块-登录】验证码错误",
        "【模块-注册】手机号校验",
    ]


def test_总纲级补充不被自己的细则隔开():
    """回归 #53：吸附力曾只比公共前缀长度，分不出「同级」与「后代」。

    总纲【提交页】与细则【提交页-日常走访】对一条【提交页】补充的公共层数都是 2，
    同分取更靠后 → 补充被推到细则之后，两条同级总纲被细则隔开。
    """
    cases = [
        case("【走访-提交页】验证走访类型单选（4类）"),
        case("【走访-提交页-日常走访】提交成功"),
        case("【走访-提交页-日常走访】必填校验"),
    ]
    out = gen_order(cases + [supp("【走访-提交页】验证提交按钮置灰规则")])
    assert titles(out) == [
        "【走访-提交页】验证走访类型单选（4类）",
        "【走访-提交页】验证提交按钮置灰规则",  # 紧跟同级总纲
        "【走访-提交页-日常走访】提交成功",
        "【走访-提交页-日常走访】必填校验",
    ]


def test_细则级补充仍归到细则末尾():
    """上一条的对照：压低后代只影响同级补充，细则补充不该被推到总纲旁。"""
    cases = [
        case("【走访-提交页】验证走访类型单选（4类）"),
        case("【走访-提交页-日常走访】提交成功"),
        case("【走访-提交页-日常走访】必填校验"),
    ]
    out = gen_order(cases + [supp("【走访-提交页-日常走访】重复提交")])
    assert titles(out)[-1] == "【走访-提交页-日常走访】重复提交"


def test_正文层的总述不被细则挤到后面():
    """第 3 层单向前移的初衷（v0.18）：总述天然先于细则出现，只允许后来者往前插。"""
    cases = [
        case("【走访-提交页】验证走访类型单选（4类）"),
        case("【走访-提交页】走访类型为「日常走访」时提交成功"),
        case("【走访-提交页】走访类型为「专项走访」时提交成功"),
    ]
    out = gen_order(cases + [supp("【走访-提交页】走访类型为「临时走访」时提交成功")])
    assert out[0]["title"] == "【走访-提交页】验证走访类型单选（4类）"


# ------------------------------------------------- 承诺三：边界与健壮性

@pytest.mark.parametrize("supp_title, why", [
    ("【全新顶层-新功能】全新模块的补充", "顶层都对不上，无处可归"),
    ("没有【】前缀的补充用例", "取不到层级路径"),
])
def test_无处归位的补充追加到末尾而不丢失(supp_title, why):
    cases = [case("【模块-登录】记住密码")]
    out = gen_order(cases + [supp(supp_title)])
    assert titles(out) == ["【模块-登录】记住密码", supp_title], why


def test_补充用例出现在所属簇之前也能归位():
    """_merge_supplements 若把补充插到子模块首条之前，排序仍应把它收进簇里。"""
    cases = [
        supp("【模块-注册】补充的注册项"),
        case("【模块-登录】记住密码"),
        case("【模块-注册】手机号校验"),
    ]
    out = gen_order(cases)
    assert titles(out) == [
        "【模块-登录】记住密码",
        "【模块-注册】手机号校验",
        "【模块-注册】补充的注册项",
    ]


def test_排序不增不减不改用例():
    cases = [
        case("【模块-登录】记住密码"),
        case("【模块-注册】手机号校验"),
        supp("【模块-登录】验证码错误"),
    ]
    out = gen_order(cases)
    assert sorted(titles(out)) == sorted(titles(cases))
    assert all(c in cases for c in out)  # 同一批 dict 对象，未复制或改写


def test_排序幂等():
    """落库即最终顺序，重复排序不该再动——否则生成页与历史页会不一致。"""
    cases = [
        case("【模块-登录】记住密码"),
        case("【模块-注册】手机号校验"),
        supp("【模块-登录】验证码错误"),
        supp("【模块-注册】密码强度"),
    ]
    once = gen_order(cases)
    assert titles(gen_order(once)) == titles(once)


@pytest.mark.parametrize("cases", [[], [case("【模块-页面】只有一条")]], ids=["空", "单条"])
def test_空列表与单条不报错(cases):
    assert titles(gen_order(cases)) == titles(cases)


# ------------------------------------------------- 承诺四：运维脚本的整批模式语义不变

def test_整批模式会重排原有用例():
    """与生成流程相反：不传 is_movable 时整批一起整理，交错路径应被并段。

    这是 resort_batch.py 补排历史批次的语义，#53 的重构必须保住它。
    """
    cases = [
        case("【模块-登录】记住密码"),
        case("【模块-注册】手机号校验"),
        case("【模块-登录】验证码错误"),
    ]
    assert titles(batch_order(cases)) == [
        "【模块-登录】记住密码",
        "【模块-登录】验证码错误",  # 被并到同路径簇里
        "【模块-注册】手机号校验",
    ]


def test_整批模式也幂等():
    cases = [
        case("【模块-登录】记住密码"),
        case("【模块-注册】手机号校验"),
        case("【模块-登录】验证码错误"),
    ]
    once = batch_order(cases)
    assert titles(batch_order(once)) == titles(once)


# ------------------------------------------------- 与 _merge_supplements 的集成

def test_经过补充合并后的完整链路():
    """生成流程实际是 _merge_supplements 再 order_cases，两步合起来才是最终顺序。"""
    kept = [
        case("【PC工作台-统计概览】验证问候语显示网格员姓名"),
        case("【PC工作台-统计概览】验证本周走访显示户数"),
        case("【PC端我的任务-状态筛选】验证默认全部"),
    ]
    supplements = [supp("【PC工作台-统计概览】验证本周走访无数据时显示0户")]
    out = gen_order(_merge_supplements(kept, supplements))

    assert locked_titles(out) == titles(kept), "原有用例顺序不变"
    idx = titles(out).index("【PC工作台-统计概览】验证本周走访无数据时显示0户")
    # 应落在同功能点「本周走访」之后，而不是跑到另一个顶层模块里
    assert out[idx - 1]["title"] == "【PC工作台-统计概览】验证本周走访显示户数"
