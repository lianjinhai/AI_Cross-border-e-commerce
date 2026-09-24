"""模拟市场数据服务：模拟 1688 采集 / 订单生成（真实部署时替换为平台 OpenAPI/爬虫适配器）。"""
import random
from datetime import datetime, timedelta

from ..models import Order, Product
from ..serialize import to_dict

# 40 个模板商品：模拟 1688 货源池
PRODUCT_TEMPLATES = [
    ("LED 灯带智能变色 5米装", "LED Strip Lights RGB 5m", "家居", 0.35, "PVC", "彩色", 2, 9.9, 15.99),
    ("北欧简约收纳盒三件套", "Nordic Storage Box Set of 3", "家居", 1.2, "PP", "白色", 10, 12.5, 22.99),
    ("落地床头小夜灯 触摸调光", "Touch Bedside Lamp Dimmable", "家居", 0.6, "ABS", "暖白", 5, 15.8, 26.99),
    ("真空压缩收纳袋 8件套", "Vacuum Storage Bags 8 Pack", "家居", 0.9, "PA+PE", "透明", 20, 11.2, 19.99),
    ("磁吸式手机车载支架", "Magnetic Car Phone Holder", "3C配件", 0.12, "锌合金", "黑色", 50, 4.2, 9.99),
    ("65W 氮化镓快充充电器", "65W GaN Fast Charger", "3C配件", 0.15, "PC", "黑色", 30, 28.0, 45.99),
    ("蓝牙耳机保护套 硅胶", "Silicone Earbuds Case Cover", "3C配件", 0.03, "硅胶", "多彩", 100, 1.8, 5.99),
    ("三合一伸缩数据线", "3-in-1 Retractable Charging Cable", "3C配件", 0.08, "TPE", "黑色", 100, 3.5, 8.99),
    ("宠物梳毛手套 脱毛神器", "Pet Grooming Gloves Deshedding", "宠物用品", 0.1, "涤纶", "绿色", 50, 3.2, 8.99),
    ("狗狗降温冰垫 夏季", "Dog Cooling Mat Summer", "宠物用品", 0.8, "冷感纤维", "蓝色", 20, 14.5, 24.99),
    ("猫咪逗猫棒电动套装", "Electric Cat Teaser Toy Set", "宠物用品", 0.15, "ABS", "粉色", 40, 5.6, 12.99),
    ("便携宠物饮水机 USB", "USB Pet Water Fountain", "宠物用品", 0.5, "PP", "白色", 20, 12.0, 21.99),
    ("加厚防滑瑜伽垫 8mm", "Thick Non-slip Yoga Mat 8mm", "户外运动", 1.1, "TPE", "紫色", 15, 19.9, 32.99),
    ("户外露营充电灯笼", "Rechargeable Camping Lantern", "户外运动", 0.4, "ABS", "军绿", 30, 10.5, 18.99),
    ("折叠便携登山杖铝合金", "Folding Trekking Poles Aluminum", "户外运动", 0.55, "铝合金", "黑色", 20, 22.0, 36.99),
    ("运动水壶不锈钢1000ml", "Stainless Steel Sport Bottle 1L", "户外运动", 0.45, "304不锈钢", "银色", 30, 13.5, 22.99),
    ("可洗化妆棉套装 16片", "Reusable Makeup Remover Pads 16pcs", "美妆工具", 0.12, "竹纤维", "白色", 100, 3.8, 9.99),
    ("指甲油胶美甲套装", "Gel Nail Polish Starter Kit", "美妆工具", 0.6, "树脂", "多色", 20, 16.8, 27.99),
    ("鲨鱼夹发抓 大号", "Large Hair Claw Clips", "美妆工具", 0.06, "醋酸纤维素", "豹纹", 200, 2.1, 6.99),
    ("电动洁面仪硅胶", "Silicone Facial Cleansing Brush", "美妆工具", 0.18, "硅胶", "粉色", 50, 7.5, 14.99),
    ("婴儿围兜防水硅胶", "Waterproof Silicone Baby Bibs", "母婴用品", 0.09, "食品级硅胶", "马卡龙", 100, 2.8, 7.99),
    ("宝宝辅食研磨碗套装", "Baby Food Grinder Bowl Set", "母婴用品", 0.5, "PP", "蓝色", 40, 9.9, 17.99),
    ("儿童防走失背包", "Toddler Anti-lost Backpack", "母婴用品", 0.3, "涤纶", "卡通", 50, 8.8, 16.99),
    ("一次性围兜便携 20片", "Disposable Baby Bibs 20pcs", "母婴用品", 0.15, "无纺布", "白色", 200, 3.9, 8.49),
    ("厨房抽屉分隔收纳架", "Kitchen Drawer Organizer Tray", "厨房用品", 0.7, "PP", "白色", 30, 8.5, 15.99),
    ("不锈钢刀具六件套", "Stainless Steel Knife Set 6pcs", "厨房用品", 1.5, "不锈钢", "银黑", 10, 26.0, 42.99),
    ("便携榨汁杯 USB充电", "USB Portable Blender Cup", "厨房用品", 0.6, "Tritan", "粉色", 30, 14.0, 24.99),
    ("硅胶铲勺厨具五件套", "Silicone Kitchen Utensil Set 5pcs", "厨房用品", 0.8, "食品级硅胶", "灰色", 30, 11.0, 19.99),
    ("帆布托特包 大容量", "Canvas Tote Bag Large", "服饰配件", 0.35, "帆布", "米色", 80, 7.2, 13.99),
    ("防晒渔夫帽 可折叠", "Foldable Sun Bucket Hat", "服饰配件", 0.1, "涤纶", "卡其", 100, 3.5, 8.99),
    ("针织围巾加厚冬季", "Thick Knit Winter Scarf", "服饰配件", 0.25, "腈纶", "酒红", 100, 5.9, 12.99),
    ("运动腰包跑步手机袋", "Running Belt Waist Bag", "服饰配件", 0.12, "尼龙", "黑色", 100, 4.5, 9.99),
    ("浴室置物架免打孔", "No-drill Bathroom Shelf", "家居", 0.9, "太空铝", "银色", 30, 13.2, 22.99),
    ("无线桌面充电支架", "Wireless Charging Desk Stand", "3C配件", 0.25, "铝合金", "深灰", 40, 12.8, 21.99),
    ("猫抓板瓦楞纸大号", "Cat Scratcher Cardboard Large", "宠物用品", 0.7, "瓦楞纸", "原色", 40, 6.5, 13.99),
    ("车载缝隙收纳盒", "Car Seat Gap Organizer", "汽车用品", 0.4, "ABS", "黑色", 60, 6.8, 13.49),
    ("湿巾加热器车载", "Car Wet Wipe Warmer", "母婴用品", 0.45, "ABS", "白色", 30, 10.8, 18.49),
    ("阳台种植架多层", "Balcony Plant Stand Multi-tier", "家居", 2.2, "碳钢", "黑金", 10, 24.0, 39.99),
    ("健身弹力带套装5件", "Resistance Bands Set 5pcs", "户外运动", 0.5, "乳胶", "多彩", 60, 8.9, 16.49),
    ("吹风机扩散风罩", "Hair Dryer Diffuser Attachment", "美妆工具", 0.2, "PP", "黑色", 80, 3.9, 8.99),
]

