"""地区归一化：国家/地区代码的唯一口径（关税、物流、合规共用一份）。

为什么单独成模块：目的国在系统里出现多次（商品、订单、关税税率、物流路由、
合规档案），而同一目的地在不同业务口径下的"判定单元"不同——例如德国 (DE) 在
关税与合规上按**欧盟**规则判定（(EU) 2026/382 的 €3/件是欧盟口径），但在物流
路由上也可能需要按成员国单独维护。把所有归一化规则收在一处，避免每个服务
各写一份别名表，最终互相漂移。
"""
from __future__ import annotations

# 欧盟成员国（ISO 3166-1 alpha-2）
EU_MEMBER_STATES = frozenset({
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU",
    "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
})

# 常用别名 → ISO 代码（订单/商品里 country 字段口径不统一，先归一化）
COUNTRY_ALIASES = {
    "USA": "US", "UNITED STATES": "US", "AMERICA": "US", "美国": "US",
    "UK": "GB", "UNITED KINGDOM": "GB", "BRITAIN": "GB", "ENGLAND": "GB", "英国": "GB",
    "GERMANY": "DE", "DEUTSCHLAND": "DE", "德国": "DE",
    "FRANCE": "FR", "法国": "FR", "ITALY": "IT", "意大利": "IT", "SPAIN": "ES", "西班牙": "ES",
    "NETHERLANDS": "NL", "荷兰": "NL", "POLAND": "PL", "波兰": "PL",
    "EU": "EU", "EUROPE": "EU", "欧盟": "EU", "EUROPEAN UNION": "EU",
    "JAPAN": "JP", "日本": "JP", "KOREA": "KR", "SOUTH KOREA": "KR", "韩国": "KR",
    "SINGAPORE": "SG", "新加坡": "SG", "MALAYSIA": "MY", "马来西亚": "MY",
    "THAILAND": "TH", "泰国": "TH", "VIETNAM": "VN", "越南": "VN",
    "INDONESIA": "ID", "印尼": "ID", "PHILIPPINES": "PH", "菲律宾": "PH",
    "BRAZIL": "BR", "巴西": "BR", "MEXICO": "MX", "墨西哥": "MX",
    "AUSTRALIA": "AU", "澳大利亚": "AU", "CANADA": "CA", "加拿大": "CA",
    "CHINA": "CN", "中国": "CN",
}


def normalize_country(country: str) -> str:
    """把 country 字段归一化为 ISO 代码；空值返回空串（不猜目的地）。"""
    value = (country or "").strip().upper()
    if not value:
        return ""
    return COUNTRY_ALIASES.get(value, value)


def region_code(country: str) -> str:
    """业务判定单元：欧盟成员国统一归为 EU，其余为归一化 ISO 代码。"""
    code = normalize_country(country)
    return "EU" if code in EU_MEMBER_STATES else code
