"""共用工具：HTTP、RSS、資料存取、去重、抓取狀態回報。"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

TPE = timezone(timedelta(hours=8))
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# 同一個 host 兩次請求之間至少隔這麼久。Reddit 連打會直接 403。
HOST_DELAY = {"www.reddit.com": 7.0, "old.reddit.com": 7.0, "news.google.com": 1.2,
               "www.books.com.tw": 3.0, "www.momoshop.com.tw": 2.0}
_last_hit: dict[str, float] = {}

_session = requests.Session()
_session.headers.update({
    "User-Agent": UA,
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
})


def now_tpe() -> datetime:
    return datetime.now(TPE)


def load_config() -> dict:
    with open(ROOT / "config.yml", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------- HTTP

def get(url: str, *, timeout: int = 20, headers: dict | None = None,
        retries: int = 3, **kw) -> requests.Response | None:
    """GET，失敗回 None 而不是丟例外 — 單一來源掛掉不該讓整批爬蟲死掉。"""
    _throttle(url)
    for attempt in range(retries + 1):
        try:
            r = _session.get(url, timeout=timeout, headers=headers, **kw)
            if r.status_code == 200:
                return r
            # Reddit 對未登入的請求會用 403 當作「太快了」，所以那邊的 403 也要重試
            retryable = {429, 500, 502, 503, 504}
            if "reddit.com" in url:
                retryable.add(403)
            if r.status_code not in retryable:
                log(f"  ! {r.status_code} {url[:80]}")
                return None
        except requests.RequestException as e:
            if attempt == retries:
                log(f"  ! {type(e).__name__} {url[:80]}")
                return None
        time.sleep(3.0 * (attempt + 1))
    return None


def _throttle(url: str) -> None:
    from urllib.parse import urlparse
    host = urlparse(url).netloc
    delay = HOST_DELAY.get(host)
    if not delay:
        return
    wait = delay - (time.monotonic() - _last_hit.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.monotonic()


def get_json(url: str, **kw) -> Any | None:
    r = get(url, **kw)
    if not r:
        return None
    try:
        return r.json()
    except ValueError:
        return None


def soup_of(url: str, **kw) -> BeautifulSoup | None:
    r = get(url, **kw)
    if not r:
        return None
    # 很多站不在 Content-Type 標 charset，requests 會猜成 ISO-8859-1 讓中文變亂碼
    if not r.encoding or r.encoding.lower() in ("iso-8859-1", "ascii"):
        r.encoding = r.apparent_encoding or "utf-8"
    return BeautifulSoup(r.text, "lxml")


def log(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------- RSS

def google_news_rss(query: str, lang: str | None = None, country: str | None = None) -> str:
    """沒指定語系時，依查詢字串是不是中文自動選繁中版或英文版。"""
    from urllib.parse import quote_plus
    if lang is None:
        cjk = bool(re.search(r"[\u4e00-\u9fff]", query))
        lang, country = ("zh-TW", "TW") if cjk else ("en-US", "US")
    ceid = f"{country}:{lang.split('-')[0]}"
    return (f"https://news.google.com/rss/search?q={quote_plus(query)}"
            f"&hl={lang}&gl={country}&ceid={ceid}")


def parse_feed(url: str, limit: int = 25) -> list[dict]:
    """解析 RSS/Atom，回傳標準化的 item list。"""
    r = get(url, timeout=25)
    if not r:
        return []
    feed = feedparser.parse(r.content)
    out = []
    for e in feed.entries[:limit]:
        link = e.get("link") or ""
        if not link:
            continue
        published = None
        for key in ("published_parsed", "updated_parsed"):
            if e.get(key):
                published = datetime(*e[key][:6], tzinfo=timezone.utc).isoformat()
                break
        out.append({
            "title": clean_text(e.get("title", "")),
            "url": link,
            "published": published,
            "excerpt": clean_text(strip_html(e.get("summary", "")))[:600],
            "author": e.get("author"),
        })
    return out


def strip_html(html: str) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "lxml").get_text(" ")


def clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


# ---------------------------------------------------------------- 資料存取

def item_id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:12]


@dataclass
class SourceStatus:
    """記錄每個來源抓得順不順，前端會顯示紅綠燈。"""
    name: str
    ok: bool = True
    count: int = 0
    note: str = ""


@dataclass
class Section:
    key: str
    items: list[dict] = field(default_factory=list)
    sources: list[SourceStatus] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    def add(self, items: Iterable[dict], source: str, note: str = "") -> None:
        items = list(items)
        for it in items:
            it.setdefault("source", source)
            it["id"] = item_id(it["url"])
        self.items.extend(items)
        self.sources.append(SourceStatus(source, ok=bool(items), count=len(items),
                                         note=note or ("" if items else "沒抓到資料（可能被擋或今天沒新內容）")))
        log(f"  {'OK ' if items else 'MISS'} {source}: {len(items)}")


def read_json(name: str, default: Any = None) -> Any:
    p = DATA / f"{name}.json"
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def write_json(name: str, payload: Any) -> None:
    p = DATA / f"{name}.json"
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"  -> data/{name}.json")


def save_section(sec: Section, *, keep_days: int = 30, dedupe: bool = True) -> dict:
    """合併舊資料、去重、砍掉太舊的，然後寫檔。

    first_seen 是「我們第一次看到它」的時間，用來排序與標 NEW；
    published 常常缺漏或不可靠，所以不能只靠它。
    """
    now = now_tpe()
    old = read_json(sec.key, {}) or {}
    old_items = {i["id"]: i for i in old.get("items", [])}

    merged: dict[str, dict] = {}
    for it in sec.items:
        prev = old_items.get(it["id"])
        if prev:
            # 保留既有的 AI 摘要與 first_seen，不要重複花錢重算
            it.setdefault("summary", prev.get("summary"))
            it.setdefault("tags", prev.get("tags"))
            it.setdefault("relevance", prev.get("relevance"))
            it["first_seen"] = prev.get("first_seen", now.isoformat())
        else:
            it["first_seen"] = now.isoformat()
        if dedupe and it["id"] in merged:
            continue
        merged[it["id"]] = it

    # 沒在這次結果裡、但還沒過期的舊項目也留著
    cutoff = now - timedelta(days=keep_days)
    for iid, it in old_items.items():
        if iid in merged:
            continue
        try:
            seen = datetime.fromisoformat(it.get("first_seen", ""))
        except ValueError:
            continue
        if seen > cutoff:
            merged[iid] = it

    items = sorted(merged.values(), key=lambda i: i.get("first_seen", ""), reverse=True)

    payload = {
        "updated_at": now.isoformat(),
        "sources": [s.__dict__ for s in sec.sources],
        "items": items,
        **sec.extra,
    }
    write_json(sec.key, payload)
    return payload


def is_new(item: dict, hours: int = 30) -> bool:
    try:
        return datetime.fromisoformat(item["first_seen"]) > now_tpe() - timedelta(hours=hours)
    except (KeyError, ValueError):
        return False


def match_keywords(text: str, keywords: list[str]) -> list[str]:
    low = (text or "").lower()
    return [k for k in keywords if k.lower() in low]
