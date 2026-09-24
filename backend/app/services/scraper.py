"""真实网页采集器：多级抓取管线，输入商品页 URL 拿到商品要素。

Level 1  静态 HTTP：Open Graph / JSON-LD / 各平台内嵌 JSON（1688/京东/淘宝），快、零依赖；
Level 2  无头浏览器（Playwright）：执行 JS 过反爬挑战、等待渲染后取完整 DOM，
         需 `pip install playwright && playwright install chromium`，未安装自动跳过；
Level 3  用户粘贴网页源码（/api/products/collect_html），任何登录墙/验证码站点都能入库。

附带 SSRF 防护：禁止内网/回环地址。
"""
import ipaddress
import json
import re
import socket
from urllib.parse import urljoin, urlparse

import httpx

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
_HEADERS = {"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
_TIMEOUT = 15.0


class ScrapeError(Exception):
    pass


def _assert_public_host(url: str) -> str:
    """SSRF 防护：仅允许公网 http/https 地址。返回规范化 URL。"""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ScrapeError("仅支持 http/https 链接")
    host = parsed.hostname or ""
    if not host:
        raise ScrapeError("URL 缺少主机名")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise ScrapeError(f"域名无法解析: {host}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            raise ScrapeError(f"禁止采集内网地址: {host}")
    if host in ("localhost",) or host.endswith(".local"):
        raise ScrapeError(f"禁止采集内网地址: {host}")
    return str(url)


def _meta_og(html: str, prop: str) -> str:
    m = re.search(
        rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)',
        html, re.I) or re.search(
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{re.escape(prop)}["\']',
        html, re.I)
    return m.group(1).strip() if m else ""


def _jsonld_from(html: str) -> dict:
    """解析 JSON-LD 结构化数据（@type=Product 的 name/offers/image）。"""
    for m in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                         html, re.S | re.I):
        try:
            data = json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            continue
        items = data if isinstance(data, list) else [data]
        for it in items:
            if isinstance(it, dict) and str(it.get("@type", "")).lower() == "product":
                return it
    return {}


def _unescape(s: str) -> str:
    """安全解 JS 字符串转义：仅当含 \\uXXXX 时解码，原生中文不做处理。"""
    if "\\u" not in s:
        return s
    try:
        return s.encode("latin-1", "backslashreplace").decode("unicode-escape")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return s


def _title_from_scripts(html: str) -> str:
    """从平台内嵌 JS 变量提取标题（1688/京东/淘宝渲染数据）。"""
    for pat in (r'"subject"\s*:\s*"([^"]{6,200})"',                 # 1688
                r'pageConfig\.product\s*=\s*[^;]*?"name"\s*:\s*"([^"]{6,200})"',  # 京东
                r'"itemName"\s*:\s*"([^"]{6,200})"',                # 淘宝/1688 移动
                r'window\.detailDataData\s*=\s*\{[^;]*?"subject"\s*:\s*"([^"]{6,200})"'):
        m = re.search(pat, html)
        if m:
            return _unescape(m.group(1))
    return ""


def _price_from_scripts(html: str) -> float:
    for pat in (r'"priceRange"\s*:\s*\[\s*\[\s*\{\s*"price"\s*:\s*(\d+(?:\.\d+)?)',  # 1688
                r'"promoPrice"\s*:\s*\{\s*"value"\s*:\s*"?(\d+(?:\.\d+)?)"?',
                r'"salePrice"\s*:\s*"?(\d+(?:\.\d+)?)"?',
                r'pageConfig\.product[^;]*?"price"\s*:\s*"?(\d+(?:\.\d+)?)"?'):
        m = re.search(pat, html)
        if m:
            return float(m.group(1))
    return 0.0


def _price_from(html: str) -> float:
    """价格提取优先级：OG price > JSON-LD > 平台内嵌 JS > 常见货币正则。"""
    for prop in ("og:price:amount", "product:price:amount", "og:price"):
        v = _meta_og(html, prop)
        if v:
            try:
                return float(re.sub(r"[^\d.]", "", v))
            except ValueError:
                pass
    ld = _jsonld_from(html)
    offers = ld.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    for key in ("price", "lowPrice"):
        try:
            if offers.get(key):
                return float(re.sub(r"[^\d.]", "", str(offers[key])))
        except (ValueError, TypeError):
            pass
    v = _price_from_scripts(html)
    if v:
        return v
    m = (re.search(r"[¥￥]\s*(\d+(?:\.\d{1,2})?)", html)
         or re.search(r"\$\s*(\d+(?:\.\d{1,2})?)", html)
         or re.search(r"[£€]\s*(\d+(?:\.\d{1,2})?)", html)
         or re.search(r"价格[:：]\s*(\d+(?:\.\d{1,2})?)", html))
    return float(m.group(1)) if m else 0.0


def _images_from(html: str, og: str, base_url: str) -> list[str]:
    imgs = []
    if og:
        imgs.append(urljoin(base_url, og))
    for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.I):
        src = urljoin(base_url, m.group(1))  # 相对路径按页面 URL 解析为绝对地址
        if src.startswith("data:") or ".svg" in src or "logo" in src.lower():
            continue
        if re.search(r"\.(jpe?g|png|webp)", src, re.I):
            imgs.append(src)
        if len(imgs) >= 6:
            break
    return list(dict.fromkeys(imgs))


