# 產業情報中樞：ChatGPT 分析、審核語意與 GitHub 寫入契約

網頁依最新 taxonomy 產生任務；每個任務要同時完成文字擴張版、結構化 JSON、GitHub 寫入與回讀驗證。

## 來源判定

1. 公司與報告身分依正文公司全名、股票代碼、財務表與業務內容判定。
2. 檔名只作原檔追溯。檔名錯誤、截斷或與正文不同，不算研究衝突，也不產生使用者待辦。
3. 不同來源的發布日、事件日、引用日與更新日分開保存並說明意義；日期不同本身不是衝突。
4. 不同券商估計、公司展望與官方實際值並存是正常的來源口徑差異。

## 審核狀態

- `accepted`：分析與寫入完成，沒有需要使用者選擇的事項。可同時存在來源註記與重要口徑註記。
- `review_required`：至少存在一項未解決且 `requires_user_action=true` 的 `review_items`。
- `rejected`：紀錄本身無法合法或結構化保存。

每個 `review_item` 必須包含明確問題、需要使用者決定的原因、選項與系統建議。沒有這些內容，就不得顯示「待你確認」。

同一報告內部數字或年度標示不一致時，系統應先依主文、估值公式、表格標題與其他證據選擇可防禦的主要解讀，替代口徑保留於 `important_notes`；除非沒有合理預設且會污染下游數字，否則不轉嫁給使用者。

## 固定寫入路徑

- 正式紀錄：`industry-intelligence-hub/data/records/{yyyy}/{mm}/{task_id}.json`
- 研究索引：`industry-intelligence-hub/data/records.json`
- 異動日誌：`industry-intelligence-hub/data/changelog.json`
- 狀態清單：`industry-intelligence-hub/data/manifest.json`
- CPO taxonomy：`kidd0368/cpo-notes/data/taxonomy.json`

## 寫入原則

- 同一 `task_id` 不重複追加。
- 新資料不刪除舊資料；同口徑新版可標示 superseded，異口徑分開保存並註明來源。
- `derived_metrics` 必須保存公式、輸入 claim ID、假設與敏感度。
- 資料不足時保留空值，不得為完成格式而虛構數字。
- taxonomy 拆分與合併建立 proposal，不直接搬移歷史 claims。
- 只有 record、commit、records.json 收據、內容 SHA-256 與 manifest 全部通過，才可宣告 GitHub 寫入完成。
