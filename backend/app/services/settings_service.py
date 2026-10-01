"""配置作用域服务（P1-10）：租户级配置的唯一读写入口。

三级读取回退（租户覆盖优先，其次平台默认，最后代码默认）：
    tenant_settings(tenant_id, key)
        ↓ 不存在
    settings(key)          ← 平台默认值，由平台服务商维护
        ↓ 不存在
    代码内 _DEFAULTS

写入按 key 分流：
    PLATFORM_KEYS（llm / 1688_api）→ settings 表，仅平台服务商可写
    TENANT_KEYS  （platform_fees / fx / rules）→ tenant_settings，租户管理员可写

为什么需要本模块：settings 表主键只有 key，没有租户维度。若租户管理员直接写
全局 key，会污染其他所有租户的定价与利润计算（跨租户写入漏洞，见
docs/phase1_setting_scope_design.md 第 1 节）。
"""
from sqlalchemy.orm import Session

from ..models import Setting, TenantSetting, utcnow

# 平台级配置：全局唯一，仅平台服务商（superadmin）可写
PLATFORM_KEYS = frozenset({"llm", "1688_api"})

# 租户级配置：每个租户独立可覆盖
TENANT_KEYS = frozenset({"platform_fees", "fx", "rules"})

# 代码内兜底默认值（与 services/costing.py 的 DEFAULT_RULES 保持一致）
DEFAULTS: dict[str, dict] = {
    "platform_fees": {"shopee": 0.06, "amazon": 0.15, "shopify": 0.02,
                      "ebay": 0.12, "temu": 0.05, "tiktok": 0.08},
    "fx": {"USD": 7.12, "EUR": 7.8},
    # D58：新增跨境成本项默认 0（未配置即不计入），避免改变既有利润口径；
    # 启用示例：{"payment_fee_rate": 0.01, "refund_rate": 0.05, "tax_rebate_rate": 0.13}
    "rules": {"min_margin": 0.15, "target_margin": 0.35,
              "logistics_base": 18.0, "logistics_per_kg": 8.0, "ads_default": 1.5,
              "payment_fee_rate": 0.0, "refund_rate": 0.0, "tax_rebate_rate": 0.0,
              "vat_in_rate": 0.13, "clearance_fee_cny": 12.0,
              "landed_cost_include_vat": True, "destination_compliance_enforce": False},
}


def _merge(base: dict, override) -> dict:
    merged = dict(base)
    if isinstance(override, dict):
        merged.update(override)
    return merged


def get_setting(db: Session, tenant_id: int | None, key: str) -> dict:
    """按三级回退读取配置，返回完整字典（已与默认值合并）。

    tenant_id 为 None（平台身份）时跳过租户级，直接读平台级。
    """
    base = DEFAULTS.get(key, {})
    if tenant_id is not None:
        row = (db.query(TenantSetting)
               .filter(TenantSetting.tenant_id == tenant_id, TenantSetting.key == key)
               .first())
        if row is not None:
            return _merge(base, row.value)
    platform_row = db.get(Setting, key)
    if platform_row is not None:
        return _merge(base, platform_row.value)
    return dict(base)


def get_setting_source(db: Session, tenant_id: int | None, key: str) -> str:
    """返回配置来源：tenant / platform / default（供排障与审计使用）。"""
    if tenant_id is not None:
        row = (db.query(TenantSetting)
               .filter(TenantSetting.tenant_id == tenant_id, TenantSetting.key == key)
               .first())
        if row is not None:
            return "tenant"
    return "platform" if db.get(Setting, key) is not None else "default"


def set_tenant_setting(db: Session, tenant_id: int, key: str, value: dict) -> dict:
    """写入租户级配置（与已有值合并）。调用方必须已完成权限校验。"""
    if key not in TENANT_KEYS:
        raise ValueError(f"{key} 不是租户级配置，禁止写入 tenant_settings")
    row = (db.query(TenantSetting)
           .filter(TenantSetting.tenant_id == tenant_id, TenantSetting.key == key)
           .first())
    if row is None:
        row = TenantSetting(tenant_id=tenant_id, key=key,
                            value=_merge(DEFAULTS.get(key, {}), value))
        db.add(row)
    else:
        row.value = _merge(row.value or {}, value)
        row.updated_at = utcnow()
    return row.value


def set_platform_setting(db: Session, key: str, value: dict) -> dict:
    """写入平台级配置（与已有值合并）。调用方必须已完成权限校验。"""
    if key not in PLATFORM_KEYS:
        raise ValueError(f"{key} 不是平台级配置，禁止写入 settings")
    row = db.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=_merge(DEFAULTS.get(key, {}), value))
        db.add(row)
    else:
        row.value = _merge(row.value or {}, value)
    return row.value


def set_platform_default(db: Session, key: str, value: dict) -> dict:
    """平台服务商改写「平台默认值」（写入 settings 表，供租户未覆盖时回退）。

    与 set_platform_setting 的区别：本函数允许 TENANT_KEYS，因为平台服务商需要
    为所有租户设定基准值（例如统一调整平台佣金费率）。租户级覆盖在
    tenant_settings 中，优先级高于此处的平台默认值。
    """
    if key not in PLATFORM_KEYS and key not in TENANT_KEYS:
        raise ValueError(f"{key} 不是已知配置项，禁止写入 settings")
    row = db.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=_merge(DEFAULTS.get(key, {}), value))
        db.add(row)
    else:
        row.value = _merge(row.value or {}, value)
    return row.value
