# kidd0368.github.io

這個 repo 的根目錄只做一件事：把 https://kidd0368.github.io/ 轉到「我的網頁總覽」（https://kidd0368.github.io/github/ ，由 `kidd0368/github` repo 產生）。

原本放在根目錄的「韓股去槓桿壓力儀表板」已於 2026-10-18 移除（含 KOFIA 抓數管線與每日排程）；需要的話可從 git 歷史找回。

同一個 repo 底下的獨立網站（各自有自己的資料夾與工作流程）：

| 網站 | 路徑 | 工作流程 |
|------|------|----------|
| FED 升降息機率儀表板 | `fed-watch/` | `.github/workflows/fed-watch.yml` |
| 美債殖利率曲線與期限溢價 | `bond-watch/` | `.github/workflows/fed-watch.yml`（與 fed-watch 同一支） |
| 台股波動率監控 | `taiwan-vol/`（程式在 `taiwan_vol/`） | `.github/workflows/taiwan-vol.yml` |
| Market Path 市場路徑引擎 | `market-path/`（程式在 `market_path_engine/`） | `.github/workflows/market-path.yml` |
| 產業情報研究系統 | `industry-intelligence-hub/` | `.github/workflows/industry-intelligence-hub-rebuild.yml` |
| 個股融資賣壓風險雷達 | `margin-pressure/` | 手動更新 |
| 籌碼上漲機會追蹤 | `chip-uptrend/` | 手動更新 |
| 暴跌後長紅的歷史機率 | `rebound-stats/` | 一次性研究 |
| 台股崩跌反彈候選研究頁 | `crash-rebound-screen/` | 一次性研究 |
