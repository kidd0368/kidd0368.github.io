# 美伊戰爭終局追蹤

這是一個每天更新的公開證據儀表板，核心問題不是猜飛彈庫存，而是觀察戰事擴大是否正在產生可驗證的終局條件。

網站預定位置：`https://kidd0368.github.io/iran-war/`

## 追蹤內容

- 最近 72 小時的去重新聞證據項目
- 海峽與商船、軍事行動、基礎設施、外交停火與核問題
- 官方發布、多方報導與單一來源的可信度標記
- 報導中的實際後果、海上壓力、能力衰退與持續反擊訊號
- Brent 原油、S&P 500、台股、VIX 與黃金
- 三種終局路徑：伊朗較弱、伊朗較強、中間僵局

所有自動計數都是「公開證據項目」，不是攻擊、飛彈、無人機或攔截次數，也不是情境機率。

## 資料來源

- Google News RSS：依主題搜尋最近三日報導
- GDELT DOC 2.0：補充全球新聞索引與去重
- Yahoo Finance public chart endpoint：市場價格代理指標
- 人工整理事件：保留停火、商船與戰事擴大的基準時間線

部分官方網站會阻擋自動抓取，因此儀表板會透過新聞索引保留官方公告連結，並在「來源健康度」顯示抓取失敗，不把資料缺口解讀成局勢平靜。

## 更新時間

GitHub Actions 每日 UTC 09:15 執行，約為台北時間 17:15；也可在 Actions 頁面手動執行。

## 本機重建

```text
python iran-war/scripts/fetch_sources.py
python iran-war/scripts/build_dashboard.py
python iran-war/scripts/validate.py
```
