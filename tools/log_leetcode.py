"""把 GitHub Issue 表單的內容存成 data/leetcode.json。

Issue Forms 送出的內容長這樣：
    ### 日期

    2026-09-05

    ### 題目

    1. Two Sum
    ...
所以用 "### 欄位名" 來切段落就好。
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data" / "leetcode.json"
TPE = timezone(timedelta(hours=8))


def parse_sections(body: str) -> dict[str, str]:
    parts = re.split(r"^###\s+", body, flags=re.M)
    out = {}
    for part in parts[1:]:
        head, _, rest = part.partition("\n")
        text = rest.strip()
        out[head.strip()] = "" if text in ("_No response_", "_未填寫_") else text
    return out


def main() -> int:
    body = os.environ.get("ISSUE_BODY", "")
    if not body.strip():
        print("issue 內容是空的，不做事")
        return 0

    sec = parse_sections(body)
    date = (sec.get("日期") or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        date = datetime.now(TPE).date().isoformat()

    problems = [re.sub(r"^[-*]\s*", "", ln).strip()
                for ln in (sec.get("題目") or "").splitlines() if ln.strip()]
    if not problems:
        print("沒有填題目，不做事")
        return 0

    payload = json.loads(DATA.read_text(encoding="utf-8")) if DATA.exists() else {"entries": []}
    entries = payload.get("entries", [])

    # 同一天再填一次就合併，不要出現兩筆同日期
    existing = next((e for e in entries if e["date"] == date), None)
    if existing:
        seen = set(existing["problems"])
        existing["problems"] += [p for p in problems if p not in seen]
        if note := (sec.get("心得（選填）") or sec.get("心得") or "").strip():
            existing["note"] = "\n".join(filter(None, [existing.get("note"), note]))
    else:
        entries.append({
            "date": date,
            "problems": problems,
            "note": (sec.get("心得（選填）") or sec.get("心得") or "").strip(),
            "issue": int(os.environ.get("ISSUE_NUM", 0) or 0),
        })

    entries.sort(key=lambda e: e["date"], reverse=True)
    payload["entries"] = entries
    payload["updated_at"] = datetime.now(TPE).isoformat()

    DATA.parent.mkdir(exist_ok=True)
    DATA.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已記錄 {date}：{len(problems)} 題")
    return 0


if __name__ == "__main__":
    sys.exit(main())
