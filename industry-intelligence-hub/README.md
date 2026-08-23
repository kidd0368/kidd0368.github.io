# 產業情報中樞（Industry Intelligence Hub）

靜態 GitHub Pages 工作台，負責：

- 選取本機 PDF、Excel、圖片與貼上文字。
- 依最新產業分類產生 ChatGPT 分析指令。
- 要求 ChatGPT 同時輸出文字擴張版與結構化 JSON。
- 在同一次對話中由 ChatGPT 直接寫入 GitHub。
- 驗證 JSON 的 taxonomy 版本、日期、單位、來源、claim_id 與衝突狀態。
- 顯示正式研究紀錄、產業節點、公司映射與異動日誌。

## 網址

`https://kidd0368.github.io/industry-intelligence-hub/`

## 分類連動

主檔優先讀取：

`https://raw.githubusercontent.com/kidd0368/cpo-notes/main/data/taxonomy.json`

若遠端讀取失敗，使用內建快照：

`data/taxonomy.cpo.json`

## 安全邊界

GitHub Pages 是靜態公開託管。登入門僅是用戶端存取阻擋，不能取代真正的伺服器身分驗證。原始付費報告、私人訪談及 Dropbox 完整路徑不應提交到公開 repository；GitHub 僅保存可接受公開託管的結構化資料。

## 資料檔

- `data/registry.json`：應用程式、寫入路徑與產業來源。
- `data/records.json`：正式研究紀錄。
- `data/changelog.json`：異動日誌。
- `data/inbox/`：每一任務的完整 JSON。
- `schemas/research-record.schema.json`：研究紀錄 Schema。
