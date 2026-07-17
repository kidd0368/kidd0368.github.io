# 台股波動率監控(taiwan-vol)

網址:**https://kidd0368.github.io/taiwan-vol/**(上傳後幾分鐘生效)

跟韓國去槓桿儀表板同一套模式:資料 → 指標 → 靜態頁,GitHub Actions 平日自動更新。

## 這一包有什麼

```
.github/workflows/taiwan-vol.yml   排程:平日台北 17:50 與 21:50 各檢查一次
taiwan_vol/
  pipeline.py        update(抓資料) / build(產頁) / selftest(驗算)
  template.html      儀表板模板
  data/
    metrics.csv        2018/1/2 起的每日市場指標(歷史種子來自 CMoney)
    state_returns.csv  近90交易日 × 全股票漲跌幅(算離散度與強勢股用)
    state_caps.csv     個股市值(億)
    state_meta.csv     個股觀測日數(排除上市未滿5日)
taiwan-vol/
  index.html         發布頁(已預先建好,上傳即可看)
```

## 資料來源與方法

- 歷史種子(2018/1–2026/7):CMoney 匯出資料計算。
- 之後每天:證交所 `MI_INDEX`(全部上市個股+加權指數,可回補缺日)為主、
  OpenAPI 為備援;櫃買為多端點自動嘗試(個股與櫃買指數),全部失敗時該欄留空、其餘照常更新。
- 指標定義與本機版「波動率監控.py」完全一致:年化波動率=20/60/252日對數報酬標準差×√252;
  離散度=全市場個股漲跌幅標準差(±10%截尾、排除上市未滿5日);
  強勢股=前20日累積漲幅前15%(市值≥50億,不含當天避免前視偏誤),熱度比=強勢股平均|漲跌|÷全市場母體。
- 市值每月自動校正:每月第一個交易日,自動抓證交所/櫃買公開的「公司實收資本額」,
  以 收盤價×股本÷10 重算全部市值,平時則以日報酬遞推。完全不需人工維護。

## 上傳後要做的事

1. 到 repo 的 **Actions** 頁籤 → 選 `taiwan-vol-update` → **Run workflow** 手動跑一次,
   看 log 確認「上市/上櫃各抓到幾檔」。第一次跑也會順便補上種子日之後缺的交易日。
2. 之後就不用管了。若某天櫃買端點格式改版,log 會顯示警告,個股與加權照常更新。

## 維護備忘

- `python taiwan_vol/pipeline.py selftest`:用狀態檔重算最後一天、對照 metrics.csv,驗證計算一致。
- `python taiwan_vol/pipeline.py calibrate`:手動強制執行一次市值校正(平常不需要,每月會自動跑)。
- GitHub 對 60 天無 commit 的 repo 會暫停排程;本 repo 每個交易日都有自動 commit,不會踩到。
