# ✈️ Flights - 機票自動追蹤系統

自動追蹤 Google Flights 機票價格，當票價低於目標價格時發送通知。

## 功能特色

- 🔍 自動爬取 Google Flights 最低票價
- ⏰ 每日台灣時間 10:00 / 22:00 自動執行
- 📧 Email / Telegram Bot 價格警報通知
- 📊 歷史價格趨勢追蹤
- 🌐 Cloudflare Pages 前台介面

## 系統架構

```
GitHub Actions (排程) → Playwright 爬蟲 → JSON 資料儲存 (gh-pages)
                                                    ↓
                                                                                  價格比對引擎 → 通知模組 (Email / Telegram)
                                                                                                                                      ↓
                                                                                                                                                                    Cloudflare Pages 前台 ← 讀取 JSON
                                                                                                                                                                    ```
                                                                                                                                                                    
                                                                                                                                                                    ## 快速開始
                                                                                                                                                                    
                                                                                                                                                                    ### 必要的 GitHub Secrets 設定
                                                                                                                                                                    
                                                                                                                                                                    在 GitHub repo → Settings → Secrets and variables → Actions 中新增：
                                                                                                                                                                    
                                                                                                                                                                    | Secret 名稱 | 說明 |
                                                                                                                                                                    |------------|------|
                                                                                                                                                                    | `TELEGRAM_BOT_TOKEN` | Telegram Bot Token（從 @BotFather 取得）|
                                                                                                                                                                    | `TELEGRAM_CHAT_ID` | 你的 Telegram Chat ID |
                                                                                                                                                                    | `EMAIL_SENDER` | 發送通知的 Gmail 帳號 |
                                                                                                                                                                    | `EMAIL_PASSWORD` | Gmail 應用程式密碼（非登入密碼）|
                                                                                                                                                                    | `EMAIL_RECEIVER` | 接收通知的 Email |
                                                                                                                                                                    
                                                                                                                                                                    ### 訂閱設定
                                                                                                                                                                    
                                                                                                                                                                    編輯 `config/subscriptions.json` 新增追蹤航線：
                                                                                                                                                                    
                                                                                                                                                                    ```json
                                                                                                                                                                    {
                                                                                                                                                                      "subscriptions": [
                                                                                                                                                                          {
                                                                                                                                                                                "id": "tpe-nrt-20261010",
                                                                                                                                                                                      "origin": "TPE",
                                                                                                                                                                                            "destination": "NRT",
                                                                                                                                                                                                  "date": "2026-10-10",
                                                                                                                                                                                                        "target_price": 12000,
                                                                                                                                                                                                              "currency": "TWD",
                                                                                                                                                                                                                    "active": true
                                                                                                                                                                                                                        }
                                                                                                                                                                                                                          ]
                                                                                                                                                                                                                          }
                                                                                                                                                                                                                          ```
                                                                                                                                                                                                                          
                                                                                                                                                                                                                          ## 本地開發
                                                                                                                                                                                                                          
                                                                                                                                                                                                                          ```bash
                                                                                                                                                                                                                          # 安裝依賴
                                                                                                                                                                                                                          pip install -r requirements.txt
                                                                                                                                                                                                                          playwright install chromium
                                                                                                                                                                                                                          
                                                                                                                                                                                                                          # 執行爬蟲（測試）
                                                                                                                                                                                                                          python scraper/main.py --test
                                                                                                                                                                                                                          
                                                                                                                                                                                                                          # 啟動前台開發伺服器
                                                                                                                                                                                                                          cd frontend && python -m http.server 8080
                                                                                                                                                                                                                          ```
                                                                                                                                                                                                                          
                                                                                                                                                                                                                          ## 部署
                                                                                                                                                                                                                          
                                                                                                                                                                                                                          - **爬蟲排程**：自動透過 GitHub Actions 執行，無需任何伺服器
                                                                                                                                                                                                                          - **資料儲存**：JSON 檔案存放於 `gh-pages` 分支
                                                                                                                                                                                                                          - **前台**：連接 Cloudflare Pages 至本 repo，選擇 `frontend/` 目錄
                                                                                                                                                                                                                          
                                                                                                                                                                                                                          ## 技術棧
                                                                                                                                                                                                                          
                                                                                                                                                                                                                          - **爬蟲**：Python 3.11 + Playwright + playwright-stealth
                                                                                                                                                                                                                          - **排程**：GitHub Actions Cron
                                                                                                                                                                                                                          - **資料儲存**：GitHub gh-pages (JSON)
                                                                                                                                                                                                                          - **通知**：smtplib (Gmail) + Telegram Bot API
                                                                                                                                                                                                                          - **前台**：Vanilla JS + Tailwind CSS
                                                                                                                                                                                                                          - **部署**：Cloudflare Pages
                                                                                                                                                                                                                          
                                                                                                                                                                                                                          ## 注意事項
                                                                                                                                                                                                                          
                                                                                                                                                                                                                          - Google Flights 有反爬機制，本系統已加入 stealth 模式與人類行為模擬
                                                                                                                                                                                                                          - 若連續失敗，GitHub Actions 會自動記錄 error log
                                                                                                                                                                                                                          - 免費方案每月 GitHub Actions 額度：2,000 分鐘（遠超本系統需求）
