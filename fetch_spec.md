# 韓股槓桿數據抓取規格（逆向驗證於 2026-07-09/10，ETF 分項補於 2026-07-26）

## 傳輸架構
**生產環境＝GitHub Actions runner，對外網路無限制**，所有來源直連即可（見 `.github/workflows/update.yml`）。
以下所有端點皆為免登入公開端點，這是刻意的設計約束：本系統不得持有任何帳密或金鑰。

開發容器的對外網路為白名單制（KOFIA/KRX/Naver/Yahoo 皆不可直連），故**端點無法在容器內實測**，
只能靠 Actions 首跑後回讀 `raw.githubusercontent.com/kidd0368/kidd0368.github.io/main/index.html`
內嵌的 `IND.etf.probe` 診斷物件驗證。歷史上曾用過的瀏覽器代抓路徑（已不再需要，僅留備查）：
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

## KRX Data Marketplace（❌ 此路不通，已放棄）
- 2026 改版後 `getJsonData.cmd` 未登入回 `400 LOGOUT`
- **open API 金鑰不對境外申請人開放**（使用者 2026-07-26 確認：「我不能申請KRX 它沒有對外國人開放」）
- 結論：KRX 路徑永久關閉，不要再回頭嘗試。槓桿ETF 分項改由下節的 Naver 公開端點取得。
- 僅存的影響：VKOSPI 官方變動性指數取不到，故以 20 日已實現波動率年化替代（儀表板文案已如實標示）。

## 槓桿ETF 分項（`fetch_etf.py`，2026-07-26 上線，全部免登入 ✅）
標的＝2026-05-27 上市的三星電子／SK海力士單股 2 倍 ETF，發行價一律 **20,000₩**（14 檔正向＋2 檔反向2X）。

**A. Naver 全 ETF 清單（分項主來源）**
`GET https://finance.naver.com/api/sise/etfItemList.nhn?etfType=0&targetColumn=market_sum&sortOrder=desc`
回 `{"result":{"etfItemList":[{itemcode,itemname,nowVal,nav,marketSum,changeRate,amonut,...}]}}`
- 單位：`marketSum`＝억원、`amonut`＝백만원（**來源端拼字即為 amonut，非 amount**，程式兩者皆試）、`nowVal`/`nav`＝₩
- 篩選採**名稱為準**：需同時命中標的（삼성전자／하이닉스）與 레버리지/2X；`인버스` 歸反向。
  `KNOWN` 代碼清單**不作為納入依據**（來源非一手，誤納會污染總量），僅在 probe 回報 `known_missed` 供校正。

**B. Naver 個股日線（跌破發行價家數的時序）**
`GET https://api.finance.naver.com/siseJson.naver?symbol=<code>&requestType=1&startTime=&endTime=&timeframe=day`
- 回**單引號偽 JSON**，需 `text.replace("'", '"')` 後再 parse；第 0 列為表頭
- 備援：`https://fchart.stock.naver.com/sise.nhn?symbol=<code>&timeframe=day&count=400&requestType=0`（XML，`data="YYYYMMDD|o|h|l|c|v"`）

**C. 全體 ETF 規模（「佔全體 ETF 比重」的分母）**：見文末 KOFIA 基金統計節。
**D. 標的市值（風險敞口分母，選配）**：`GET https://m.stock.naver.com/api/stock/<code>/integration`，取 `totalInfos` 中 `시가총액`（억원）。三星＝005930、SK海力士＝000660。

### 核心口徑：看份額不看規模
規模（市值口徑）會被淨值暴跌灌水成「已出清」的假象。真實槓桿倉位要剝除價格效果：
```
units_eok       = marketSum / price          # 億좌
unit_value_tril = units_eok × 20000 / 1e4    # 兆₩ ← 份額對應資產
aum_tril        = marketSum / 1e4            # 兆₩ ← 總規模
```
手驗：30,000억원 ÷ 10,000₩ = 3억좌；3e8 좌 × 20,000₩ = 6e12₩ = 6 兆₩ ✅
兩線背離＝規模縮水全來自淨值回落、份額並未退場（＝槓桿還在）。

