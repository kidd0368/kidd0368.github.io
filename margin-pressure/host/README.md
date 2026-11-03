# 融資賣壓風險雷達：主機版

可在 Windows、Mac、Linux 或 Docker 上啟動，使用瀏覽器操作。原有股票查詢、60／120／160 日分析、排序、篩選、深色介面與 CSV 匯出均保留。網址的 `?stock=2492` 也可繼續使用。

主機版沿用原本的加密資料與頁面密碼；密碼由主機驗證，瀏覽器登入後才可讀取分析資料。重新整理保留登入，登入期限 12 小時，右上角可登出。主機重新啟動會清除所有登入。

## 在自己的電腦啟動

需先安裝 Node.js 22 或更新版本，不需安裝 npm 套件。保留整個 `margin-pressure` 資料夾，包含 `index.html`、`payload.enc` 與 `host` 子資料夾。

- Windows：雙擊 `host/start.cmd`，保持視窗開啟。
- Mac：雙擊 `host/start.command`；若系統不允許直接開啟，改用終端機執行下面指令。
- Linux 或終端機：在專案根目錄執行：

```sh
node margin-pressure/host/server.mjs
```

接著開啟 **http://127.0.0.1:8787/?stock=2492**，輸入原本的頁面密碼。

Windows 啟動檔使用 Windows 換行與純 ASCII 指令，可放在包含中文字與空白的資料夾中。如果舊版啟動檔出現亂碼或「不是內部或外部命令」，請以新版 `start.cmd` 覆蓋舊檔。啟動檔會檢查 Node.js 是否已安裝、版本是否至少為 22，以及主機程式是否存在。

程式預設僅供本機連線。如要在內網提供服務，設定 `HOST=0.0.0.0`；對外提供服務時，請使用下述 HTTPS 反向代理設定。

## Docker 啟動

在專案根目錄執行：

```sh
docker compose -f margin-pressure/host/compose.yaml up -d --build
```

開啟 **http://127.0.0.1:8787/?stock=2492**。

```sh
# 查看狀態與主機訊息
docker compose -f margin-pressure/host/compose.yaml ps
docker compose -f margin-pressure/host/compose.yaml logs --tail=30

# 停止
docker compose -f margin-pressure/host/compose.yaml down
```

Docker 使用唯讀容器與非管理員帳號，資料檔以唯讀方式掛載，預設埠口只開放本機。`BIND_ADDRESS` 可調整 Docker 對外監聽的位址。

## 放在自己的網域

在主機上使用 Caddy 或既有 HTTPS 反向代理。以 `radar.example.com` 為例，將環境變數 `PUBLIC_ORIGIN` 設為 `https://radar.example.com`，讓登入 Cookie 使用 Secure 屬性。

```sh
PUBLIC_ORIGIN=https://radar.example.com docker compose -f margin-pressure/host/compose.yaml up -d --build
```

Caddy 設定範例（Caddy 與應用程式在同一主機）：

```caddyfile
radar.example.com {
    reverse_proxy 127.0.0.1:8787
}
```

設定好自己的 DNS、主機防火牆及反向代理後，開啟 `https://radar.example.com/?stock=2492`。

## 資料更新

頁面上方會列出每日應更新的三份 Excel，以及本機最新找到的檔名與匯出日：

| 檔案 | 用途 |
|---|---|
| `chatgpt 計算融資維持率 YYYYMMDD.xlsx` | 近180個交易日的價量、融資買賣與現償資料 |
| `融資融券 YYYYMMDD.xlsx` | 長期融資餘額、歷史回溯 |
| `個股日k線 YYYYMMDD.xlsx` | 長期價格與成交成本 |

三份皆可存於 `Dropbox/DT同步/cmoney/機率分布預測`；專用 `chatgpt 計算融資維持率` 檔也支援 `gpt 維持率追蹤` 第一層。先按檔名日期選最新檔，同日優先主資料夾。同一資料夾同日重複檔會另列提示。永久保留 `gpt 維持率追蹤/備份/融資維持率 20260728.xlsx`，其內2026/07/27最後可用維持率作為固定基準，不需每日更新。

此面板只掃描指定資料夾內的檔名，不讀取或上傳 Excel 內容；檔名匯出日不等於已驗證的最新交易日。主機的實際資料日仍以登入後的加密分析資料為準。檔名日期不同或較網站資料日新時，頁面會提示核對來源與重算流程。

預設依專案所在位置尋找同一 `cmoney` 目錄下的 `機率分布預測`。若安裝位置不同，設定 `INPUT_DIRECTORY` 為該資料夾的絕對路徑。Docker 若需要掃描宿主機 Excel，須另以唯讀方式掛載來源資料夾並設定容器內的 `INPUT_DIRECTORY`；不掛載也可照常查看分析。

目前隨網站保存的資料日期為 **2026-08-14**。主機版沒有新增行情來源，也不會自動產生最新融資數據；原專案的資料更新方式為手動更新。

取得相同格式的新 `payload.enc` 後，替換 `margin-pressure/payload.enc` 並重新啟動主機。若新版資料需要更新前端欄位，也一併更新原本的 `margin-pressure/index.html`。

Docker 掛載外部資料時，可設定 `MARGIN_DATA_FILE` 為資料檔的絕對路徑。替換資料後使用以下指令重建容器，以重新掛載檔案及載入記憶體：

```sh
docker compose -f margin-pressure/host/compose.yaml up -d --force-recreate
```

若連 `index.html` 或主機程式也有更新，需再加上 `--build`。

## 環境變數

| 變數 | 預設值 | 用途 |
|---|---|---|
| `HOST` | `127.0.0.1` | 直接啟動 Node 時的監聽位址；容器內固定為 `0.0.0.0` |
| `PORT` | `8787` | 直接啟動時的埠口；Compose 中為本機對應埠口 |
| `PUBLIC_ORIGIN` | 空白 | HTTPS 公開網址，例如 `https://radar.example.com` |
| `DATA_FILE` | `margin-pressure/payload.enc` | Node 讀取的加密資料位置，建議使用絕對路徑 |
| `TEMPLATE_FILE` | `margin-pressure/index.html` | Node 讀取的原版頁面位置 |
| `INPUT_DIRECTORY` | 同一 `cmoney` 下的 `機率分布預測` | 更新提醒面板掃描的 Excel 來源資料夾 |
| `BIND_ADDRESS` | `127.0.0.1` | Docker 對外綁定的網路位址 |
| `MARGIN_DATA_FILE` | `../payload.enc` | Compose 掛載資料檔的位置，相對於 `host/` 資料夾 |

主機版提供 `/`、`/api/login`、`/api/data`、`/api/input-status`、`/api/logout`、`/healthz`，不會公開資料檔、程式碼或目錄。錯誤登入每個來源 15 分鐘最多嘗試 10 次（成功登入也計入），最多保留 20 個登入狀態。反向代理後的來源以代理位址計算，適用私人使用。

## 驗證

```sh
cd margin-pressure/host
npm test
```

測試使用另外產生的加密樣本，涵蓋加密格式、登入、登出、過期、權杖輪替、跨站請求、密碼嘗試限制、資料檔隔離，以及原有分析程式保留。
