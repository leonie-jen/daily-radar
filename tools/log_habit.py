"""把「習慣打卡」issue 存進 data/habits.json。

Issue Forms 的 checkbox 會渲染成：
    - [x] 🏃 運動
    - [ ] 🎧 VoiceTube 打卡
所以只要挑出打勾的行，再對回 config.yml 裡設定的習慣名稱即可。
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "habits.json"
TPE = timezone(timedelta(hours=8))


def habit_keys() -> list[str]:
    cfg = yaml.safe_load((ROOT / "config.yml").read_text(encoding="utf-8"))
    return [h["key"] for h in (cfg.get("habits", {}).get("track") or [])]


def main() -> int:
    body = os.environ.get("ISSUE_BODY", "")
    if not body.strip():
        print("issue 內容是空的，不做事")
        return 0

    keys = habit_keys()
    # 勾起來的項目：- [x] 🏃 運動
    checked = re.findall(r"^\s*-\s*\[[xX]\]\s*(.+?)\s*$", body, flags=re.M)
    done = [k for k in keys if any(k in line for line in checked)]

    m = re.search(r"^###\s*日期\s*\n+(\d{4}-\d{2}-\d{2})", body, flags=re.M)
    date = m.group(1) if m else datetime.now(TPE).date().isoformat()

    note = ""
    if m2 := re.search(r"^###\s*一句話（選填）\s*\n+(.+?)(?=\n###|\Z)", body, flags=re.M | re.S):
        text = m2.group(1).strip()
        note = "" if text in ("_No response_", "_未填寫_") else text

    if not done and not note:
        print("沒有勾任何項目也沒寫心得，不做事")
        return 0

    payload = json.loads(DATA.read_text(encoding="utf-8")) if DATA.exists() else {"entries": []}
    entries = payload.get("entries", [])

    # 同一天再打一次就合併（例如早上先勾運動，晚上再補韓文）
    if existing := next((e for e in entries if e["date"] == date), None):
        existing["done"] = sorted(set(existing["done"]) | set(done), key=keys.index)
        if note:
            existing["note"] = "\n".join(filter(None, [existing.get("note"), note]))
    else:
        entries.append({"date": date, "done": done, "note": note})

    entries.sort(key=lambda e: e["date"], reverse=True)
    payload["entries"] = entries
    payload["updated_at"] = datetime.now(TPE).isoformat()

    DATA.parent.mkdir(exist_ok=True)
    DATA.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已記錄 {date}：{'、'.join(done) or '(只有心得)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
