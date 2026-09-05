"""CPT / OPT / F-1 簽證政策風向。

政策一變動，最快出現的是新聞與 r/f1visa 的災情回報，
所以這裡用 Google News 多組關鍵字 + Reddit 兩條腿走。
"""
from __future__ import annotations

from . import reddit
from .common import Section, google_news_rss, parse_feed

REDDIT = [
    ("Reddit r/f1visa", dict(sub="f1visa", sort="new")),
    ("Reddit r/immigration CPT", dict(sub="immigration", query="CPT OR OPT")),
]

OFFICIAL = [
    ("ICE 新聞稿", "https://www.ice.gov/rss.xml"),
    ("Study in the States", "https://studyinthestates.dhs.gov/rss.xml"),
]


def scrape(cfg: dict) -> Section:
    conf = cfg.get("cpt", {})
    sec = Section("cpt")

    for q in conf.get("queries", []):
        sec.add(parse_feed(google_news_rss(q), limit=12), "Google News")

    for name, kw in REDDIT:
        sec.add(reddit.listing(limit=25, **kw), name)

    for name, url in OFFICIAL:
        sec.add(parse_feed(url, limit=15), name)

    # 這些字代表「事情真的變了」，前端會置頂
    URGENT = ["revoked", "terminated", "lawsuit", "rule", "policy", "crackdown",
              "suspend", "ban", "federal register", "injunction", "sevp"]
    for it in sec.items:
        text = f"{it['title']} {it.get('excerpt','')}".lower()
        it["policy_signal"] = any(u in text for u in URGENT)

    return sec
