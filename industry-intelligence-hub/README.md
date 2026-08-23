# 產業情報研究系統

這個目錄是獨立於 `cpo-notes` 的研究資料系統。`cpo-notes` 管理產業分類與上下游關係；本系統管理分析任務、結構化紀錄、數值時間序列與研究查詢。

## 核心資料流

1. 網頁讀取 `/cpo-notes/data/taxonomy.json` 的最新分類。
2. 網頁根據附件與分析類型產生 ChatGPT 指令。
3. ChatGPT 完成文字擴張版與 JSON，直接寫入：
   `industry-intelligence-hub/data/records/YYYY/MM/TASK-*.json`
4. GitHub Actions 執行 `scripts/rebuild_records.py`，重建索引與網站資料。
5. GitHub Pages 顯示最新紀錄。

## 資料邊界

- 原始券商 PDF、圖片、訪談與付費資料只留在 Dropbox。
- GitHub 僅保存結構化研究紀錄與來源識別資料。
- 每筆數字保留資訊日期、指標期間、單位、事實類型、證據與信心。
- 分類名稱可更新，`node_id` 應保持穩定；拆分或合併需使用 migration。

## 主要檔案

- `index.html`：靜態前端
- `data/registry.json`：產業來源與 GitHub 寫入位置
- `schemas/analysis-record.schema.json`：ChatGPT 回傳資料契約
- `data/records/**/*.json`：一任務一檔
- `scripts/rebuild_records.py`：自動重建索引
