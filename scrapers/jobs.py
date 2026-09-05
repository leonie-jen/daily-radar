"""職缺 + 技術文章。

LinkedIn 反爬很兇（GitHub Actions 的 IP 通常會被擋），所以：
主力用 104 的搜尋 API（穩定），LinkedIn 當 best-effort，
抓不到就在網站上顯示為「來源異常」而不是靜靜地空白。
"""
from __future__ import annotations

from urllib.parse import quote_plus

from .common import (Section, clean_text, get, get_json, google_news_rss,
                     parse_feed, soup_of)


def scrape(cfg: dict) -> Section:
    conf = cfg.get("jobs", {})
    sec = Section("jobs")

    for kw in conf.get("keywords", []):
        sec.add(_jobs_104(kw), f"104｜{kw}")

    sec.add(_linkedin(conf.get("linkedin_keywords", "Test Automation"),
                      conf.get("linkedin_location", "Taiwan")),
            "LinkedIn 職缺",
            note="LinkedIn 常擋機器人，抓不到屬正常")

    for url in conf.get("blog_feeds") or []:
        sec.add(parse_feed(url, limit=10), _feed_name(url))

    for q in conf.get("article_queries") or []:
        sec.add(parse_feed(google_news_rss(q), limit=10), "Google News 文章")

    sec.add(parse_feed("https://dev.to/feed/tag/testing", limit=15), "dev.to #testing")

    for it in sec.items:
        it.setdefault("kind", "job" if it.get("company") else "article")
    return sec


def _feed_name(url: str) -> str:
    from urllib.parse import urlparse
    return urlparse(url).netloc.replace("www.", "")


def _jobs_104(keyword: str, limit: int = 15) -> list[dict]:
    """104 搜尋 API。一定要帶 Referer，否則會回 HTML 而不是 JSON。

    104 的關鍵字搜尋很寬鬆（搜「自動化測試」會撈到人資職缺），
    所以這裡再過一次：職稱或描述真的提到關鍵字才留下。
    """
    url = ("https://www.104.com.tw/jobs/search/api/jobs"
           f"?ro=0&keyword={quote_plus(keyword)}&order=15&asc=0&page=1"
           "&mode=s&jobsource=index_s")
    data = get_json(url, headers={"Referer": "https://www.104.com.tw/jobs/search/"})
    rows = (data or {}).get("data")
    if not isinstance(rows, list):
        return []

    kw_low = keyword.lower()
    out = []
    for j in rows:
        name = clean_text(j.get("jobName", ""))
        desc = clean_text(j.get("descSnippet") or j.get("description") or "")
        if kw_low not in f"{name} {desc}".lower():
            continue

        link = j.get("link")
        link = link.get("job", "") if isinstance(link, dict) else (link or "")
        if link.startswith("//"):
            link = "https:" + link
        if not link:
            continue

        out.append({
            "title": name,
            "url": link,
            "company": clean_text(j.get("custName", "")),
            "location": clean_text(j.get("jobAddrNoDesc", "")),
            "salary": _salary(j),
            "published": _ymd(j.get("appearDate")),
            "excerpt": desc[:400],
            "kind": "job",
        })
        if len(out) >= limit:
            break
    return out


def _salary(j: dict) -> str:
    lo, hi = j.get("salaryLow") or 0, j.get("salaryHigh") or 0
    if not lo and not hi:
        return "面議"
    if hi and hi >= 9999999:
        return f"月薪 {lo:,} 以上"
    return f"{lo:,} - {hi:,}" if lo and hi else f"{lo or hi:,}"


def _ymd(s: str | None) -> str | None:
    import re as _re
    m = _re.fullmatch(r"(\d{4})(\d{2})(\d{2})", str(s or ""))
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def _linkedin(keywords: str, location: str, limit: int = 15) -> list[dict]:
    """LinkedIn 的 guest endpoint，不需登入但很容易被擋。f_TPR=r86400 = 只看 24 小時內。"""
    url = ("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
           f"?keywords={quote_plus(keywords)}&location={quote_plus(location)}"
           "&f_TPR=r86400&start=0")
    soup = soup_of(url, headers={"Referer": "https://www.linkedin.com/jobs/"})
    if not soup:
        return []
    out = []
    for card in soup.select("li")[:limit]:
        a = card.select_one("a.base-card__full-link, a[href*='/jobs/view/']")
        title = card.select_one(".base-search-card__title")
        company = card.select_one(".base-search-card__subtitle")
        loc = card.select_one(".job-search-card__location")
        if not (a and title):
            continue
        out.append({
            "title": clean_text(title.get_text()),
            "url": a["href"].split("?")[0],
            "company": clean_text(company.get_text()) if company else "",
            "location": clean_text(loc.get_text()) if loc else location,
            "salary": "",
            "published": None,
            "excerpt": "",
            "kind": "job",
        })
    return out
