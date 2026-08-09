# Market Path Engine V1

Market Path Engine is an isolated GitHub Pages prototype at `/market-path/`. It does not modify the existing root dashboard or its data pipeline, and it intentionally excludes EPS forecasts.

The page includes a client-side password gate. Only a SHA-256 digest is committed; the plaintext password is not stored in the repository. Because GitHub Pages is public static hosting, this is a casual-access barrier rather than server-side authorization: a determined technical user can still inspect or bypass client-side controls. Use an authenticated proxy such as Cloudflare Access when true access control is required.

## What V1 covers

- Financial Conditions: Treasury yields, 10-year real yield, broad USD and credit OAS.
- Liquidity: Fed assets, reserve balances, TGA, ON RRP and a clearly labelled net-liquidity proxy.
- Volatility: VIX, VVIX and a free 9D/30D/3M VIX term-curve proxy.
- Positioning: official weekly CFTC plus transparent CTA trend and vol-control risk-target proxies.
- Cross-Asset: S&P 500, Nasdaq Composite, HY OAS, broad USD, WTI and the 10-year yield.
- Event Shock: realized cross-asset shock intensity. Forward event scheduling is deferred until a stable official feed is selected.
- Regime: six-module composite classification.
- Paths: heuristic up/range/down priors for 1–5D, 1–4W and 1–3M.
- Archive: one dated prediction record per model version and automatic validation after each horizon matures.

## Source policy

Official FRED, Cboe and CFTC data are preferred. V1 uses official FRED market series for the cross-asset layer, while keeping the adapter contract simple enough for an existing IBKR connection to replace or extend it later. Missing sources never silently become real observations: the build carries forward the last saved series and reports a fallback or degraded status.

The VIX curve in V1 is the official VIX9D/VIX/VIX3M index-tenor curve, not a full tradable futures strip. CTA, vol-control, Event Shock, Net Liquidity, regime and path probabilities are model proxies. Probabilities are heuristic priors and are not yet statistically calibrated.

## Cross-site ChatGPT analysis bundle

The dashboard action **「11 個網頁資料給 ChatGPT」** builds an analysis bundle locally in the browser. It combines the complete Market Path payload (one page) with the ten published research pages listed under `/github/`, for eleven pages in total. For every page it records the visible research text, HTML tables and safely serializable page-level data objects when available. Collection status is shown page by page; a failed source is recorded as an error instead of being silently omitted.

The shared page password is held in memory only while the bundle is being built and is explicitly excluded from the export. The dashboard does not automatically transmit data to ChatGPT. The user downloads the complete JSON, copies the generated Traditional Chinese analysis instruction, then uploads and submits them manually. A copy-all option is also provided for smaller bundles, but JSON upload is the recommended path for large histories.

## Run locally

```bash
python market_path_engine/engine.py
```

The command updates:

- `market-path/index.html`
- `market_path_engine/data/latest.json`
- `market_path_engine/data/predictions.jsonl`
- `market_path_engine/data/validations.jsonl`

Only Python's standard library is required.

## Archive contract

Schemas live in `market_path_engine/schema/`. Each prediction stores the model version, data date, S&P 500 anchor, regime, module feature scores and all three horizon probabilities. Matured forecasts store realized return/class, multiclass Brier score and log loss. Thresholds are ±1% (5D), ±3% (20D) and ±6% (63D).

## Known V1 gaps

- No EPS estimate inputs by design.
- No paid historical SPX option chain or dealer GEX.
- No claimed “actual” CTA or vol-control dealer exposure.
- No scheduled-event probability feed yet.
- No statistical probability calibration until enough out-of-sample predictions accumulate.
