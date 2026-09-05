"""用 Claude 判斷相關性 + 產中文摘要。

設計原則：
1. 沒有 ANTHROPIC_API_KEY 就自動降級成關鍵字過濾，整包爬蟲照樣能跑。
2. 摘要過的東西寫進快取，同一篇文章一輩子只花一次錢。
3. 一次送一批（不是一篇一次），把每天的成本壓在幾毛錢。
"""
from __future__ import annotations

import json
import os
from typing import Any

from .common import DATA, log, read_json, write_json, clean_text

CACHE_KEY = "_ai_cache"

# 每個版面告訴 Claude「什麼叫做對我有用」
BRIEFS = {
    "omscs": (
        "使用者正在準備申請 Georgia Tech OMSCS（線上碩士）。"
        "她最在意：錄取／被拒的實際案例與背景條件、錄取率變化、申請時程與規則異動、"
        "課程難度與選課建議、推薦信與 SOP 的實務經驗。"
        "純粹的閒聊、meme、賣課廣告都算不相關。"
    ),
    "cpt": (
        "使用者是台灣人，未來可能到美國念書或工作，關心 F-1 簽證下的實習與工作許可。"
        "她最在意：CPT（尤其 day-1 CPT）政策變化、哪些學校被查或被撤銷 SEVP 資格、"
        "OPT / STEM OPT 規則異動、移民署或法院的相關判決。"
        "一般的留學廣告、代辦業配都算不相關。"
    ),
    "jobs": (
        "使用者是軟體測試／自動化測試工程師（Playwright、QA、SDET）。"
        "她最在意：自動化測試的實務技巧與踩雷經驗、測試框架與工具的新版本、"
        "台灣的相關職缺與薪資行情、面試心得。"
        "純行銷貼文、與測試無關的泛用技術新聞都算不相關。"
    ),
    "finance": (
        "使用者關心台幣兌美金匯率（她之後可能要付美金學費）以及台股美股大盤走勢。"
        "她最在意：匯率走勢的原因與短期展望、大盤與半導體族群的重點變化、"
        "以及可以直接看懂的結論。避免冗長的免責聲明與盤面流水帳。"
    ),
}

SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer", "description": "對應輸入的編號"},
                    "relevance": {
                        "type": "integer",
                        "description": "0-100，這篇對使用者的實際幫助有多大。低於 40 會被隱藏。",
                    },
                    "summary": {
                        "type": "string",
                        "description": "繁體中文兩句話以內的重點。寫結論，不要寫『這篇文章討論了…』。",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "1-3 個繁體中文標籤，例如「錄取心得」「政策異動」「面試」",
                    },
                },
                "required": ["index", "relevance", "summary", "tags"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}


class Enricher:
    def __init__(self, cfg: dict):
        ai_cfg = cfg.get("ai", {})
        self.model = ai_cfg.get("model", "claude-haiku-4-5")
        self.budget = int(ai_cfg.get("max_items_per_run", 40))
        self.cache: dict[str, Any] = read_json(CACHE_KEY, {}) or {}
        self.spent = {"input": 0, "output": 0}
        self.client = None

        if not ai_cfg.get("enabled", True):
            log("AI: 設定關閉，改用關鍵字過濾")
            return
        if not os.environ.get("ANTHROPIC_API_KEY"):
            log("AI: 沒有 ANTHROPIC_API_KEY，改用關鍵字過濾")
            return
        try:
            import anthropic
            self.client = anthropic.Anthropic()
            log(f"AI: 啟用 {self.model}（本次最多 {self.budget} 篇）")
        except ImportError:
            log("AI: 沒裝 anthropic 套件，改用關鍵字過濾")

    # ------------------------------------------------------------------
    def enrich(self, items: list[dict], section: str, batch_size: int = 10) -> None:
        """就地把 summary / relevance / tags 補進 items。"""
        todo = [i for i in items if i["id"] not in self.cache and not i.get("summary")]

        for it in items:
            if cached := self.cache.get(it["id"]):
                it.update(cached)

        if not todo:
            return
        if not self.client:
            for it in todo:
                it.setdefault("relevance", None)   # None = 未評分，前端一律顯示
            return

        todo = todo[: self.budget]
        self.budget -= len(todo)

        for start in range(0, len(todo), batch_size):
            self._score_batch(todo[start : start + batch_size], section)

        write_json(CACHE_KEY, self.cache)

    # ------------------------------------------------------------------
    def _score_batch(self, batch: list[dict], section: str) -> None:
        lines = []
        for n, it in enumerate(batch):
            body = clean_text(it.get("excerpt", ""))[:700]
            lines.append(f"[{n}] 標題：{it['title']}\n    來源：{it.get('source','')}\n    內容：{body or '(只有標題)'}")

        prompt = (
            f"{BRIEFS.get(section, '')}\n\n"
            "以下是今天抓到的內容。請針對每一則評估相關性並寫出中文重點。\n"
            "相關性請嚴格一點：只有標題、看不出實質內容的，relevance 不要超過 50。\n\n"
            + "\n\n".join(lines)
        )

        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}],
                output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
            )
        except Exception as e:                      # noqa: BLE001 — AI 掛掉不該弄死爬蟲
            log(f"  ! AI 呼叫失敗（{type(e).__name__}），這批改用關鍵字：{e}")
            return

        self.spent["input"] += resp.usage.input_tokens
        self.spent["output"] += resp.usage.output_tokens

        try:
            text = next(b.text for b in resp.content if b.type == "text")
            results = json.loads(text)["results"]
        except (StopIteration, KeyError, ValueError) as e:
            log(f"  ! AI 回傳格式看不懂：{e}")
            return

        for r in results:
            idx = r.get("index")
            if not isinstance(idx, int) or not 0 <= idx < len(batch):
                continue
            payload = {
                "summary": r.get("summary", ""),
                "relevance": r.get("relevance"),
                "tags": r.get("tags", []),
            }
            batch[idx].update(payload)
            self.cache[batch[idx]["id"]] = payload

    # ------------------------------------------------------------------
    def cost_note(self) -> dict:
        """Haiku 4.5：input $1 / output $5 每百萬 token。"""
        usd = self.spent["input"] / 1e6 * 1.0 + self.spent["output"] / 1e6 * 5.0
        return {
            "enabled": bool(self.client),
            "model": self.model if self.client else None,
            "input_tokens": self.spent["input"],
            "output_tokens": self.spent["output"],
            "usd": round(usd, 4),
            "twd": round(usd * 32, 2),
        }
