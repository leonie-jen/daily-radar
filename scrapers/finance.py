"""匯率 + 股市。

來源選擇的理由（都實測過，而且不需要 API key）：
- 匯率：rter.info（台灣站，USDTWD 更新頻繁）+ open.er-api 當備援。
        台銀牌告有 JS 反爬擋著，抓不了，所以這裡是中間價，
        實際換匯的銀行買賣價會再差個 0.1~0.3 元。
- 美股：CNBC 的報價服務（Yahoo Finance 會對機房 IP 回 429）。
- 台股大盤：證交所官方 OpenAPI。
- 台股個股：證交所 MIS 即時報價。
- 哈利的投資研究筆記庫：sitemap 有 lastmod，直接照日期組 URL 最省事。
"""
from __future__ import annotations

import re
from datetime import timedelta

from .common import (Section, clean_text, get, get_json, item_id, now_tpe,
                     read_json, soup_of)

CNBC = ("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol"
        "?symbols={syms}&requestMethod=itv&noform=1&partnerId=2&fund=1"
        "&exthrs=1&output=json&events=1")

# config 用 Yahoo 風格代號，這裡轉成各家實際能用的代號
CNBC_ALIAS = {"^GSPC": ".SPX", "^IXIC": ".IXIC", "^SOX": ".SOX", "^DJI": ".DJI",
              "^VIX": ".VIX", "^RUT": ".RUT"}


def scrape(cfg: dict) -> Section:
    conf = cfg.get("finance", {})
    sec = Section("finance")

    fx = _fx(conf)
    sec.extra["fx"] = fx
    sec.sources.append(_status("匯率 USD/TWD", bool(fx.get("usd_twd"))))

    quotes = _quotes(conf.get("tickers", []))
    sec.extra["quotes"] = quotes
    sec.sources.append(_status("股價報價", bool(quotes), f"{len(quotes)} 檔"))

    # 導航連結原封不動帶到前端；這是設定不是抓來的資料，所以不需要爬
    sec.extra["links"] = conf.get("links", [])

    hm = conf.get("harrymemo", {})
    if hm.get("enabled", True):
        sec.add(_harrymemo(hm), "哈利的投資研究筆記庫")

    return sec


def _status(name, ok, note=""):
    from .common import SourceStatus
    return SourceStatus(name, ok=ok, count=1 if ok else 0,
                        note=note or ("" if ok else "抓取失敗"))


# ---------------------------------------------------------------- 匯率

def _fx(conf: dict) -> dict:
    rate = None
    src = None

    data = get_json("https://tw.rter.info/capi.php")
    if data and isinstance(data.get("USDTWD"), dict):
        rate = data["USDTWD"].get("Exrate")
        src = "rter.info"

    if rate is None:
        data = get_json("https://open.er-api.com/v6/latest/USD")
        if data and data.get("result") == "success":
            rate = (data.get("rates") or {}).get("TWD")
            src = "exchangerate-api"

    if rate is None:
        return {}

    rate = round(float(rate), 4)
    history = _push_history("fx_history", rate, keep=180)
    alert_below = conf.get("usd_twd_alert_below")

    return {
        "usd_twd": rate,
        "source": src,
        "history": history,
        "change_7d": _delta(history, 7),
        "change_30d": _delta(history, 30),
        "alert_below": alert_below,
        "good_time_to_buy": bool(alert_below and rate < float(alert_below)),
        "note": "中間價，實際銀行買賣會有價差",
    }


def _push_history(key: str, value: float, keep: int = 180) -> list[dict]:
    """每天記一點，前端才畫得出走勢圖。同一天只留最後一筆。"""
    hist = read_json(key, []) or []
    today = now_tpe().date().isoformat()
    hist = [h for h in hist if h.get("d") != today]
    hist.append({"d": today, "v": value})
    hist = sorted(hist, key=lambda h: h["d"])[-keep:]
    from .common import write_json
    write_json(key, hist)
    return hist


def _delta(history: list[dict], days: int) -> float | None:
    if len(history) < 2:
        return None
    target = (now_tpe().date() - timedelta(days=days)).isoformat()
    past = [h for h in history if h["d"] <= target]
    if not past:
        return None
    return round(history[-1]["v"] - past[-1]["v"], 4)


# ---------------------------------------------------------------- 報價

def _quotes(tickers: list[dict]) -> list[dict]:
    out = []
    us, tw = [], []
    for t in tickers:
        sym = t.get("symbol", "")
        (tw if (sym.endswith(".TW") or sym == "^TWII") else us).append(t)

    out += _cnbc(us)
    out += _twse(tw)
    order = {t.get("symbol"): n for n, t in enumerate(tickers)}
    return sorted(out, key=lambda q: order.get(q["symbol"], 99))