_FIRST = ["Emma", "Liam", "Olivia", "Noah", "Ava", "Ethan", "Sophia", "Mason",
          "Isabella", "Lucas", "Mia", "James"]
_COUNTRIES = ["US", "DE", "GB", "FR", "SG", "MY", "TH", "PH", "BR", "MX", "AU", "CA"]
_PLATFORMS = ["shopee", "amazon", "shopify", "ebay", "temu", "tiktok"]


def gen_sku() -> str:
    return f"SKU-{random.randint(10000, 99999)}"


def gen_products(keyword: str | None = None, count: int = 8) -> list[dict]:
    """模拟 1688 采集结果（确定性随机）。"""
    rng = random.Random(f"{keyword or 'erp'}-{datetime.utcnow().date()}")
    pool = list(PRODUCT_TEMPLATES)
    if keyword:
        matched = [t for t in pool if keyword.lower() in (t[0] + t[1] + t[2]).lower()]
        pool = matched + [t for t in pool if t not in matched]
    rng.shuffle(pool)
    items = []
    for t in pool[:count]:
        title_zh, title_en, category, weight, material, color, moq, price_cny, sale_usd = t
        items.append({
            "title_zh": title_zh, "title_en": title_en, "category": category,
            "attrs": {"weight_kg": weight, "material": material, "color": color,
                      "moq": moq, "supplier_price": price_cny, "sale_price": sale_usd,
                      "onhand": rng.choice([0, 20, 50, 120, 300]),
                      "scene": rng.choice(["home", "travel", "office", "outdoor", "gift"])},
            "price_range": f"¥{price_cny}-¥{round(price_cny * 1.4, 2)}",
            "min_order": f"{moq}件起批",
            "supplier_location": rng.choice(["义乌", "深圳", "广州", "宁波", "汕头"]),
        })
    return items


