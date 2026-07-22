# ✈️ 機票雷達 FareRadar

自動掃描 Google Flights 未來 3 個月的票價日曆，找出最便宜出發日期，並在票價跌破目標時即時通知。

🌐 **線上展示**：[flights-276.pages.dev](https://flights-276.pages.dev)

---

## 功能特色

| 功能 | 說明 |
|------|------|
| 📅 **日曆掃描** | 每次執行自動掃描訂閱航線未來 3 個月的完整票價日曆 |
| 🗓️ **熱力圖介面** | 前台顯示日曆熱力圖，綠色深淺代表票價高低，一眼看出便宜日期 |
| 🔔 **智慧通知** | 任一日期票價低於目標即觸發 Telegram / Email 通知 |
| ⏰ **自動排程** | 每日台灣時間 10:00 自動執行（GitHub Actions）|
| 🌐 **Web 介面** | Cloudflare Pages 靜態前台，支援新增/刪除訂閱、查看日曆 |

---

## 系統架構

```
[GitHub Actions - 每日 2 次]
└── scraper/main.py
├── 讀取 config/subscriptions.json（航線 + 日期範圍 + 目標價）
├── google_flights.py → search_calendar()
│ ├── 主要：抓取 Google Flights 日曆視圖（aria-label 解析）
│ └── Fallback：每 7 天取樣一次（週掃描模式）
├── tigerair.py → merge_into_calendar()
│ └── 合併台灣虎航官方每日票價（若有更便宜則取代）
├── rapidapi_flights.py → get_calendar_fallback()
│ └── 最終備援：若 Google Flights + Tigerair 都完全抓不到資料，
│ 改用 RapidAPI 上訂閱的機票查詢 API 補資料
├── data_store.py → update_calendar()
│ └── 儲存 price_calendar: {"2026-07-15": 8500, ...}
├── price_engine.py → should_notify_calendar()
│ └── 任一日期 ≤ 目標價 → 觸發通知
└── notifier.py → Telegram / Email

[資料存放]
gh-pages branch → mywu-cloud.github.io/flights/data/
├── prices.json ← 各航線最新日曆快照
└── history.json ← 歷次最低價紀錄

[Cloudflare Worker] flights.tw-mywu.workers.dev
├── GET /subscriptions → 讀取 config/subscriptions.json + sha
└── PUT /subscriptions → 寫回 GitHub（需 sha 防衝突）

[Cloudflare Pages] flights-276.pages.dev
└── frontend/index.html
├── 讀取 Worker API → 訂閱清單
├── 讀取 prices.json → 日曆資料
└── 日曆熱力圖 / 最低價日期 / 新增刪除訂閱
```

---

## 訂閱格式

編輯 `config/subscriptions.json`，或直接透過 Web 介面操作：

```json
{
"subscriptions": [
{
"id": "tpe-nrt",
"origin": "TPE",
"destination": "NRT",
"date_from": "2026-07-01",
"date_to": "2026-09-30",
"target_price": 12000,
"currency": "TWD",
"active": true,
"note": "東京行，暑假前後"
}
]
}
```

| 欄位 | 說明 |
|------|------|
| `id` | 唯一識別碼，格式建議 `origin-destination` |
| `origin` / `destination` | IATA 機場代碼（如 TPE、NRT、KIX）|
| `date_from` / `date_to` | 搜尋日期範圍，建議設 2~3 個月 |
| `target_price` | 目標票價（TWD），低於此值即通知 |
| `active` | `false` 可暫停此航線不抓取 |

---

## 資料格式

### prices.json

```json
{
"updated_at": "2026-06-30T02:00:00Z",
"prices": {
"tpe-nrt": {
"subscription_id": "tpe-nrt",
"origin": "TPE",
"destination": "NRT",
"date_from": "2026-07-01",
"date_to": "2026-09-30",
"price_calendar": {
"2026-07-15": 8500,
"2026-07-22": 9200,
"2026-08-05": 7800
},
"cheapest_date": "2026-08-05",
"cheapest_price": 7800,
"scraped_at": "2026-06-30T02:05:00+08:00"
}
}
}
```

### history.json

```json
{
"history": {
"tpe-nrt": [
{
"cheapest_price": 7800,
"cheapest_date": "2026-08-05",
"dates_found": 45,
"scraped_at": "2026-06-30T02:05:00+08:00"
}
]
}
}
```

---

## 快速開始

### 1. Fork 此 repo

### 2. 設定 GitHub Secrets

在 repo → Settings → Secrets and variables → Actions：

| Secret | 說明 |
|--------|------|
| `GH_TOKEN` | GitHub Personal Access Token（需 `repo` 權限，供 Worker 讀寫訂閱）|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token（從 @BotFather 取得）|
| `TELEGRAM_CHAT_ID` | 你的 Telegram Chat ID |
| `EMAIL_SENDER` | 發送通知的 Gmail 帳號（選填）|
| `EMAIL_PASSWORD` | Gmail 應用程式密碼（選填）|
| `EMAIL_RECEIVER` | 接收通知的 Email（選填）|
| `RAPIDAPI_KEY` | RapidAPI 應用程式金鑰（選填，供最終備援使用）|
| `RAPIDAPI_HOST` | 你訂閱的 RapidAPI 機票查詢服務的 `x-rapidapi-host` 值（選填）|
| `RAPIDAPI_URL` | 該 RapidAPI 服務的日曆/票價查詢端點完整網址（選填）|

> RapidAPI 相關三個 Secret 皆為選填。若未設定，備援機制會直接略過，
> 不影響原有的 Google Flights + Tigerair 抓取流程。由於 RapidAPI 市集上
> 機票查詢類 API 的請求參數與回傳格式各不相同，啟用前請先確認你訂閱的
> 服務的實際規格，必要時調整 `scraper/rapidapi_flights.py` 的解析邏輯。

### 3. 設定 Cloudflare Worker

部署 `src/index.js` 到 Cloudflare Workers，設定環境變數：
- `GH_TOKEN`：同上
- `GH_OWNER`：你的 GitHub 帳號
- `GH_REPO`：repo 名稱（flights）

### 4. 部署前台

Cloudflare Pages 連接此 repo，Build 設定：
- **Build command**：（空白）
- **Build output directory**：`frontend`

### 5. 本地測試

```bash
pip install -r scraper/requirements.txt
playwright install chromium

# 執行爬蟲
python -m scraper.main --test
```

---

## 技術棧

| 層級 | 技術 |
|------|------|
| 爬蟲 | Python 3.11 + Playwright（stealth 模式）|
| 排程 | GitHub Actions Cron（UTC 02:00 = 台灣時間 10:00）|
| 資料 | JSON 存於 `gh-pages` 分支（GitHub Pages 公開讀取）|
| 後端 API | Cloudflare Workers（讀寫 subscriptions.json）|
| 前台 | Vanilla JS，純靜態 HTML（Cloudflare Pages）|
| 通知 | Telegram Bot API + Gmail SMTP |
| 備援資料源 | RapidAPI（僅在 Google Flights + Tigerair 皆抓不到資料時啟用）|

---

## 注意事項

- Google Flights 有反爬機制，已加入 stealth 模式與人類行為模擬（隨機 UA、滾動、延遲）
- 日曆掃描若無法抓取完整日曆視圖，會自動切換為每 7 天取樣的 fallback 模式
- 若 Google Flights 與 Tigerair 皆完全抓不到資料，會再嘗試以 RapidAPI 作為最終備援（需設定對應 Secrets，詳見上方）
- GitHub Actions 免費方案每月 2,000 分鐘，本系統每次約 5~15 分鐘，每日 1 次約 450 分鐘/月
- 訂閱的 `id` 欄位會成為 `prices.json` 的 key，修改 id 等同重置該航線的歷史資料
