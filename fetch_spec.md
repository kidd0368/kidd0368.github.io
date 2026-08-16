# 韓股槓桿數據抓取規格（逆向驗證於 2026-07-09/10，ETF 分項補於 2026-07-26，交叉驗證卡補於 2026-08-01）

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
| STATSCU0100000140BO | 대차거래추이（借券餘額時序，2026-08-16 實測 ✅） | TMPV3 체결주수, TMPV4 상환주수, TMPV5 잔고주수, TMPV6 잔고금액(百萬)；TMPV2 固定「전체」；2008-10-20 起日度，全歷史單次可得（~4,400 列 / 450KB） |
| STATSCU0100000130BO | 대차거래내역（借券逐檔快照，非時序） | 逐股 2,700+ 列，未使用 |

- **STATSCU0100000140BO 兩個陷阱**：①回應尾端附「합계／평균」列，合計欄溢位被伺服器印成 `119794######`（Java DecimalFormat 溢位），整包 JSON 會解析失敗——須先 `re.sub(r"(\d)#+", r"\1", text)` 再 parse，並只保留 8 位日期列；②`tmpV41` 在此 BO 是**股數除數**（1＝주；2、3 會把股數除以 2、3），務必固定 `"1"`。
- 服務定義（欄位名等）：`POST /meta/getSrvData.do`，body `{"dmSearchData":{"strSvrId":"STATSCU0100000070","strDivId":"MSIS10000000000000","app_peron_yn":"Y","language_gb":"KOR","strGetCode":"N"}}`

### 真實錨點（核對用）
- 借券餘額（STATSCU0100000140BO，잔고주수 / 잔고금액百萬）：2026-08-14：3,165,164,593 / 173,189,854；2026-07-31：3,047,164,506 / 155,863,228；2026-06-30：2,915,145,467 / 177,971,885；2026-06-15 金額年高 195,300,558；2026-04-03 股數年高 3,190,798,927；2008-10-20（首列）：562,874,574 / 17,645,454。
  與交易所放空餘額（新聞：2月底15兆→3月初12兆→6月初23兆→7/31 16.73兆→8/11 19兆）方向一致，比率約 8.5-12%。
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

### 高點基準（seed）的來源與界線
`remaining`（＝份額對應資產／高點）與 `aum_vs_peak` 都需要一個「高點」，但本管線 2026-07-24 才開始累積，
高點發生在那之前。故用兩個**已記錄的觀測值**作起始比較基準，而非推估或回測：

| 常數 | 值 | 觀測日 | 內容 |
|---|---|---|---|
| `UNIT_SEED_TRIL` | 26.7 兆₩ | 2026-07-10 | 14 檔正向槓桿 ETF 的份額對應資產（同期由 19.9 兆升至此值） |
| `AUM_SEED_TRIL` | 25.0 兆₩ | 峰值日 | 同一組 ETF 的規模峰值，約合 US$16.7bn |

界線有三條，違反任何一條就不該再沿用這兩個數：
1. **只當下限**——`peak = max(seed, 本管線實測序列)`。管線一旦測到更高值就自動接管，seed 不會壓低高點。
2. **口徑必須同一組**：14 檔正向、發行價 20,000₩、標的限三星電子／SK海力士。`probe.lev_names` 若顯示成分變動，seed 立即失效。
3. **前台必須揭露**：卡片註腳寫明「含本管線啟用前的已記錄觀測值」，不讓讀者誤以為整段高點是本系統實測。

交叉驗算（2026-07-24 首跑）：份額對應資產 14.648 兆＝7.324 億좌×20,000₩，對 26.7 兆為 −45.1%；
規模 8.853 兆對 25.0 兆為 −64.6%。兩者相除得隱含均價／發行價 ≈ 0.604，與逐檔未加權均值 −42.4%
在同一量級（差額來自加權方式不同），口徑自洽。

### 時間預算（重要）
本模組掛在 `fetch_kofia.py` 尾端，與主抓取**共用同一個 workflow step**（`timeout-minutes: 15`）。
來源若無回應，重試累加可達數十分鐘，會讓「計算指標／組裝／提交」三步永不執行＝整份儀表板停更。
故設 `BUDGET_S = 240` 硬上限，逐檔歷史迴圈預留 90 秒、KOFIA 預留 45 秒、市值預留 20 秒，
超時即帶著已取得的部分結果收工。且整段包在 `try` 內，ETF 任何異常都不得中斷主管線。

### 健全性檢查（寧可留空也不輸出錯數字）
- 全體 ETF 規模須落在 50 兆–2,000 兆₩，否則視為抓錯欄位 → `probe.kofia_reject`
- 個股市值須落在 50 兆–1,000 兆₩，否則視為單位解析錯誤 → `probe.mcap_reject`
- 找不到任何正向槓桿 ETF → 直接 raise（命名規則已變更），當日沿用前次時序

### 個股市值：標籤比對而非硬編路徑
`exposure_pct`（＝規模×2／標的市值）的分母來自 Naver 個股端點。端點改版時**欄位路徑常變、韓文標籤不變**，
故 `scan_mcap()` 遞迴掃描整份 JSON 找標著「시가총액」的節點，並依序試三個端點
（`m.stock` integration → `api.stock` integration → `m.stock` basic）。金額字串由 `won_to_eok()` 解析，
支援「340조 3,443억원」「3,403,443억원」「340조원」與純數字四種寫法。
三個端點都沒中時，把各端點的頂層 key 與候選值寫進 `probe.mcap_shape`——
下次執行不必再猜，直接從 probe 看出欄位搬到哪裡。分母缺漏只讓該欄留空，不影響其餘讀數。