def _cnbc(tickers: list[dict]) -> list[dict]:
    if not tickers:
        return []
    syms = [CNBC_ALIAS.get(t["symbol"], t["symbol"]) for t in tickers]
    data = get_json(CNBC.format(syms="|".join(syms)))
    if not data:
        return []
    rows = (data.get("FormattedQuoteResult") or {}).get("FormattedQuote") or []
    if isinstance(rows, dict):
        rows = [rows]

    back = {CNBC_ALIAS.get(t["symbol"], t["symbol"]): t for t in tickers}
    out = []
    for r in rows:
        conf = back.get(r.get("symbol"), {})
        out.append({
            "symbol": conf.get("symbol", r.get("symbol")),
            "name": conf.get("name") or r.get("shortName") or r.get("name"),
            "price": _num(r.get("last")),
            "change": _num(r.get("change")),
            "change_pct": _num((r.get("change_pct") or "").replace("%", "")),
            "currency": r.get("currencyCode", "USD"),
            "as_of": r.get("last_time") or r.get("last_timedate"),
            "market": "US",
        })
    return out


def _twse(tickers: list[dict]) -> list[dict]:
    out = []
    stocks = [t for t in tickers if t["symbol"].endswith(".TW")]
    index = [t for t in tickers if t["symbol"] == "^TWII"]

    if index:
        data = get_json("https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX")
        row = next((r for r in (data or []) if r.get("指數") == "發行量加權股價指數"), None)
        if row:
            pct = _num(row.get("漲跌百分比"))
            sign = -1 if row.get("漲跌") == "-" else 1
            out.append({
                "symbol": "^TWII",
                "name": index[0].get("name", "台股加權指數"),
                "price": _num(row.get("收盤指數")),
                "change": (_num(row.get("漲跌點數")) or 0) * sign,
                "change_pct": (pct or 0) * sign,
                "currency": "TWD",
                "as_of": _roc_date(row.get("日期", "")),
                "market": "TW",
            })

    if stocks:
        chs = "|".join(f"tse_{t['symbol'].lower()}" for t in stocks)
        data = get_json(
            f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={chs}&json=1&delay=0",
            headers={"Referer": "https://mis.twse.com.tw/stock/"})
        by_code = {t["symbol"].split(".")[0]: t for t in stocks}
        for m in (data or {}).get("msgArray", []):
            conf = by_code.get(m.get("c"), {})
            price = _num(m.get("z")) or _num(m.get("pz"))   # z=成交價，收盤後可能是 "-"
            prev = _num(m.get("y"))                          # y=昨收
            change = round(price - prev, 2) if (price and prev) else None
            out.append({
                "symbol": conf.get("symbol", m.get("c")),
                "name": conf.get("name") or m.get("n"),
                "price": price,
                "change": change,
                "change_pct": round(change / prev * 100, 2) if (change and prev) else None,
                "currency": "TWD",
                "as_of": _fmt_ymd(m.get("d")),
                "market": "TW",
            })
    return out


def _num(s) -> float | None:
    if s is None:
        return None
    try:
        return float(str(s).replace(",", "").replace("%", "").strip())
    except ValueError:
        return None


def _roc_date(s: str) -> str:
    """民國 1150904 -> 2026-09-04"""
    m = re.fullmatch(r"(\d{3})(\d{2})(\d{2})", s or "")
    return f"{int(m.group(1)) + 1911}-{m.group(2)}-{m.group(3)}" if m else s


# ---------------------------------------------------------------- harrymemo

def _harrymemo(conf: dict) -> list[dict]:
    """站上沒有 RSS，但 sitemap.xml 有 lastmod，直接從那裡挑最新的 dashboard。

    比起自己照日期猜網址，讀 sitemap 不會抓到不存在的頁面
    （不存在的路徑會回一個 200 的空殼，猜網址會被騙）。

    注意：每個區塊「最新兩期」是付費會員限定（NT$150/月起），
    未登入抓到的會是訂閱方案頁。這種頁面標成 paywalled，
    只留標題與連結，不把訂閱說明當成報告內容餵給 AI。
    """
    labels = {"us": "美股", "tw": "台股", "crypto": "加密貨幣"}
    wanted = set(conf.get("sections", ["us", "tw"]))
    cutoff = (now_tpe().date() - timedelta(days=int(conf.get("days_back", 3)))).isoformat()

    r = get("https://harrymemo.com/sitemap.xml")
    if not r:
        return []

    picked = []
    for url in re.findall(r"<loc>([^<]+)</loc>", r.text):
        m = re.search(r"/outputs/(us|tw|crypto)/(\d{4}-\d{2}-\d{2})_", url)
        if m and m.group(1) in wanted and m.group(2) >= cutoff:
            picked.append((m.group(1), m.group(2), url))
    picked.sort(key=lambda x: x[1], reverse=True)

    out = []
    for section, date, url in picked[:8]:
        soup = soup_of(url if url.endswith("/") else url + "/")
        if not soup:
            continue
        body = soup.find("main") or soup.find("article") or soup
        text = clean_text(body.get_text(" "))
        paywalled = "訂閱會員可解鎖" in text or len(text) < 2000

        raw_title = clean_text(soup.title.get_text()) if soup.title else ""
        headline = raw_title.split("｜")[0].strip()
        if paywalled or not headline:
            headline = f"{date} {labels[section]}盤後報告"

        out.append({
            "title": f"[{labels[section]}] {headline}",
            "url": url,
            "published": date,
            "excerpt": "" if paywalled else text[:1500],
            "market_section": section,
            "paywalled": paywalled,
        })
    return out


def _fmt_ymd(s: str | None) -> str | None:
    """20260904 -> 2026-09-04"""
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", s or "")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else s
