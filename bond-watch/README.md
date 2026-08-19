# 美債殖利率曲線與期限溢價

網址：https://kidd0368.github.io/bond-watch/（密碼保護，同本站其他頁）

回答的問題：長端利率往哪走、是誰在推、風險資產的折現率壓力有多大。
與 fed-watch 分工——fed-watch 管「Fed 會不會動」，本頁管「曲線與期限溢價」。

## 內容

- **折現率壓力指數 0–100**：長端實質利率 35%＋10年期限溢價 25%＋30年名目水位 25%＋30年20日動能 15%。可與 AI 算力基建對帳戰情板對照。
- **完整殖利率曲線**：1M 到 30Y 共 11 個期別，今日 vs 20 日前 vs 60 日前三條線。
- **關鍵利差**：2s10s、5s30s、3M10Y、10s30s。
- **名目利率拆解**：名目 ≈ 實質(TIPS) + 通膨預期，判定 20 日變動由誰驅動。這是本頁的核心——長端上升若來自實質利率與期限溢價（財政赤字、發債供給、外資減持），意涵與通膨推升完全相反。
- **30年殖利率與 10年期限溢價（ACM）走勢**。
- **債市政策事件台帳**：金十快訊自動萃取（回購、拍賣、發債、外資持債、財政部發言等）。

## 資料源

FRED：DGS1MO/3MO/6MO/1/2/3/5/7/10/20/30、DFII5/10/30、T5YIE/T10YIE、THREEFYTP10（紐約聯準會 ACM 期限溢價）、T10Y2Y、T10Y3M、DFF。
金十數據 MCP：債市快訊。

## 管線

與 fed-watch 共用 `.github/workflows/fed-watch.yml`，每日 4 次（台北 09:23／15:23／21:23／03:23）。
`scripts/collect.py` → 加密資料庫 `data/store.enc` → `scripts/build_page.py` → AES-256-GCM 加密成 `payload.enc.NN`。

Secrets：`PAGE_PASSWORD`、`FRED_API_KEY`、`JIN10_MCP_TOKEN`（與 fed-watch 共用）。

本頁非投資建議。
