# 產業情報研究系統（Industry Intelligence Hub）

此頁面與 `cpo-notes` 產業筆記分開，負責：

1. 依最新產業分類生成 ChatGPT 分析指令。
2. 將 PDF、圖片、試算表或文字轉為來源可追溯的研究紀錄。
3. 驗證 ChatGPT 回傳 JSON 的公司、期間、單位、證據與分類版本。
4. 累積產能、出貨、報價、稼動率、良率、毛利率、營收、獲利與技術進度。
5. 由 ChatGPT 在同一分析任務中直接提交 JSON 與異動紀錄至 GitHub。

## 正式網址

`https://kidd0368.github.io/industry-intelligence-hub/`

## 分類連動

CPO 分類主檔：

`https://kidd0368.github.io/cpo-notes/data/taxonomy.json`

本頁每次開啟都重新讀取主檔；只要維持穩定 `node_id`，節點改名或移動可直接連動。拆分、合併或停用節點時，必須在 taxonomy 的 `migrations` 建立遷移規則。

## 資料路徑

- `data/records.json`：正式研究紀錄索引
- `data/changelog.json`：異動紀錄
- `data/inbox/<task_id>.json`：每次 ChatGPT 分析的完整輸出
- `schemas/research-record.schema.json`：輸出契約

## 安全邊界

GitHub Pages 是靜態公開託管。頁面密碼只用於降低誤入，不是伺服器端權限控制。付費報告、未公開資料與原始附件不得寫入 GitHub；GitHub 只保存結構化摘要、來源識別資訊與必要證據位置，原始檔留在 Dropbox 或 ChatGPT 對話。
