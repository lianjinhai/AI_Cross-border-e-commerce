"""合规关键词表的双向不变量（数据驱动，2026-10 QA 补充）。

为什么要有这个文件
------------------
关键词表的历史证明：**「漏词」与「过宽」是同一种病的两种症状**，而且修复其中
一种很容易制造另一种：

- ``5f68c5d`` 修了 FCC 的「漏词」（充电器/ adapter 不再漏检），但
  ``applies_to`` 里留着 2 字母的裸 ``"rf"``——过宽的一侧没人量过；
- 同一次修复补了 ``"usb-c"`` / ``"usb c"``，却漏了裸 ``"usb"``——**修漏词时
  又造了一个漏词**，于是「便携宠物饮水机 USB」放行、「便携榨汁杯 USB充电」被拦，
  差别只在标题有没有「充电」二字。

只测「该拦的有没有拦」是不够的：**放行不会让任何断言失败**，所以漏词方向天然隐形。
只测「不该拦的有没有放过」也不够：**拦截同样会写绿灯**。两个方向必须同时钉住。

唯一的硬约束：直接调 ``check_evidence``，**绝不自己拼 haystack**
----------------------------------------------------------------
2026-10 的一次真实教训：有人（包括我自己）用「完整 attrs JSON 拼字符串」的方式
模拟匹配，凭空得出「针织围巾被要求 FCC」的结论并上报；而生产代码只读
``category + title + attrs["source_desc"]`` 三个字段，``title_en`` 根本不参与匹配，
于是那条「缺陷」在真实数据上并不存在。**自己复刻匹配逻辑 = 测一个不存在的生产
路径**，比不测更危险，因为它能凭空造出一个看似严谨的假结论。

因此本文件的所有断言：
1. 一律通过 ``compliance_registry.check_evidence`` 走真实代码路径；
2. stub 只提供 ``id`` / ``category`` / ``title`` / ``attrs={'source_desc': ...}``；
3. 任何新增的被测字段若改变匹配结果，用例会立刻变红，而不是静默测一个假场景。

四层分类
--------
``TestMustBlock``    有源电子（充电/发热/发光/电动）—— 必须要求认证；
``TestMustPass``     无源被动（支架/挂钩/纯机械/纯纺织）—— 必须放行，FCC 不适用；
``TestLatentMine``   潜伏地雷—— 英文 ``source_desc`` 不得被 2 字母词误伤；
``TestUndecided``    边界样本—— ``xfail`` + 注明待法务确认，不阻塞 CI。

隔离：自建内存库 + 独立 Tenant，不读业务主库``erp.db``。
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Product, Tenant
from app.services import compliance_registry

ELECTRICAL = ("FCC", "CE", "UKCA", "KC", "PSE")
"""电气安全类认证：补 ``usb`` 只应影响这些（与工程师补丁范围一致）。"""

# 绝不该被 USB 牵连的认证：电池运输/儿童/食品/医疗。
# 补``usb`` 时若误加到这些表上，凭空制造合规债务（工程师已踩过一次）。
UNRELATED = ("UN38.3", "CPC", "FDA")


@pytest.fixture
def env():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(name="QA 关键词表探针")
        db.add(tenant)
        db.flush()
        yield db, tenant.id


def _probe(db, tenant_id, *, category, title, source_desc=None, country="US",
           tag="case"):
    """构造最小 stub 并**直调 check_evidence** 返回 required 认证名列表。

    只提供 ``id`` / ``category`` / ``title`` / ``attrs``，其余字段一律不给——
    这样若生产代码将来改变匹配字段（例如开始读 ``title_en``），用例会立刻失败。
    """
    attrs = {} if source_desc is None else {"source_desc": source_desc}
    product = Product(tenant_id=tenant_id, sku=f"SKU-{tag}", status="active",
                      category=category, title=title, images=[], attrs=attrs)
    db.add(product)
    db.flush()
    report = compliance_registry.check_evidence(db, tenant_id, product, country)
    names = [item["requirement"] for item in report["required"]]
    db.delete(product)
    db.flush()
    return names


# ====================================================================== 必须拦
class TestMustBlock:
    """有源电子：必须要求目的国强制认证。这层是本轮修复的主战场。"""

    @pytest.mark.parametrize("country,requirement", [
        ("US", "FCC"), ("EU", "CE"), ("GB", "UKCA"), ("JP", "PSE"), ("KR", "KC"),
    ])
    def test_charger_requires_electrical_cert_in_every_market(
            self, env, country, requirement):
        """SKU-46048 同款充电器：五大市场都必须命中电气安全认证。"""
        db, tenant_id = env
        names = _probe(db, tenant_id, category="3C配件",
                       title="65W 氮化镓快充充电器", country=country, tag="charger")
        assert requirement in names, f"{country} 站应要求 {requirement}，实际 {names}"

    def test_wireless_charging_stand_is_blocked(self, env):
        """无线充电支架：有源（无线发射），必须拦。"""
        db, tenant_id = env
        names = _probe(db, tenant_id, category="3C配件",
                       title="无线桌面充电支架", tag="wireless-stand")
        assert "FCC" in names, names

    @pytest.mark.parametrize("title,note", [
        ("便携榨汁杯 USB充电", "标题含「充电」"),
        ("便携宠物饮水机 USB", "**仅** USB，无「充电」—— 本轮待修的漏词"),
    ])
    def test_usb_powered_appliance_consistently_blocked(self, env, title, note):
        """同类 USB 有源件必须**一致**判定。

        这条是``bare usb`` 漏词的直接回归锁：修复前「榨汁杯 USB充电」被拦、
        「饮水机 USB」放行，差别只在标题措辞——同一种商品两种判法。
        """
        db, tenant_id = env
        category = "厨房用品" if "榨汁" in title else "宠物用品"
        names = _probe(db, tenant_id, category=category, title=title,
                       tag=f"usb-{abs(hash(title)) % 10000}")
        assert "FCC" in names, f"{note}：应要求 FCC，实际 {names}"


# ====================================================================== 必须放行
class TestMustPass:
    """无源被动件：**必须放行**。

    这一层此前完全没有测试保护，导致我把「合规豁免」误读成「覆盖盲区」
    （磁吸支架无电路无射频，FCC Part 15B 本就不适用）。放行在这里是**正确行为**，
    必须钉住，否则将来有人为了「覆盖更全」收紧关键词表时会把无源件误伤。
    """

    @pytest.mark.parametrize("category,title,tag", [
        ("3C配件", "磁吸式手机车载支架", "magnetic-holder"),
        ("家居", "浴室置物架免打孔", "shelf"),
        ("家居", "落地床头小夜灯 触摸调光", "lamp-alive"),
    ])
    def test_source_less_passive_goods_must_not_require_fcc(self, env, category,
                                                            title, tag):
        """无源/纯机械/纯纺织件不得被要求 FCC。

        注意 ``小夜灯`` 放行仅在**当前数据**下成立（它可能是有源的），
        故与 ``TestUndecided`` 中的同类样本保持一致：一旦法务认定需拦截，
        改 ``TestUndecided`` 的 xfail 即可，不会与本用例互相打架。
        """
        db, tenant_id = env
        names = _probe(db, tenant_id, category=category, title=title, tag=tag)
        assert "FCC" not in names, f"{title}（{category}）不该要求 FCC，实际 {names}"


# ================================================================== 潜伏地雷
class TestLatentMine:
    """英文 ``source_desc`` 不得被 2 字母关键词误伤。

    背景：``applies_to`` 里的裸 ``"rf"``（射频缩写）会命中 ``sca-rf``、``pe-rf-ume``。
    现状是**潜伏地雷**而非现行缺陷——业务主库 53 个商品的 ``source_desc``
    全为 ``None``，所以围巾并不会真的被要求 FCC。但只要有一天运营填入英文
    ``source_desc``（跨境商品常见），围巾/香水就会被误判成需要 FCC。

    这条断言锁住「拆弹」这个动作：删掉裸 ``rf``、换成明确的射频词。
    """

    @pytest.mark.parametrize("source_desc,note", [
        ("Thick Knit Winter Scarf", "围巾含 sca-rf"),
        ("Perfume Gift Set", "香水含 pe-rf-ume"),
        ("Silk Scarf", "真丝围巾"),
    ])
    def test_english_source_desc_must_not_trigger_fcc(self, env, source_desc, note):
        db, tenant_id = env
        names = _probe(db, tenant_id, category="服饰配件", title="围巾/香水",
                       source_desc=source_desc, tag=f"mine-{abs(hash(source_desc)) % 9999}")
        assert "FCC" not in names, (
            f"{note}：英文 source_desc 不应触发 FCC，实际 {names}。"
            "裸 2 字母关键词（rf）必须替换为明确射频词。")

    def test_genuine_radio_term_still_blocked(self, env):
        """反向保护：拆 ``rf`` 不能把**真正的射频商品**一起放掉。"""
        db, tenant_id = env
        names = _probe(db, tenant_id, category="3C配件", title="蓝牙耳机",
                       source_desc="Bluetooth Wireless Earbuds", tag="bt-earbud")
        assert "FCC" in names, f"蓝牙耳机应要求 FCC，实际 {names}"


# ====================================================================== 待定
class TestUndecided:
    """边界样本：有源但类目模糊，待法务确认。

    用 ``xfail(strict=False)`` 登记当前实际行为——**这不是期待它们通过**，
    而是让「待定」这件事在测试里可见、可追踪。法务给出结论后，
    改``expected`` 即可转为硬断言。
    """

    # 实测当前行为：这些有源件因关键词表未覆盖而放行。
    @pytest.mark.xfail(strict=False, reason="待法务确认：Part 15B 适用范围未决")
    @pytest.mark.parametrize("category,title,expected", [
        ("家居", "落地床头小夜灯 触摸调光", ["FCC"]),
        ("母婴用品", "湿巾加热器车载", ["FCC"]),
        ("宠物用品", "便携宠物饮水机 USB", ["FCC"]),
    ])
    def test_pending_active_products_await_legal(self, env, category, title, expected):
        db, tenant_id = env
        names = _probe(db, tenant_id, category=category, title=title,
                       tag=f"pending-{abs(hash(title)) % 9999}")
        assert names == expected, f"{title}：待法务确认，当前 {names}"


# ============================================================ 补丁边界防回归
class TestUsbPatchScope:
    """锁定「补 ``usb`` 只影响电气安全类」的补丁范围。

    工程师的补丁初版给**所有**认证项补了 ``usb``，实测会让任何带 USB 的商品
    被要求儿童产品证书 / FDA 注册 / 电池运输报告——**一个漏词补丁变成三个新的
    凭空债务**。这组断言防止该范围再次被扩大。
    """

    @pytest.mark.parametrize("requirement", sorted(UNRELATED))
    def test_usb_must_not_pull_in_unrelated_certificates(self, env, requirement):
        """USB 类商品不得因本次补丁被要求电池/儿童/食品/医疗认证。"""
        db, tenant_id = env
        country = {"UN38.3": "US", "CPC": "US", "FDA": "US"}[requirement]
        names = _probe(db, tenant_id, category="厨房用品",
                       title="便携榨汁杯 USB充电", country=country, tag="scope")
        assert requirement not in names, (
            f"补 usb 不应牵连 {requirement}，实际 {names}——凭空制造合规债务。")

    @pytest.mark.parametrize("requirement,country", [
        ("FCC", "US"), ("CE", "EU"), ("UKCA", "GB"), ("KC", "KR"), ("PSE", "JP"),
    ])
    def test_usb_may_still_trigger_electrical_certs(self, env, requirement, country):
        """反向边界：电气安全类**应当**会因 USB 命中（补丁生效的正向证据）。"""
        db, tenant_id = env
        names = _probe(db, tenant_id, category="厨房用品",
                       title="便携榨汁杯 USB充电", country=country, tag="elec")
        if requirement in ELECTRICAL:
            assert requirement in names, (
                f"{country} 站的 {requirement} 应因 USB 命中，实际 {names}")
