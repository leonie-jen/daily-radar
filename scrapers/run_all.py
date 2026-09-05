"""每日主流程：跑所有爬蟲 -> AI 加值 -> 寫 data/*.json。

單一來源失敗不會中斷整體；狀態會寫進 data/status.json，
網站上有紅綠燈可以看到哪個來源今天掛了。
"""
from __future__ import annotations

import sys
import traceback

from . import cpt, finance, jobs, omscs, prices
from .ai import Enricher
from .common import (Section, load_config, log, now_tpe, read_json,
                     save_section, write_json)

MODULES = [
    ("omscs", omscs, "OMSCS 情報"),
    ("cpt", cpt, "CPT / 簽證"),
    ("jobs", jobs, "職缺與文章"),
    ("finance", finance, "匯率與股市"),
    ("prices", prices, "商品降價"),
]

# 這些版面的內容適合送 AI 摘要；商品價格是數字，不需要
AI_SECTIONS = {"omscs", "cpt", "jobs", "finance"}


def main() -> int:
    cfg = load_config()
    started = now_tpe()
    enricher = Enricher(cfg)
    report = []

    for key, module, label in MODULES:
        if not cfg.get(key, {}).get("enabled", True):
            log(f"\n[{label}] 設定關閉，跳過")
            continue

        log(f"\n[{label}]")
        try:
            sec: Section = module.scrape(cfg)
        except Exception:                       # noqa: BLE001 — 一個版面掛掉不該拖垮其他版面
            log(f"  !! {key} 整個爆掉：\n{traceback.format_exc()}")
            report.append({"key": key, "label": label, "ok": False,
                           "error": traceback.format_exc(limit=2)})
            continue

        if key in AI_SECTIONS:
            enricher.enrich(sec.items, key)

        payload = save_section(sec, keep_days=45 if key != "prices" else 400,
                               dedupe=key != "prices")
        report.append({
            "key": key,
            "label": label,
            "ok": any(s.ok for s in sec.sources) if sec.sources else True,
            "items": len(payload["items"]),
            "sources": [s.__dict__ for s in sec.sources],
        })

    write_json("status", {
        "updated_at": now_tpe().isoformat(),
        "duration_sec": round((now_tpe() - started).total_seconds(), 1),
        "sections": report,
        "ai": enricher.cost_note(),
        "leetcode_goal": cfg.get("leetcode", {}).get("weekly_goal", 10),
        "habits": cfg.get("habits", {}).get("track", []),
        "fx_alert_below": cfg.get("finance", {}).get("usd_twd_alert_below"),
    })

    ai = enricher.cost_note()
    log(f"\n完成，耗時 {round((now_tpe() - started).total_seconds())}s"
        f"｜AI 花費 約 NT${ai['twd']}（{ai['input_tokens']}+{ai['output_tokens']} tokens）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
