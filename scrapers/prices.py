"""商品降價追蹤。

抓價格的策略是「由通用到特化」：
1. JSON-LD（schema.org Product/Offer）— 大部分正經電商都有，最可靠
2. Open Graph / meta 標籤（product:price:amount 之類）
3. 各站專屬的 CSS selector

蝦皮與 Amazon 反爬很兇，抓不到是常態；抓不到時會保留上一次的價格
並在網站上標成「抓取失敗」，不會假裝價格是 0。
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from .common import (Section, SourceStatus, clean_text, get, item_id, log,
                     now_tpe, read_json, soup_of, write_json)

SITE_SELECTORS = {
    "www.momoshop.com.tw": ["span.font-price", "li.special .price b", ".prdPrice .special"],
    "shopee.tw": ["._3e_UQT", ".pqTWkA"],
    "www.books.com.tw": [".price strong b", "ul.price li em"],
    "www.amazon.com": [".a-price .a-offscreen", "#corePrice_feature_div .a-offscreen"],
    "www.amazon.co.jp": [".a-price .a-offscreen"],
}

CURRENCY_HINT = {"amazon.com": "USD", "amazon.co.jp": "JPY"}


def scrape(cfg: dict) -> Section:
    conf = cfg.get("prices", {})
    sec = Section("prices")
    history = read_json("price_history", {}) or {}
    today = now_tpe().date().isoformat()

    for w in conf.get("watch", []):
        url, name = w.get("url"), w.get("name") or w.get("url", "")
        if not url:
            continue
        pid = item_id(url)
        host = urlparse(url).netloc

        price, title = _fetch_price(url, host)
        series = history.setdefault(pid, [])

        if price is not None:
            series[:] = [p for p in series if p.get("d") != today]
            series.append({"d": today, "v": price})
            series.sort(key=lambda p: p["d"])
            del series[:-365]

        values = [p["v"] for p in series]
        prev = values[-2] if len(values) >= 2 else None
        target = w.get("target_price")

        sec.items.append({
            "id": pid,
            "title": name,
            "detected_title": title,
            "url": url,
            "source": host,
            "currency": CURRENCY_HINT.get(host.replace("www.", ""), "TWD"),
            "price": price,
            "ok": price is not None,
            "prev_price": prev,
            "change": round(price - prev, 2) if (price is not None and prev) else None,
            "lowest": min(values) if values else None,
            "highest": max(values) if values else None,
            "is_lowest_ever": bool(values) and price is not None and price <= min(values),
            "target_price": target,
            "hit_target": bool(target and price is not None and price <= float(target)),
            "history": series[-120:],
            "checked_at": now_tpe().isoformat(),
        })
        sec.sources.append(SourceStatus(
            name, ok=price is not None, count=1 if price is not None else 0,
            note="" if price is not None else "抓不到價格（可能被反爬擋，或網址失效）"))
        log(f"  {'OK ' if price is not None else 'MISS'} {name}: {price}")

    write_json("price_history", history)
    return sec


def _fetch_price(url: str, host: str) -> tuple[float | None, str]:
    if "pchome.com.tw" in host:
        if found := _pchome(url):
            return found
    soup = soup_of(url, headers={"Referer": f"https://{host}/"})
    if not soup:
        return None, ""

    title = ""
    if og := soup.find("meta", property="og:title"):
        title = clean_text(og.get("content", ""))
    elif soup.title:
        title = clean_text(soup.title.get_text())

    for extractor in (_from_jsonld, _from_meta, _from_selectors):
        price = extractor(soup, host)
        if price:
            return price, title
    return None, title


def _pchome(url: str) -> tuple[float, str] | None:
    """PChome 商品頁是 SPA，HTML 裡沒有價格；改打它的 ecapi。
    回應是 JSONP（try{cb({...})}catch...），要把外殼剝掉。"""
    m = re.search(r"/prod/([A-Z0-9-]+)", url, re.I)
    if not m:
        return None
    r = get(f"https://ecapi.pchome.com.tw/ecshop/prodapi/v2/prod/{m.group(1)}"
            "&fields=Id,Name,Price,Nick&_callback=cb",
            headers={"Referer": "https://24h.pchome.com.tw/"})
    if not r:
        return None
    # 貪婪的 .* 會吃到最後一個右括號，要非貪婪並鎖到 catch 前面
    body = re.search(r"cb\((.*?)\);?\s*\}\s*catch", r.text, re.S)
    if not body:
        return None
    try:
        data = json.loads(body.group(1))
    except json.JSONDecodeError:
        return None
    for node in data.values():
        price = node.get("Price")
        value = _num(price.get("P") if isinstance(price, dict) else price)
        if value:
            return value, clean_text(node.get("Name", ""))
    return None


def _from_jsonld(soup, host) -> float | None:
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        for node in _walk(data):
            if not isinstance(node, dict):
                continue
            offers = node.get("offers")
            for offer in (offers if isinstance(offers, list) else [offers]):
                if isinstance(offer, dict) and (p := _num(offer.get("price"))):
                    return p
            if node.get("@type") == "Offer" and (p := _num(node.get("price"))):
                return p
    return None


def _walk(node):
    """JSON-LD 可能是 list、可能有 @graph，全部攤平來找。"""
    if isinstance(node, list):
        for n in node:
            yield from _walk(n)
    elif isinstance(node, dict):
        yield node
        for key in ("@graph", "itemListElement", "mainEntity"):
            if key in node:
                yield from _walk(node[key])


def _from_meta(soup, host) -> float | None:
    """momo 用 name="product:price:amount"，其他站多半用 property=，兩種都要找。"""
    for key in ("product:price:amount", "og:price:amount", "price"):
        for attr in ("property", "name", "itemprop"):
            if tag := soup.find("meta", attrs={attr: key}):
                if p := _num(tag.get("content")):
                    return p
    return None


def _from_selectors(soup, host) -> float | None:
    for sel in SITE_SELECTORS.get(host, []):
        if el := soup.select_one(sel):
            if p := _num(el.get_text()):
                return p
    return None


def _num(v) -> float | None:
    if v is None:
        return None
    m = re.search(r"\d[\d,]*(?:\.\d+)?", str(v))
    if not m:
        return None
    try:
        n = float(m.group().replace(",", ""))
    except ValueError:
        return None
    return n if n > 0 else None
