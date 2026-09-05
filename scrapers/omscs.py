"""GT OMSCS 情報：官方公告 + Reddit + Google News + HN + Medium。

錄取/被拒的實際案例幾乎都在 Reddit r/OMSCS，所以那是主力來源；
官方頁面則是規則異動的權威來源。
"""
from __future__ import annotations

from . import reddit
from .common import (Section, clean_text, get, google_news_rss, match_keywords,
                     parse_feed, soup_of)

REDDIT_SOURCES = [
    ("Reddit r/OMSCS", dict(sub="OMSCS", sort="new")),
    ("Reddit r/OMSCS 錄取討論",
     dict(sub="OMSCS", query="admission OR admitted OR rejected OR decision")),
    ("Reddit r/gradadmissions", dict(sub="gradadmissions", query="OMSCS")),
]

NEWS_QUERIES = [
    '"OMSCS" OR "Georgia Tech Online Master of Science in Computer Science"',
    'Georgia Tech OMSCS admission',
]


def scrape(cfg: dict) -> Section:
    conf = cfg.get("omscs", {})
    sec = Section("omscs")
    kws = conf.get("admission_keywords", [])

    for name, kw in REDDIT_SOURCES:
        sec.add(reddit.listing(limit=30, **kw), name)

    for q in NEWS_QUERIES:
        sec.add(parse_feed(google_news_rss(q), limit=15), "Google News")

    sec.add(_gatech_news(), "OMSCS 官方公告")
    sec.add(parse_feed("https://medium.com/feed/tag/omscs", limit=15), "Medium #omscs")
    sec.add(_hn(), "Hacker News")

    for url in conf.get("extra_feeds") or []:
        sec.add(parse_feed(url), url)

    # 標出「錄取情報」— 這是使用者真正在找的東西
    for it in sec.items:
        hits = match_keywords(f"{it['title']} {it.get('excerpt','')}", kws)
        it["admission_signal"] = bool(hits)
        it["keyword_hits"] = hits

    return sec


def _gatech_news() -> list[dict]:
    """官方 news 頁沒有 RSS，直接抓 /external-news 連結。"""
    soup = soup_of("https://omscs.gatech.edu/news")
    if not soup:
        return []
    out, seen = [], set()
    for a in soup.select('a[href^="/external-news"]'):
        title = clean_text(a.get_text(" "))
        href = "https://omscs.gatech.edu" + a["href"]
        if not title or href in seen:
            continue
        seen.add(href)
        out.append({"title": title, "url": href, "published": None, "excerpt": ""})
    return out


def _hn() -> list[dict]:
    from .common import get_json
    data = get_json("https://hn.algolia.com/api/v1/search_by_date"
                    "?query=OMSCS&tags=story&hitsPerPage=20")
    if not data:
        return []
    out = []
    for h in data.get("hits", []):
        url = h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}"
        out.append({
            "title": clean_text(h.get("title") or ""),
            "url": url,
            "published": h.get("created_at"),
            "excerpt": clean_text(h.get("story_text") or "")[:500],
        })
    return [o for o in out if o["title"]]
