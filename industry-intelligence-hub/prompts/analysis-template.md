# 產業情報中樞：ChatGPT 分析與 GitHub 寫入契約

網頁會依最新產業分類產生完整任務。每次任務包含：

1. 任務 ID、來源日期、附件 SHA-256 與核心問題。
2. 目前 taxonomy version、可用 node_id 與 metric_id。
3. 文字擴張版與 JSON 的必備欄位。
4. ChatGPT 完成分析後直接寫入 GitHub 的路徑與 commit 規則。

## 固定寫入路徑

- 任務原檔：`industry-intelligence-hub/data/inbox/{task_id}.json`
- 正式紀錄：`industry-intelligence-hub/data/records.json`
- 異動日誌：`industry-intelligence-hub/data/changelog.json`
- CPO 分類主檔：`kidd0368/cpo-notes/data/taxonomy.json`

## 寫入原則

- 同一 `task_id` 不重複追加。
- 新資料不刪除舊資料；同口徑新版可標示 superseded，異口徑並存並建立 conflict。
- `derived` claims 必須保存公式、輸入 claim_id 與假設。
- 資料不足時使用 `review_required`，不可為了完成格式而虛構數字。
- taxonomy 的拆分與合併必須建立 migration proposal，不直接搬移歷史 claims。
