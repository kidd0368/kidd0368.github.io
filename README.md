# 韓國股市去槓桿壓力儀表板

網址：https://kidd0368.github.io/

- 數據源：KOFIA 金融投資協會綜合統計（信用融資、預託金、斷頭、兩市行情，日度，1998至今）
- 每個交易日 台北 17:43 由 GitHub Actions 自動抓數、重算、發布（見 .github/workflows/update.yml）
- 手動更新：Actions 頁籤 → 每日更新韓股去槓桿儀表板 → Run workflow
- 管線：fetch_kofia.py → compute_indicators.py → build_dashboard.py → index.html
