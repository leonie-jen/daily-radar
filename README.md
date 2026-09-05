# 📡 每日雷達 daily-radar

一站式看完你在追的所有事情：GT OMSCS 情報、美國 CPT / 簽證風向、自動化測試職缺與文章、
台幣美金匯率、台股美股、商品降價、刷題紀錄。

**每天早上 8 點自動更新，手機瀏覽器打開就能看，零伺服器費用。**

```
GitHub Actions (每天 08:00) → 爬蟲 → data/*.json → commit 回 repo → GitHub Pages
```

---

## 一次性設定（約 10 分鐘）

### 1. 推上 GitHub

```bash
cd daily-radar
gh repo create daily-radar --private --source=. --push
```

（想讓網站公開可見的話用 `--public`。private repo 的 GitHub Pages 需要付費方案。）

### 2. 開啟 GitHub Pages

Repo → **Settings** → **Pages** → Source 選 **GitHub Actions**。

### 3. 把 repo 網址填進前端

編輯 [`site/app.js`](site/app.js) 第一行的 `REPO`，換成你的 repo 網址。
（刷題「＋ 記錄」按鈕靠它連到 issue 表單。）

### 4. 跑第一次

Repo → **Actions** → **每日更新** → **Run workflow**。
跑完之後網站就會出現在 `https://<你的帳號>.github.io/daily-radar/`。

---

## 選配設定

### AI 摘要（建議開，很便宜）

沒設定的話，抓回來的文章只會列出標題；設定之後，Claude 會判斷每一則跟你的目標有沒有關係，
並寫一句中文重點，讓你不用一篇一篇點進去。

Repo → Settings → Secrets and variables → Actions → New repository secret：

| Name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | 你的 API key（[console.anthropic.com](https://console.anthropic.com/settings/keys) 申請） |

**成本**：用 Claude Haiku 4.5，每天約 20~40 篇新文章 → **一個月大約 NT$15~30**。
每次跑完實際花了多少，網站最下面「資料來源狀態」會顯示。
想再省一點就把 `config.yml` 的 `ai.max_items_per_run` 調小。

不設這個 key 也完全能跑，只是沒有摘要與相關性排序。

### 讓 Reddit 穩定抓取（建議開，免費）

OMSCS 的錄取／被拒心得幾乎都在 Reddit，但 Reddit 對沒登入的請求很不友善——
**實測每次跑大約會有一半的 Reddit 來源被回 403**，而且每次掛的還不一樣。
申請一組免費的 API 憑證就能解決：

1. 開 <https://www.reddit.com/prefs/apps> → **create another app...**
2. 類型選 **script**，redirect uri 隨便填 `http://localhost:8080`
3. 建好後，app 名稱下方那串是 **client id**，右邊 `secret` 是 **client secret**
4. 把兩個值加成 repo secrets：`REDDIT_CLIENT_ID`、`REDDIT_CLIENT_SECRET`

沒設定的話會自動退回公開 RSS，抓得到多少算多少。

---

## 平常怎麼用

### 改追蹤內容

只要動 [`config.yml`](config.yml) 一個檔案，push 上去隔天就生效：

| 想改什麼 | 改哪裡 |
|---|---|
| 追蹤的商品、目標價 | `prices.watch` |
| 匯率提醒價位 | `finance.usd_twd_alert_below` |
| 想看的股票 / 指數 | `finance.tickers` |
| 職缺關鍵字 | `jobs.keywords` |
| 要訂閱的部落格 | `jobs.blog_feeds` |
| CPT 相關的搜尋詞 | `cpt.queries` |
| 每週刷題目標 | `leetcode.weekly_goal` |
| AI 每次最多處理幾篇（成本上限） | `ai.max_items_per_run` |

### 記錄刷題

網站「刷題」分頁 → **＋ 記錄今天刷的題** → 填 issue 表單 → 送出。
Actions 會把它寫進 `data/leetcode.json` 並自動關掉 issue。手機上也能填。

### 本機測試

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m scrapers.run_all          # 跑爬蟲
cd site && python3 -m http.server 8899        # 開 http://localhost:8899
```

---

## 資料來源與可靠度

網站最下方的「資料來源狀態」會顯示每個來源今天抓到幾筆、哪個掛了。

| 版面 | 來源 | 狀況 |
|---|---|---|
| OMSCS | Reddit r/OMSCS、GT 官方公告、Google News、Medium、Hacker News | Reddit 建議設 API 憑證 |
| CPT 簽證 | Google News、r/f1visa、ICE 新聞稿、Study in the States | 穩定 |
| 職缺 | 104 搜尋 API | 穩定 |
| 職缺 | LinkedIn guest API | **常被擋，抓不到是正常的** |
| 文章 | hwchiu、安德魯的部落格、cnblogs、dev.to、Google News | 穩定 |
| 匯率 | rter.info（主）、exchangerate-api（備） | 穩定 |
| 台股 | 證交所 OpenAPI + MIS 即時報價 | 穩定 |
| 美股 | CNBC 報價服務 | 穩定 |
| 投資筆記 | harrymemo.com | **最新兩期是付費會員限定**，只會顯示標題與連結 |
| 商品 | PChome（官方 API）、momo、博客來 | 穩定 |
| 商品 | 蝦皮、Amazon | 反爬很兇，成功率低 |

幾個要知道的事：

- **匯率是中間價**，不是銀行牌告的買賣價，實際換匯會差 0.1~0.3 元。
  （台銀牌告頁有 JavaScript 反爬，爬不到。）
- **走勢圖需要時間累積**。匯率與商品價格是每天記一筆，第一天不會有線，跑一週後才好看。
- **GitHub 的排程常誤點 5~30 分鐘**，這是官方已知行為，不是壞掉。
- **抓不到就是抓不到**，程式不會假裝有資料。價格抓失敗時會保留上一次的數字並標成灰色。

## 專案結構

```
config.yml              ← 平常只要改這個
scrapers/
  common.py             HTTP、RSS、去重、存檔、各站節流
  ai.py                 Claude 摘要與相關性評分（可關閉）
  reddit.py             Reddit OAuth，沒憑證時退回 RSS
  omscs.py cpt.py jobs.py finance.py prices.py
  run_all.py            每日主流程
tools/log_leetcode.py   把刷題 issue 存成 JSON
site/                   前端（純 HTML/CSS/JS，沒有打包工具）
data/                   爬蟲產出，由 Actions 自動 commit
```
