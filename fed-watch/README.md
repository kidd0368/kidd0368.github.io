# FED 升降息機率儀表板

網址：https://kidd0368.github.io/fed-watch/（密碼保護）

三層機率合成，追蹤未來四次 FOMC（2026/9/16、10/28、12/9、2027/1/27）：

1. **市場層（權重 0.5）**：Kalshi ＋ Polymarket 的 FOMC 決議市場中價，加上金十快訊引用的 CME FedWatch 數字，三者平均。
2. **模型層（權重 0.3）**：透明反應函數。核心PCE缺口／核心CPI動能／油價60天衝擊／就業動能／2年債定價五因子 → 鷹派分數 H → 離散常態映射成五檔動作機率（降≥2碼…升≥2碼）。
3. **專家層（權重 0.2）**：金十快訊裡券商與經濟學家的表態，Claude 每日分類鷹鴿，時間衰減加權；14 天內樣本不足 3 條時此層停用並重新配權。

## 管線

- .github/workflows/fed-watch.yml：每日 4 次（台北 09:23／15:23／21:23／03:23）＋可手動觸發
- scripts/collect.py：抓四個資料源 → 寫入加密資料庫 data/store.enc
- scripts/model.py：反應函數與三層合成
- scripts/build_page.py：讀庫 → 算模型 → 產頁 → AES-256-GCM 加密成 payload.enc.NN
- index.html：解鎖頁（瀏覽器端解密，格式與本站其他加密頁相同）
- Claude 每日 07:30 排程：分類新言論＋寫機率推演 → 提交 → 觸發重建

## Secrets（repo Settings → Secrets → Actions）

- PAGE_PASSWORD：頁面密碼（加密資料庫與頁面 payload 共用）
- JIN10_MCP_TOKEN：金十數據 MCP Token（缺少時自動跳過金十，其餘照跑）

## 維護

- 每次 FOMC 開完，把 config.json 的 meetings 往前滾動一場、更新 current_target
- 金十內容僅供個人研究，全部只存在加密 payload 內，公開 repo 只有密文
- 本頁非投資建議
