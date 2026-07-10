# 韓股槓桿數據抓取規格（逆向驗證於 2026-07-09/10）

## 傳輸架構
雲端容器對外網路為白名單制（KOFIA/KRX/Naver/Yahoo 皆不可直連）。
數據經使用者 Chrome（Claude in Chrome 擴充功能）抓取：
1. 在 freesis.kofia.or.kr 任一頁面以 `javascript_tool` 執行同源 fetch
2. 大批量數據打包成 JSON Blob 觸發下載到使用者「下載」資料夾
3. 使用者已連接該資料夾 → `device_stage_files` 進容器；或使用者手動把檔案拖進對話
4. `javascript_tool` 單次回傳上限約 1,000 字元 — 小型當日更新可直接回傳，批量必須走檔案

## KOFIA FreeSIS（無需登入，已驗證 ✅）
- 端點：`POST https://freesis.kofia.or.kr/meta/getMetaDataList.do`
- Content-Type: `application/json`
- Body：`{"dmSearch":{"tmpV40":"1000000","tmpV41":"1","tmpV1":"D","tmpV45":"<起YYYYMMDD>","tmpV46":"<迄YYYYMMDD>","OBJ_NM":"<服務BO>"}}`
- 回應：`{unit, ds1:[{TMPV1:"YYYYMMDD", TMPV2..TMPV9: 數值}], dsmHeader}`，ds1 依日期新→舊
- 單位：百萬韓元（tmpV40=1000000 即以百萬示）
- 全歷史（1998→今，約 7,150 列）單次請求即可取得；深夜（約 KST 01:30-05:00）服務可能無回應，白天正常
- 服務清單（strDivId=MSIS10000000000000，主機= kf.stat.divscu.bo.*BO）：

| OBJ_NM | 內容 | 欄位（TMPV2 起） |
|---|---|---|
| STATSCU0100000070BO | 信用供與餘額推移 | 融資全體/유가증권(KOSPI)/코스닥, 貸株全體/KOSPI/KOSDAQ, 청약자금대출, 예탁증권담보융자 |
| STATSCU0100000060BO | 證市資金推移 | 투자자예탁금, 파생예수금, RP, 위탁매매미수금, 반대매매금액, 반대매매/미수금比(%) |
| STATSCU0100000020BO | 유가증권(KOSPI)市場 | 指數, 成交量(株), 成交額(百萬), 時價總額(百萬), 外國人時總, 外國人比重% |
| STATSCU0100000030BO | 코스닥市場 | 同上（KOSDAQ） |
| STATSCU0100000010BO | 日別主要證市現況 | 單日快照（14列分類彙總，非時序） |
| STATSCU0100000080BO | 信用去來締結株數推移 | 締結株數（千株） |

- 服務定義（欄位名等）：`POST /meta/getSrvData.do`，body `{"dmSearchData":{"strSvrId":"STATSCU0100000070","strDivId":"MSIS10000000000000","app_peron_yn":"Y","language_gb":"KOR","strGetCode":"N"}}`

### 真實錨點（核對用）
- 2026-07-08：融資全體 37,199,867；KOSPI融資 29,239,165；KOSDAQ 7,960,702；예탁금 110,874,403；미수금 1,391,052；반대매매 28,846（비중 2.5%）；KOSPI 7,246.79（-5.34%）成交額 42,465,431 市值 5,931,056,231；KOSDAQ 785.0
- 2026-06-01：융자 37,681,169；2008-01-02：융자 4,439,407

## KRX Data Marketplace（需登入 ⚠️，用戶已授權網域）
- 2026 改版後 `getJsonData.cmd` 未登入回 `400 LOGOUT`
- 登入後（同源）：`POST https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd`
  Content-Type: `application/x-www-form-urlencoded`
- 待驗證的 bld（登入後逐一確認欄位）：
  - `dbms/MDC/STAT/standard/MDCSTAT04601` ETF全種目基本情報（找14檔三星/海力士單股2倍ETF代碼：名稱含 삼성전자/하이닉스 + 레버리지/2X）
  - `dbms/MDC/STAT/standard/MDCSTAT04501` 個別ETF時序（收盤、NAV、順資產總額=AUM、成交額）→ 每檔一請求
  - `dbms/MDC/STAT/standard/MDCSTAT00301` 指數時序（indIdx=1,indIdx2=001=KOSPI）
  - 變動性指數（VKOSPI）bld 待查；未解鎖前以 20 日已實現波動率替代
- ETF指標：AUM合計、距峰值%、距4/30基期未出清比例、跌破發行價(2萬₩)家數、再平衡衝擊=Σ(AUM×2×|日漲跌|)/個股成交額
- 文章錨點：SK海力士槓桿ETF AUM 峰值 167億美元→78億；14檔中13檔破發行價（7/8）

## 更新流程
- 每日增量：抓「最後已存日期+1 → 今日」（幾列而已，可直接經 1KB 通道回傳，無需下載檔案）
- 週期性（每月）重抓近 3 個月覆寫，防修正
- KOFIA 信用數據為 T+1 公布（早上約 08:00-09:00 KST 前後）；指數/成交當日收盤後即有

## 管線
```
data/kofia_kr_leverage_bulk.json  ← 瀏覽器打包（格式見 make_sample_data.py 的 out 結構）
python3 compute_indicators.py data/kofia_kr_leverage_bulk.json [data/krx_etf_indicators.json]
python3 build_dashboard.py        → out/korea_deleverage_dashboard.html（含內嵌原始碼）
```
Cowork artifact id：`korea-deleverage-dashboard`（用 update_artifact 更新）