def insert_products(db, tenant_id: int, items: list[dict], source_platform: str = "1688") -> list[Product]:
    now = datetime.utcnow()
    products = []
    for i, it in enumerate(items):
        p = Product(
            tenant_id=tenant_id, sku=gen_sku(), title=it["title_zh"],
            category=it.get("category", ""), brand="",
            attrs=dict(it["attrs"], title_en=it.get("title_en", "")),
            images=[f"/api/placeholder/{tenant_id}-{i + 1}.svg",
                    f"/api/placeholder/{tenant_id}-{i + 1}b.svg"],
            source_platform=source_platform,
            source_url=f"https://detail.1688-demo.local/offer/{random.randint(100000, 999999)}",
        )
        p.created_at = now - timedelta(days=random.randint(0, 45))
        db.add(p)
        products.append(p)
    db.commit()
    return products


def collect(db, tenant_id: int, platform: str, keyword: str | None, count: int) -> dict:
    items = gen_products(keyword, count)
    products = insert_products(db, tenant_id, items, source_platform=platform or "1688")
    return {"collected": len(products), "items": [to_dict(p) for p in products]}


def gen_order(db, tenant_id: int, platform: str | None = None) -> Order:
    """生成一条模拟订单（成本利润按真实公式换算）。"""
    products = (db.query(Product)
                .filter(Product.tenant_id == tenant_id, Product.status == "active").all())
    p = random.choice(products) if products else None
    qty = random.choices([1, 2, 3], weights=[70, 20, 10])[0]
    fx = 7.12
    purchase = float((p.attrs or {}).get("supplier_price", 10)) if p else 10
    logistics = 18 + 8 * float((p.attrs or {}).get("weight_kg", 0.3)) if p else 20
    fee_rate = 0.06
    price = float((p.attrs or {}).get("sale_price", 19.99)) * qty * random.uniform(0.9, 1.1) if p else 19.99
    cost_total = (purchase * qty + logistics + fee_rate * price * fx + 1.5) / fx
    amount = round(price, 2)
    cost = round(cost_total, 2)
    status = random.choices(["pending", "paid", "shipped", "delivered", "refunded"],
                            weights=[10, 20, 30, 35, 5])[0]
    o = Order(
        tenant_id=tenant_id,
        platform=platform or random.choice(_PLATFORMS),
        external_no=f"SO{random.randint(10 ** 9, 10 ** 10 - 1)}",
        product_id=p.id if p else None,
        qty=qty, amount=amount, cost=cost,
        profit=round(amount - cost, 2), currency="USD",
        status=status, country=random.choice(_COUNTRIES),
        buyer_name=random.choice(_FIRST) + f"{random.randint(10, 99)}",
    )
    days_ago = random.randint(0, 59)
    o.created_at = datetime.utcnow() - timedelta(days=days_ago,
                                                 hours=random.randint(0, 23),
                                                 minutes=random.randint(0, 59))
    o.updated_at = o.created_at
    db.add(o)
    db.flush()
    return o