### 首跑驗證方式
容器連不上 Naver/KOFIA，故首次 Actions 跑完後回讀
`https://raw.githubusercontent.com/kidd0368/kidd0368.github.io/main/index.html`，
檢查內嵌 `IND.etf.probe`：`list.n`（清單筆數）、`known_missed`（應為空）、`lev_names`（命名規則是否改版）、
`elapsed_s`（時間預算是否夠用）、`hist_truncated`／`kofia_reject`／`mcap_reject`／`mcap_shape`／`fatal`。

**2026-07-26 首跑（run #17，workflow_dispatch）實測**：清單 1,150 筆、`known_missed` 空、
正向 14／反向 2、`elapsed_s` 11.6（預算 240 秒，用掉 5%）、KOFIA 全體 ETF 458.9 兆₩ 且筆數 1,150 與清單自洽、
無 `hist_truncated`／`kofia_reject`／`fatal`。唯一缺口：`under_mcap_tril` 與 `exposure_pct` 為空——
舊版硬編 `totalInfos[].key` 路徑，端點已不是那個形狀，且該路徑不觸發任何 probe 欄位＝靜默失敗。
已改為上節的標籤掃描＋形狀回報。

- 錨點（核對用）：SK海力士槓桿ETF AUM 峰值 167億美元→78億；14檔中13檔破發行價（7/8）

## 交叉驗證卡（IND.ctx，2026-08-01 上線，不計入綜合指數）
儀表板主體量「賣方」（份額註銷、融資去化）；此卡量「接手方」與市場座標。三個來源、零新增基礎設施：

### 1. 市場外資持股比率（KOFIA，零新請求）
`STATSCU0100000020BO`/`030BO` 的 TMPV6/TMPV7 欄（外國人時價總額/比重%）**主管線每天本來就在抓，過去未使用**。
2026-08-01 瀏覽器同源實測核對：20260730 KOSPI 39.242%（=TMPV6÷TMPV5 ✅）、KOSDAQ 12.036%。
`compute_indicators.py` 直接從 bulk 取 `k[6]/q[6]` → `series.kospi_fpct/kosdaq_fpct`（1998 全歷史）＋ `ctx.fpct`（現值與 20 日變化 pp）。

### 2. KOSDAQ 座標（KOFIA 既有序列，僅新增推導）
`ctx.kosdaq`：現值、52 週最高收盤、距高%、**seen_date**＝52週高點之前最近一次收在現值以下的日期
（「跌回哪天的水位」——完全由數據推得，不硬編任何歷史事件日期）。

### 3. 個股外資持股率＋券商股價（Naver siseJson，與 ETF 價格歷史同端點）
- 股票模式的 siseJson 表頭多一欄 `외국인소진율`（外資持股比率%）。**欄位一律以表頭標籤定位**
  （`col_of(hd,"외국인")`／`"종가"`），不硬編位置；表頭快照記入 `probe.ctx_header` 供改版偵錯。
- 個股：005930 三星電子、000660 SK海力士（即槓桿ETF標的）。券商：006800 未來資產證券、039490 Kiwoom證券
  （代碼↔名稱 2026-08-01 經多個公開行情站交叉核對）。
- **每次全量重抓近 400 日、無自建狀態** → 任一天漏跑自癒；與份額時序的「逐日累積」是刻意不同的設計，
  因為這裡的來源本身就提供完整歷史。52 週高由抓回的歷史自身計得，不引用外部欄位。
- 為何用「持股率」不用「買賣超」：持股率是存量、siseJson 一次給整年、口徑單一；
  日買賣超需另一組頁面爬 HTML，多一個易碎面。持股率上升本身就等於累計淨接手。
- 失敗模式：各股獨立 try、budget 守門（<25s 跳過）、`ctx` 整包失敗只損失此卡（前端顯示 pending，不估算）。
- 首跑驗證：回讀 `IND.etf.probe.ctx_header` 應含 `외국인소진율`；`IND.ctx.stock_frgn.stat` 量級核對
  （三星外資率歷史區間約 45-57%）。

### 4. 借券餘額＝對做方（KOFIA `STATSCU0100000140BO`，2026-08-16 上線）
- **為何是借券不是放空餘額**：KRX 放空綜合入口（short.krx.co.kr）2026 起整併進 Data Marketplace，
  未登入直接 302 到登入頁（實測）；本系統不持有帳密。借券餘額是放空的原料庫存、與放空餘額方向一致
  （見上方錨點比對）、更領先、且與主管線同一端點家族——零新增基礎設施。
- **看股數不看金額**：잔고금액＝잔고주수×當日收盤，反彈中金額上升不代表新放空。主指標 `lend_qty`（億股）、
  流量 `lend_net`（체결−상환，億股/日）、比率 `lend_mcap`（金額÷兩市市值 %）三者並列。
- 抓取在 `fetch_kofia.py::pull_lending`，選配：失敗只留 `bulk["lending"]=[]`，compute 產出全 None、
  前端該段顯示 pending；不中斷主管線、不估算。
- 判讀模板（寫進「怎麼看這張圖」）：散戶被清＋外資接＋空方回補＝出清接近完成；份額回升＋借券股數創高＝
  兩邊都在加槓桿、波動未解決。借券餘額同時是懸在頭上的未來回補量（續漲＝軋空燃料、失敗＝順勢追殺）。
- 首跑驗證：`IND.ctx.lending.qty` 應約 31.65（億股，2026-08-14）、`mcap_pct` 約 3-4%；`series.lend_qty`
  非空且 1 年區間可見 6 月底低點→8 月中新高的形狀。

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