### 狀態延續（無公開歷史檔）
規模與份額**沒有公開歷史**，只能自首次執行起逐日累積，且 workflow 的提交步驟只 `git add index.html`
（`data/` 不進版控）。故狀態載體＝**上一版 `index.html` 內嵌的 `IND.etf.series`**：
`load_prev()` 找 `const IND = ` 後用 `json.JSONDecoder().raw_decode()` 取回，合併今日點再重新內嵌。
此設計不需改動 workflow。價格歷史則每次重抓（Naver 有完整日線），無累積問題。
**不以估算值回填**——觀測點不足時卡片明說「目前 N 個觀測點」。

### 時間預算（重要）
本模組掛在 `fetch_kofia.py` 尾端，與主抓取**共用同一個 workflow step**（`timeout-minutes: 15`）。
來源若無回應，重試累加可達數十分鐘，會讓「計算指標／組裝／提交」三步永不執行＝整份儀表板停更。
故設 `BUDGET_S = 240` 硬上限，逐檔歷史迴圈預留 90 秒、KOFIA 預留 45 秒、市值預留 20 秒，
超時即帶著已取得的部分結果收工。且整段包在 `try` 內，ETF 任何異常都不得中斷主管線。

### 健全性檢查（寧可留空也不輸出錯數字）
- 全體 ETF 規模須落在 50 兆–2,000 兆₩，否則視為抓錯欄位 → `probe.kofia_reject`
- 個股市值須落在 50 兆–1,000 兆₩，否則視為單位解析錯誤 → `probe.mcap_reject`
- 找不到任何正向槓桿 ETF → 直接 raise（命名規則已變更），當日沿用前次時序

### 首跑驗證方式
容器連不上 Naver/KOFIA，故首次 Actions 跑完後回讀
`https://raw.githubusercontent.com/kidd0368/kidd0368.github.io/main/index.html`，
檢查內嵌 `IND.etf.probe`：`list.n`（清單筆數）、`known_missed`（應為空）、`lev_names`（命名規則是否改版）、
`elapsed_s`（時間預算是否夠用）、`hist_truncated`／`kofia_reject`／`mcap_reject`／`fatal`。

- 文章錨點（核對用）：SK海力士槓桿ETF AUM 峰值 167億美元→78億；14檔中13檔破發行價（7/8）

## 更新流程
- 每日增量：抓「最後已存日期+1 → 今日」（幾列而已，可直接經 1KB 通道回傳，無需下載檔案）
- 週期性（每月）重抓近 3 個月覆寫，防修正
- KOFIA 信用數據為 T+1 公布（早上約 08:00-09:00 KST 前後）；指數/成交當日收盤後即有

## 管線
```
python3 fetch_kofia.py            → data/kofia_kr_leverage_bulk.json
                                    （尾端 try 內呼叫 fetch_etf.main() → data/krx_etf_indicators.json）
python3 compute_indicators.py data/kofia_kr_leverage_bulk.json [data/krx_etf_indicators.json]
                                  → out/indicators.json（ETF 檔預設路徑即上者，存在才讀）
python3 build_dashboard.py        → out/korea_deleverage_dashboard.html
cp out/korea_deleverage_dashboard.html index.html   ← 唯一進版控的產物（＝ETF 時序的狀態載體）
```
- ETF 分項接進綜合指數：`etf["remaining"]` 啟用 15 分的分項，其餘權重乘 0.85 重新歸一；
  `etf["aum_d5"]` 供訊號① 判定（規模 5 日萎縮達 2%，需時序滿 6 日才有值）。
- 檔名 `krx_etf_indicators.json` 沿用歷史命名，內容已與 KRX 無關。
- Cowork artifact id：`korea-deleverage-dashboard`（用 update_artifact 更新）

## KOFIA 基金統計（2026-07-20 探勘）
- 특정유형펀드현황（特定類型基金現況，含 ETF 整體規模）：
  `POST /meta/getMetaDataList.do`，body `{"dmSearch":{"tmpV40":"100000000","tmpV41":"1","tmpV34":"<YYYYMMDD單日>","tmpV11":"","tmpV7":"1","OBJ_NM":"STATFND0100100140BO"}}`
  回傳各特定類型列（含 ETF：檔數與規模，單位=tmpV40 억원）。單日快照制，歷史需逐日迴圈。
  用途：槓桿ETF/整體ETF 比率的「分母」。假日/未公布日回空陣列，故程式自 asof 往前找最多 6 天。
  分子（槓桿ETF 單獨規模）已由 Naver 清單解決，不再需要 KRX。