def parse_product_html(html: str, url: str, preferred_title: str = "") -> dict:
    """把商品页 HTML 解析为入库结构（纯函数，可独立测试）。

    标题优先级：显式传入（浏览器 DOM 提取）> OG > JSON-LD > 平台内嵌 JS > <title>。
    """
    ld = _jsonld_from(html)
    title = (preferred_title
             or _meta_og(html, "og:title") or _meta_og(html, "title")
             or str(ld.get("name") or "") or _title_from_scripts(html))
    if not title:
        m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
        title = m.group(1).strip() if m else ""
    title = re.sub(r"\s+", " ", title)[:200]
    if not title:
        raise ScrapeError("页面中未找到商品标题")
    desc = _meta_og(html, "og:description") or _meta_og(html, "description") or str(ld.get("description") or "")
    price = _price_from(html)
    og_image = _meta_og(html, "og:image")
    if not og_image and ld.get("image"):
        img = ld["image"]
        img = img[0] if isinstance(img, list) else img
        og_image = str(img)
    images = _images_from(html, og_image, url)
    domain = urlparse(url).netloc
    return {
        "title": title,
        "description": desc[:500],
        "price": price,
        "images": images,
        "domain": domain,
        "source_url": url,
    }


def fetch_product_browser(url: str) -> dict:
    """Level 2：无头浏览器渲染抓取（过 JS 反爬挑战/等待 SPA 渲染）。

    未安装 Playwright 时抛 ScrapeError 提示，调用方降级。
    """
    safe_url = _assert_public_host(url)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise ScrapeError("浏览器引擎未安装（pip install playwright && playwright install chromium）") from e
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True,
                                        args=["--disable-blink-features=AutomationControlled"])
            page = browser.new_page(user_agent=_UA, locale="zh-CN",
                                    viewport={"width": 1440, "height": 900})
            page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
            page.goto(safe_url, wait_until="domcontentloaded", timeout=40_000)
            page.wait_for_timeout(4000)  # 等 JS 挑战跳转与渲染
            html = page.content()
            dom_title = page.evaluate(
                "() => { const og = document.querySelector('meta[property=\"og:title\"]');"
                " if (og && og.content) return og.content;"
                " const t = document.title || ''; return t.replace(/[-|–—]\\s*(阿里巴巴|1688|淘宝网|天猫|京东|Amazon.*|eBay.*)?\\s*$/,'').trim(); }")
            browser.close()
    except ScrapeError:
        raise
    except Exception as e:
        raise ScrapeError(f"浏览器渲染抓取失败: {e}") from e
    if len(html) < 5000:
        raise ScrapeError("渲染后页面内容过短，站点可能要求登录或验证码")
    return parse_product_html(html, safe_url, preferred_title=dom_title or "")


_BLOCK_TITLE_MARKS = ("验证码拦截", "punish", "请输入验证码", "访问异常", "登录", "slider", "captcha")


def _looks_blocked(title: str, url: str) -> bool:
    t = (title or "").lower()
    if len(title) < 4:
        return True
    return any(m in t for m in _BLOCK_TITLE_MARKS) and "1688" not in title and "taobao" not in title


def fetch_product_auto(db, url: str) -> tuple[dict, str]:
    """三层管线：1688 官方 API（有配置时）→ 静态 HTTP → 无头浏览器渲染。

    返回 (item, engine)：engine ∈ {api1688, static, browser}。
    """
    offer_id = _offer_id_1688(url)
    if offer_id:
        try:
            from . import open_1688

            return open_1688.product_info(db, int(offer_id)), "api1688"
        except Exception:  # API 未配置/失败 -> 继续走抓取管线
            pass
    try:
        item = fetch_product(url)
        if item.get("price") and not _looks_blocked(item["title"], url):
            return item, "static"
    except ScrapeError:
        pass
    item = fetch_product_browser(url)
    if _looks_blocked(item["title"], url):
        raise ScrapeError(
            "目标站点弹出验证码/登录墙（频繁抓取会触发）。建议：1) 在「AI 设置」配置 1688 官方 API Key 走正式接口；"
            "2) 或用「粘贴网页源码」方式采集")
    return item, "browser"


def _offer_id_1688(url: str) -> str | None:
    m = re.search(r"detail\.1688\.com/offer/(\d+)\.html", url or "")
    return m.group(1) if m else None


def fetch_product(url: str) -> dict:
    """真实抓取一个商品页（静态 HTTP）。失败抛 ScrapeError。"""
    safe_url = _assert_public_host(url)
    try:
        resp = httpx.get(safe_url, headers=_HEADERS, follow_redirects=True,
                         timeout=_TIMEOUT)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise ScrapeError(f"抓取失败: {e}") from e
    content_type = resp.headers.get("content-type", "")
    if "html" not in content_type and "text" not in content_type:
        raise ScrapeError(f"不支持的内容类型: {content_type}")
    html = resp.text[:2_000_000]
    return parse_product_html(html, safe_url)
