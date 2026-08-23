# 產業情報中樞：ChatGPT 分析、GitHub 寫入與完成閘門

網頁會依最新產業分類產生完整任務。每次任務包含：

1. 任務 ID、來源日期、附件 SHA-256 與核心問題。
2. 目前 taxonomy version、可用 node_id 與 metric_id。
3. 文字擴張版與 JSON 的必備欄位。
4. ChatGPT 寫入 GitHub 的 repository、branch、record path 與 commit 規則。
5. 寫入後必須通過的 GitHub 回讀與索引收據驗證。

## 固定寫入路徑

- 單筆正式紀錄：`industry-intelligence-hub/data/records/{yyyy}/{mm}/{task_id}.json`
- 研究索引：`industry-intelligence-hub/data/records.json`
- 狀態清單：`industry-intelligence-hub/data/manifest.json`
- 異動日誌：`industry-intelligence-hub/data/changelog.json`
- CPO 分類主檔：`kidd0368/cpo-notes/data/taxonomy.json`

## 寫入原則

- 同一 `task_id` 不重複追加；檔案不存在用 `create_file`，存在則先取得 blob SHA 再用 `update_file`。
- 每次只提交該任務的 record JSON；原始 PDF、圖片、付費報告全文與 GitHub Token 不得寫入。
- 新資料不刪除舊資料；同口徑新版可標示 superseded，異口徑並存並建立 conflict。
- `derived` claims 必須保存公式、輸入 claim_id、假設與敏感度。
- 資料不足時使用 `review_required`，不可為了完成格式而虛構數字。
- taxonomy 的拆分與合併必須建立 migration proposal，不直接搬移歷史 claims。

## GitHub 完成閘門

任務只有在下列條件全部成立後，才可標記為完成：

1. `create_file` 或 `update_file` 回傳非空 commit SHA。
2. 從 `main` 分支重新讀取目標 record，且 `task_id`、`industry_id`、`taxonomy_version_used` 正確。
3. `records.json` 已包含相同 `task_id` 與 record path。
4. 索引項目的 `write_receipt.status` 為 `committed_and_indexed`。
5. `write_receipt.record_commit_sha` 等於該 record 最新修改 commit。
6. `write_receipt.record_content_sha256` 等於 GitHub 上 record 的實際內容雜湊。
7. `manifest.json` 沒有把該 task 或 record path 列為 invalid。

若 record 已提交、但 Action 尚未產生索引收據，狀態只能是 `index_pending`；任何其他失敗皆為 `failed`。本地 JSON、下載檔或只有寫入意圖，都不能視為已提交。
