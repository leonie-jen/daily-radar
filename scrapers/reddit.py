"""Reddit 取用層。

錄取心得幾乎都在 Reddit，但公開的 .rss 對機器人很不友善——
同一個 IP 連打幾次就開始隨機回 403（實測每次成功的來源都不一樣）。

所以這裡分兩條路：
  1. 有設 REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET → 走官方 OAuth API，穩定不會被擋。
     申請是免費的，見 README「讓 Reddit 穩定抓取」。
  2. 沒設 → 退回公開 RSS，抓得到多少算多少（會在網站上標示來源異常）。
"""
from __future__ import annotations

import os
import time

import feedparser
import requests

from .common import UA, clean_text, get, log, strip_html

_token: tuple[str, float] | None = None      # (access_token, 到期時間)


def _oauth_token() -> str | None:
    global _token
    cid = os.environ.get("REDDIT_CLIENT_ID")
    secret = os.environ.get("REDDIT_CLIENT_SECRET")
    if not (cid and secret):
        return None
    if _token and _token[1] > time.time() + 60:
        return _token[0]

    try:
        r = requests.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(cid, secret),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": "daily-radar/1.0 by u/anonymous"},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError) as e:
        log(f"  ! Reddit OAuth 取 token 失敗：{e}")
        return None

    _token = (data["access_token"], time.time() + data.get("expires_in", 3600))
    return _token[0]


def listing(sub: str, *, sort: str = "new", query: str | None = None,
            limit: int = 30) -> list[dict]:
    """抓一個 subreddit 的貼文。query 有值就走搜尋。"""
    if token := _oauth_token():
        if items := _via_api(token, sub, sort, query, limit):
            return items
    return _via_rss(sub, sort, query, limit)


def _via_api(token: str, sub: str, sort: str, query: str | None, limit: int) -> list[dict]:
    headers = {"Authorization": f"bearer {token}", "User-Agent": "daily-radar/1.0 by u/anonymous"}
    if query:
        url = (f"https://oauth.reddit.com/r/{sub}/search"
               f"?q={requests.utils.quote(query)}&restrict_sr=1&sort=new&limit={limit}")
    else:
        url = f"https://oauth.reddit.com/r/{sub}/{sort}?limit={limit}"

    try:
        r = requests.get(url, headers=headers, timeout=20)
        r.raise_for_status()
        children = r.json()["data"]["children"]
    except (requests.RequestException, KeyError, ValueError) as e:
        log(f"  ! Reddit API r/{sub}：{e}")
        return []

    from datetime import datetime, timezone
    out = []
    for c in children:
        d = c.get("data", {})
        if d.get("stickied"):
            continue
        out.append({
            "title": clean_text(d.get("title", "")),
            "url": "https://www.reddit.com" + d.get("permalink", ""),
            "published": datetime.fromtimestamp(
                d.get("created_utc", 0), timezone.utc).isoformat(),
            "excerpt": clean_text(d.get("selftext", ""))[:700],
            "author": d.get("author"),
            "score": d.get("score"),
            "comments": d.get("num_comments"),
        })
    return out


def _via_rss(sub: str, sort: str, query: str | None, limit: int) -> list[dict]:
    from urllib.parse import quote_plus
    if query:
        url = (f"https://www.reddit.com/r/{sub}/search.rss"
               f"?q={quote_plus(query)}&restrict_sr=1&sort=new")
    else:
        # 注意：/r/<sub>/new/.rss 幾乎一定被擋，/r/<sub>/.rss 比較有機會
        url = f"https://www.reddit.com/r/{sub}/.rss"

    r = get(url)
    if not r:
        return []

    from datetime import datetime, timezone
    out = []
    for e in feedparser.parse(r.content).entries[:limit]:
        published = None
        if e.get("published_parsed"):
            published = datetime(*e["published_parsed"][:6], tzinfo=timezone.utc).isoformat()
        out.append({
            "title": clean_text(e.get("title", "")),
            "url": e.get("link", ""),
            "published": published,
            "excerpt": clean_text(strip_html(e.get("summary", "")))[:700],
            "author": e.get("author"),
        })
    return [o for o in out if o["url"]]
