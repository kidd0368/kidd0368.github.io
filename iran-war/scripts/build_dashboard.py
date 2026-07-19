#!/usr/bin/env python3
"""Build the self-contained Iran war terminal dashboard."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUTPUT = ROOT / "index.html"


def load_json(name: str) -> dict:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def safe_json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


HTML = r'''<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="美伊戰爭終局每日追蹤：以公開證據觀察海峽安全、軍事韌性、談判執行與市場壓力。">
  <title>美伊戰爭終局追蹤</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #07100f;
      --panel: #0d1917;
      --panel-2: #11211e;
      --line: #24413b;
      --text: #eef7f3;
      --muted: #9fb5ad;
      --green: #43d19e;
      --amber: #ffc857;
      --red: #ff6b6b;
      --blue: #65a6ff;
      --chip: #17312b;
      --shadow: 0 18px 55px rgba(0,0,0,.24);
    }
    :root[data-theme="light"] {
      color-scheme: light;
      --bg: #eef3f0;
      --panel: #ffffff;
      --panel-2: #f6faf8;
      --line: #cbd9d3;
      --text: #10211b;
      --muted: #5f736b;
      --green: #087f5b;
      --amber: #a66500;
      --red: #c43f3f;
      --blue: #286cc1;
      --chip: #e0eee8;
      --shadow: 0 16px 44px rgba(23,54,43,.10);
    }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      margin: 0;
      background:
        radial-gradient(circle at 86% -10%, rgba(67,209,158,.13), transparent 29rem),
        radial-gradient(circle at -8% 24%, rgba(101,166,255,.08), transparent 28rem),
        var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans TC", sans-serif;
      line-height: 1.55;
    }
    a { color: inherit; }
    button { font: inherit; }
    .shell { width: min(1440px, calc(100% - 32px)); margin: 0 auto; padding: 26px 0 64px; }
    .topbar { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-bottom: 22px; }
    .brand { display: flex; align-items: center; gap: 12px; }
    .brand-mark { width: 14px; height: 14px; border-radius: 50%; background: var(--green); box-shadow: 0 0 0 7px rgba(67,209,158,.12); }
    .brand strong { letter-spacing: .05em; }
    .brand small { display: block; color: var(--muted); font-size: 12px; }
    .top-actions { display: flex; gap: 8px; align-items: center; }
    .pill, .icon-btn, .filter-btn {
      border: 1px solid var(--line); background: var(--panel); color: var(--muted); border-radius: 999px;
      padding: 8px 12px; text-decoration: none;
    }
    .icon-btn, .filter-btn { cursor: pointer; }
    .icon-btn:hover, .filter-btn:hover, .filter-btn.active { border-color: var(--green); color: var(--text); }
    .hero {
      position: relative; overflow: hidden; border: 1px solid var(--line); background: linear-gradient(135deg, var(--panel), var(--panel-2));
      padding: clamp(24px, 4vw, 54px); border-radius: 28px; box-shadow: var(--shadow); margin-bottom: 18px;
    }
    .hero::after { content: ""; position: absolute; width: 280px; height: 280px; border: 1px solid rgba(67,209,158,.18); border-radius: 50%; right: -90px; top: -105px; box-shadow: 0 0 0 48px rgba(67,209,158,.025), 0 0 0 96px rgba(67,209,158,.018); }
    .eyebrow { margin: 0 0 13px; color: var(--green); font-size: 12px; font-weight: 800; letter-spacing: .14em; text-transform: uppercase; }
    h1 { max-width: 1180px; font-size: clamp(34px, 4.5vw, 58px); line-height: 1.08; letter-spacing: -.04em; margin: 0 0 22px; }
    .hero-summary { max-width: 1080px; color: var(--text); font-size: clamp(17px, 2vw, 21px); line-height: 1.75; margin: 0; }
    .hero-explanation { position: relative; z-index: 1; display: grid; margin-top: 30px; border-top: 1px solid var(--line); }
    .hero-point { display: grid; grid-template-columns: 92px minmax(0, 1fr); gap: 20px; padding: 20px 0; border-bottom: 1px solid var(--line); }
    .hero-point-label { align-self: start; width: fit-content; border: 1px solid var(--line); border-radius: 999px; padding: 5px 10px; color: var(--green); background: var(--chip); font-size: 12px; font-weight: 800; letter-spacing: .08em; }
    .hero-point h2 { margin: 0 0 6px; font-size: 18px; line-height: 1.35; }
    .hero-point p { max-width: 1120px; margin: 0; color: var(--muted); font-size: 15px; line-height: 1.78; }
    .hero-meta { position: relative; z-index: 1; display: grid; grid-template-columns: .8fr 1.4fr 1.2fr; gap: 12px; margin-top: 22px; }
    .hero-meta-item { border: 1px solid var(--line); border-radius: 14px; padding: 14px 16px; background: rgba(255,255,255,.015); }
    .hero-meta-item small { display: block; margin-bottom: 5px; color: var(--green); font-size: 11px; font-weight: 800; letter-spacing: .08em; }
    .hero-meta-item strong, .hero-meta-item span { display: block; color: var(--muted); font-size: 13px; line-height: 1.65; }
    .hero-meta-item strong { color: var(--text); }
    .grid { display: grid; gap: 16px; }
    .thesis-card { padding: 26px; }
    .thesis-card > h3 { margin: 0 0 18px; max-width: 1040px; font-size: clamp(20px, 2.7vw, 30px); line-height: 1.25; }
    .thesis-flow { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; counter-reset: thesis; }
    .thesis-step { position: relative; min-height: 150px; padding: 18px; border: 1px solid var(--line); border-radius: 16px; background: var(--panel-2); }
    .thesis-step::before { counter-increment: thesis; content: counter(thesis); display: grid; place-items: center; width: 27px; height: 27px; margin-bottom: 14px; border-radius: 50%; background: var(--chip); color: var(--green); font-weight: 800; font-size: 12px; }
    .thesis-step:not(:last-child)::after { content: "→"; position: absolute; right: -18px; top: 58px; z-index: 2; color: var(--green); font-weight: 900; }
    .thesis-step strong { display: block; margin-bottom: 7px; font-size: 16px; }
    .thesis-step p { margin: 0; color: var(--muted); font-size: 13px; }
    .thesis-note { margin: 17px 2px 0; color: var(--muted); font-size: 13px; }
    .analysis-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .analysis-card { padding: 24px; position: relative; overflow: hidden; }
    .analysis-card::before { content: ""; position: absolute; inset: 0 auto 0 0; width: 3px; background: var(--accent); }
    .analysis-kicker { display: flex; align-items: center; justify-content: space-between; gap: 12px; color: var(--accent); font-size: 12px; font-weight: 800; letter-spacing: .06em; }
    .analysis-kicker span:last-child { color: var(--muted); font-weight: 600; letter-spacing: 0; }
    .analysis-card h3 { margin: 12px 0 9px; font-size: 20px; }
    .analysis-card p { margin: 0; color: var(--muted); font-size: 15px; }
    .watch-card { margin-top: 16px; padding: 22px 24px; display: grid; grid-template-columns: 220px 1fr; gap: 20px; }
    .watch-card h3 { margin: 0 0 5px; }
    .watch-card p { margin: 0; color: var(--muted); font-size: 12px; }
    .watch-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px 18px; margin: 0; padding-left: 20px; color: var(--muted); font-size: 13px; }
    .guardrail { margin-top: 16px; padding: 18px 22px; border-left: 3px solid var(--amber); color: var(--muted); font-size: 13px; }
    .regional-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .kpi-grid { grid-template-columns: repeat(5, minmax(0, 1fr)); margin: 18px 0; }
    .card { border: 1px solid var(--line); background: var(--panel); border-radius: 20px; box-shadow: var(--shadow); }
    .kpi { min-height: 142px; padding: 19px; display: flex; flex-direction: column; justify-content: space-between; }
    .kpi-label { color: var(--muted); font-size: 13px; }
    .kpi-value { font-variant-numeric: tabular-nums; font-size: 38px; line-height: 1; font-weight: 760; margin: 15px 0 8px; }
    .kpi-note { color: var(--muted); font-size: 12px; }
    .section { margin-top: 28px; }
    .section-head { display: flex; align-items: end; justify-content: space-between; gap: 18px; margin: 0 2px 13px; }
    .section-head h2 { font-size: clamp(22px, 3vw, 32px); letter-spacing: -.025em; margin: 0; }
    .section-head p { max-width: 670px; color: var(--muted); margin: 4px 0 0; font-size: 14px; }
    .scenario-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .scenario { padding: 23px; position: relative; overflow: hidden; }
    .scenario::before { content: ""; position: absolute; inset: 0 0 auto; height: 3px; background: var(--accent); }
    .scenario h3 { margin: 4px 0 10px; font-size: 21px; }
    .scenario p { color: var(--muted); font-size: 14px; min-height: 66px; }
    .scenario-update { display: inline-flex; margin-bottom: 6px; border-radius: 999px; padding: 4px 9px; background: color-mix(in srgb, var(--accent) 14%, transparent); color: var(--accent); font-size: 11px; font-weight: 800; }
    .route-read { display: grid; gap: 10px; background: var(--panel-2); padding: 14px; border-radius: 13px; margin: 14px 0 18px; }
    .route-read div { color: var(--muted); font-size: 12px; }
    .route-read strong { display: block; margin-bottom: 3px; color: var(--text); font-size: 12px; }
    .market-interpretation { padding: 20px 22px; margin-bottom: 16px; }
    .market-interpretation h3 { margin: 0 0 7px; font-size: 18px; }
    .market-interpretation p { margin: 0; color: var(--muted); font-size: 14px; }
    details { border-top: 1px solid var(--line); padding: 11px 0 0; margin-top: 8px; }
    summary { cursor: pointer; font-size: 13px; font-weight: 700; }
    details ul { margin: 10px 0 4px; padding-left: 20px; color: var(--muted); font-size: 13px; }
    .market-grid { grid-template-columns: repeat(5, minmax(0, 1fr)); }
    .market { padding: 18px; min-height: 160px; }
    .market-top { display: flex; justify-content: space-between; gap: 9px; color: var(--muted); font-size: 12px; }
    .market-value { font-size: 25px; font-weight: 760; margin-top: 10px; font-variant-numeric: tabular-nums; }
    .change { margin-left: 8px; font-size: 13px; font-weight: 700; }
    .change.up { color: var(--red); }
    .change.down { color: var(--green); }
    .spark { width: 100%; height: 44px; display: block; margin-top: 13px; }
    .two-col { grid-template-columns: 1.2fr .8fr; }
    .chart-card, .health-card { padding: 22px; }
    .bar-chart { display: grid; grid-template-columns: repeat(7, 1fr); gap: 9px; height: 220px; align-items: end; padding-top: 24px; }
    .bar-day { min-width: 0; text-align: center; }
    .bar-stack { height: 166px; display: flex; flex-direction: column-reverse; justify-content: flex-start; gap: 3px; }
    .bar { min-height: 3px; border-radius: 5px 5px 2px 2px; opacity: .9; }
    .bar-day small { color: var(--muted); font-size: 10px; }
    .legend { display: flex; flex-wrap: wrap; gap: 8px 14px; margin-top: 13px; color: var(--muted); font-size: 11px; }
    .legend i { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 5px; }
    .health-list { display: grid; gap: 9px; margin-top: 14px; }
    .health-row { display: flex; justify-content: space-between; gap: 10px; border-bottom: 1px solid var(--line); padding-bottom: 9px; font-size: 12px; }
    .health-row:last-child { border-bottom: 0; }
    .ok { color: var(--green); }
    .fail { color: var(--red); }
    .timeline { padding: 0 22px; }
    .timeline-item { display: grid; grid-template-columns: 112px 1fr; gap: 18px; padding: 20px 0; border-bottom: 1px solid var(--line); }
    .timeline-item:last-child { border-bottom: 0; }
    .timeline-date { color: var(--green); font-size: 13px; font-variant-numeric: tabular-nums; }
    .timeline h3 { margin: 0 0 6px; font-size: 17px; }
    .timeline p { color: var(--muted); margin: 0 0 9px; font-size: 14px; }
    .source-links { display: flex; gap: 8px; flex-wrap: wrap; }
    .source-links a { color: var(--blue); font-size: 12px; text-decoration: none; }
    .source-links a:hover { text-decoration: underline; }
    .filters { display: flex; flex-wrap: wrap; gap: 7px; margin-bottom: 12px; }
    .filter-btn { padding: 7px 11px; font-size: 12px; }
    .evidence-wrap { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; min-width: 820px; }
    th, td { border-bottom: 1px solid var(--line); padding: 14px 12px; text-align: left; vertical-align: top; }
    th { position: sticky; top: 0; background: var(--panel); color: var(--muted); font-size: 11px; letter-spacing: .04em; text-transform: uppercase; }
    td { font-size: 13px; }
    td.title-cell { max-width: 540px; }
    td.title-cell a { text-decoration: none; font-weight: 650; }
    td.title-cell a:hover { color: var(--blue); }
    .tag { display: inline-flex; align-items: center; white-space: nowrap; border: 1px solid var(--line); background: var(--chip); color: var(--muted); border-radius: 999px; padding: 3px 8px; font-size: 11px; }
    .confidence { font-weight: 700; }
    .confidence.official { color: var(--green); }
    .confidence.multi { color: var(--blue); }
    .evidence-footer { display: flex; justify-content: space-between; color: var(--muted); font-size: 11px; padding-top: 13px; }
    .method-grid { grid-template-columns: repeat(3, 1fr); }
    .method-card { padding: 21px; }
    .method-card h3 { margin: 0 0 9px; font-size: 15px; }
    .method-card p, .method-card li { color: var(--muted); font-size: 13px; }
    .method-card ul { margin: 8px 0 0; padding-left: 18px; }
    footer { color: var(--muted); font-size: 11px; text-align: center; margin-top: 28px; }
    .empty { color: var(--muted); padding: 24px 4px; }
    @media (max-width: 1080px) {
      .kpi-grid { grid-template-columns: repeat(3, 1fr); }
      .market-grid { grid-template-columns: repeat(3, 1fr); }
      .scenario-grid, .method-grid, .regional-grid { grid-template-columns: 1fr; }
      .analysis-grid { grid-template-columns: 1fr; }
      .thesis-flow { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .thesis-step:nth-child(2)::after { display: none; }
    }
    @media (max-width: 760px) {
      .shell { width: min(100% - 20px, 1440px); padding-top: 15px; }
      .topbar { align-items: flex-start; }
      .pill { display: none; }
      .hero { border-radius: 21px; padding: 24px 20px; }
      .kpi-grid { grid-template-columns: repeat(2, 1fr); }
      .market-grid, .two-col { grid-template-columns: 1fr; }
      .timeline-item { grid-template-columns: 1fr; gap: 5px; }
      .watch-card { grid-template-columns: 1fr; }
      .watch-list { grid-template-columns: 1fr; }
      .section-head { align-items: flex-start; flex-direction: column; }
      .thesis-flow { grid-template-columns: 1fr; }
      .thesis-step { min-height: 0; }
      .thesis-step::after { display: none; }
      .hero-meta { grid-template-columns: 1fr; }
    }
    @media (max-width: 430px) {
      .kpi-grid { grid-template-columns: 1fr; }
      h1 { font-size: 36px; }
      .hero-point { grid-template-columns: 1fr; gap: 10px; padding: 18px 0; }
      .kpi { min-height: 118px; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header class="topbar">
      <div class="brand"><span class="brand-mark" aria-hidden="true"></span><div><strong>IRAN WAR TERMINAL</strong><small>公開證據 × 情境推演</small></div></div>
      <div class="top-actions"><span class="pill" id="refreshPill">更新中</span><button class="icon-btn" id="themeButton" aria-label="切換顯示模式">◐</button></div>
    </header>

    <section class="hero">
      <p class="eyebrow">今日分析結論</p>
      <h1 id="headline"></h1>
      <p class="hero-summary" id="assessmentSummary"></p>
      <div class="hero-explanation" id="heroExplanation" aria-label="今日結論的完整推理"></div>
      <div class="hero-meta">
        <div class="hero-meta-item"><small>目前階段</small><strong id="phaseValue"></strong></div>
        <div class="hero-meta-item"><small>判讀限制</small><span id="limitValue"></span></div>
        <div class="hero-meta-item"><small>核心問題</small><span id="questionValue"></span></div>
      </div>
    </section>

    <section class="section">
      <div class="section-head"><div><h2>核心推演：擴大如何可能通往終局</h2><p>戰事擴大不是終局本身；它的作用是迫使雙方用真實成本揭露底牌並修正誤判。</p></div></div>
      <article class="card thesis-card">
        <h3 id="thesisTitle"></h3>
        <div class="thesis-flow" id="thesisFlow"></div>
        <p class="thesis-note">兩種清楚答案都可能打開終局：伊朗底牌有限，或美國確認軍事手段有極限。最危險的是答案長期模糊，讓雙方都相信再打一點會更有利。</p>
      </article>
    </section>

    <section class="section">
      <div class="section-head"><div><h2>今日終局推演</h2><p>固定回答六個問題：揭露了什麼、還不知道什麼、美方可能學到什麼、靠近哪條路、協議能否執行，以及擴大的雙面作用。</p></div></div>
      <div class="grid analysis-grid" id="analysisGrid"></div>
      <article class="card guardrail" id="evidenceGuardrail"></article>
      <article class="card watch-card"><div><h3>什麼證據會推翻今天的結論</h3><p>不是列一般觀察項目，而是列出足以讓終局路徑改變的條件。</p></div><ul class="watch-list" id="watchList"></ul></article>
    </section>

    <section class="section">
      <div class="section-head"><div><h2>三條終局路徑</h2><p>訊號數是新聞證據佇列的自動標記，只用於安排閱讀優先順序，不是情境機率或戰力統計。</p></div></div>
      <div class="grid scenario-grid" id="scenarioGrid"></div>
    </section>

    <section class="section">
      <div class="section-head"><div><h2>區域擴散如何改變實力測試</h2><p>以色列、紅海第二咽喉與非對稱戰術既可能加速底牌揭露，也可能把可收斂戰爭變成多戰線僵局。</p></div></div>
      <div class="grid regional-grid" id="regionalGrid"></div>
    </section>

    <section class="section">
      <div class="section-head"><div><h2>公開證據儀表</h2><p>這些數字放在推演之後，只用來佐證與安排人工閱讀，不再直接產生戰力或終局結論。</p></div></div>
      <div class="grid kpi-grid" id="kpiGrid" aria-label="最近24小時公開證據指標"></div>
    </section>

    <section class="section">
      <div class="section-head"><div><h2>市場壓力表</h2><p>市場只反映風險定價，不直接證明軍事成敗；方向與事件應交叉閱讀。</p></div></div>
      <article class="card market-interpretation"><h3 id="marketAnalysisTitle"></h3><p id="marketAnalysisText"></p></article>
      <div class="grid market-grid" id="marketGrid"></div>
    </section>

    <section class="section grid two-col">
      <article class="card chart-card">
        <div class="section-head"><div><h2>7日公開資訊活動</h2><p>每日各類別的去重證據項目數。</p></div></div>
        <div class="bar-chart" id="barChart" aria-label="七日資訊活動長條圖"></div>
        <div class="legend" id="chartLegend"></div>
      </article>
      <article class="card health-card">
        <div class="section-head"><div><h2>來源健康度</h2><p>來源失敗會保留在此，不用靜默的空白冒充平靜。</p></div></div>
        <div class="health-list" id="healthList"></div>
      </article>
    </section>

    <section class="section">
      <div class="section-head"><div><h2>推演基準時間線</h2><p>人工整理的固定事件，避免每日新聞流失去前後脈絡。</p></div></div>
      <div class="card timeline" id="timeline"></div>
    </section>

    <section class="section">
      <div class="section-head"><div><h2>最新證據佇列</h2><p>最多顯示最近80組去重新聞；點標題回到來源，先看後判斷。</p></div><span class="tag" id="evidenceCount"></span></div>
      <div class="filters" id="filters"></div>
      <div class="card evidence-wrap">
        <table>
          <thead><tr><th>時間</th><th>類別</th><th>標題</th><th>可信度</th><th>來源</th></tr></thead>
          <tbody id="evidenceBody"></tbody>
        </table>
      </div>
      <div class="evidence-footer"><span>計數單位：公開證據項目，不是攻擊次數</span><span id="staleNote"></span></div>
    </section>

    <section class="section">
      <div class="section-head"><div><h2>方法與邊界</h2><p>這個頁面刻意把「知道什麼」與「不知道什麼」分開。</p></div></div>
      <div class="grid method-grid">
        <article class="card method-card"><h3>怎麼替代拿不到的答案</h3><ul id="methodList"></ul></article>
        <article class="card method-card"><h3>資料限制</h3><ul id="limitationList"></ul></article>
        <article class="card method-card"><h3>判讀原則</h3><p>單日安靜不等於能力消失；單次命中也不等於韌性充足。只有跨日趨勢、可驗證後果、通航改善與協議執行共同收斂，才接近終局訊號。</p><p>網站不提供投資建議，也不把媒體標題當成已驗證戰果。</p></article>
      </div>
    </section>
    <footer>資料每日自動更新 · 方法框架由人工維護 · <span id="generatedFooter"></span></footer>
  </main>

  <script id="snapshotData" type="application/json">__SNAPSHOT__</script>
  <script id="assessmentData" type="application/json">__ASSESSMENT__</script>
  <script id="eventsData" type="application/json">__EVENTS__</script>
  <script>
    const snapshot = JSON.parse(document.getElementById('snapshotData').textContent);
    const assessment = JSON.parse(document.getElementById('assessmentData').textContent);
    const events = JSON.parse(document.getElementById('eventsData').textContent);
    const metrics = snapshot.metrics || {};
    const analysis = snapshot.analysis || {};
    const categories = ['海峽與商船','軍事行動','基礎設施','外交與停火','核問題','以色列動向','紅海與蘇伊士','非對稱戰術'];
    const categoryColors = {'海峽與商船':'#43d19e','軍事行動':'#ff6b6b','基礎設施':'#ffc857','外交與停火':'#65a6ff','核問題':'#b28dff','以色列動向':'#f78fb3','紅海與蘇伊士':'#34ace0','非對稱戰術':'#ff9f43'};
    const fmtNumber = value => Number(value).toLocaleString('zh-TW', {maximumFractionDigits: 2});
    const fmtTime = value => new Intl.DateTimeFormat('zh-TW',{timeZone:'Asia/Taipei',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value));
    const escAttr = value => String(value || '').replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;').replaceAll('>','&gt;');
    const elt = (tag, cls, text) => { const node=document.createElement(tag); if(cls) node.className=cls; if(text!==undefined) node.textContent=text; return node; };

    document.getElementById('headline').textContent = analysis.headline || assessment.headline;
    document.getElementById('assessmentSummary').textContent = analysis.plain_summary || analysis.bottom_line || assessment.summary;
    const heroExplanation = document.getElementById('heroExplanation');
    (analysis.hero_explanation || []).forEach(item => {
      const row=elt('article','hero-point');
      const body=elt('div','hero-point-body');
      body.append(elt('h2','',item.title || ''),elt('p','',item.assessment || ''));
      row.append(elt('span','hero-point-label',item.label || ''),body);
      heroExplanation.append(row);
    });
    document.getElementById('phaseValue').textContent = analysis.test_phase || metrics.posture || '資料不足';
    document.getElementById('limitValue').textContent = `${analysis.thesis_state || ''}。判讀信心：${analysis.confidence || '偏低'}。${analysis.confidence_note || metrics.posture_note || ''}`;
    document.getElementById('questionValue').textContent = assessment.decision_question;
    document.getElementById('refreshPill').textContent = `台北 ${fmtTime(snapshot.generated_at)} 更新`;
    document.getElementById('generatedFooter').textContent = `資料時間 ${fmtTime(snapshot.generated_at)}`;
    document.getElementById('staleNote').textContent = snapshot.stale ? '本次抓取失敗，顯示上次成功資料' : '自動來源已完成本次更新';

    const thesis = assessment.thesis || {};
    document.getElementById('thesisTitle').textContent = thesis.title || '擴大戰事的作用，是揭露實力並迫使雙方修正誤判';
    (thesis.steps || []).forEach(step => {
      const card=elt('article','thesis-step'); card.append(elt('strong','',step.label),elt('p','',step.detail)); document.getElementById('thesisFlow').append(card);
    });

    const analysisColors = ['#43d19e','#65a6ff','#ff9f43','#ffc857','#b28dff','#ff6b6b'];
    const analysisKeys = ['revelation','durability','us_learning','endpoint','negotiability','escalation'];
    const analysisLabels = ['能力揭露','持續性邊界','認知修正','終局位置','可信承諾','擴大的雙面作用'];
    const analysisGrid = document.getElementById('analysisGrid');
    analysisKeys.forEach((key,index) => {
      const item=analysis[key] || {}; const card=elt('article','card analysis-card'); card.style.setProperty('--accent',analysisColors[index]);
      const kicker=elt('div','analysis-kicker'); kicker.append(elt('span','',analysisLabels[index]),elt('span','',index<2?'已知與未知分開':''));
      card.append(kicker,elt('h3','',item.title||'資料不足'),elt('p','',item.assessment||'目前沒有足夠資料形成判讀。')); analysisGrid.append(card);
    });
    document.getElementById('evidenceGuardrail').textContent = analysis.evidence_guardrail || '新聞項目只用於安排人工驗證，不是戰力統計。';
    (analysis.watch_next||[]).forEach(x=>document.getElementById('watchList').append(elt('li','',x)));

    const regionalKeys = ['israel','red_sea','asymmetric'];
    const regionalLabels = ['以色列觸發器','紅海第二咽喉','分散與非對稱能力'];
    regionalKeys.forEach((key,index) => {
      const item=analysis[key] || {}; const card=elt('article','card analysis-card'); card.style.setProperty('--accent',['#f78fb3','#34ace0','#ff9f43'][index]);
      const kicker=elt('div','analysis-kicker'); kicker.append(elt('span','',regionalLabels[index]));
      card.append(kicker,elt('h3','',item.title||'資料不足'),elt('p','',item.assessment||'目前沒有足夠資料形成判讀。')); document.getElementById('regionalGrid').append(card);
    });

    const kpis = [
      ['資訊活動', metrics.evidence_items_24h || 0, `前期 ${metrics.evidence_items_prev_24h||0} 組｜不是攻擊數`],
      ['較高可信度', (metrics.multi_source_24h||0)+(metrics.official_24h||0), '官方或多方報導｜不代表已驗證戰果'],
      ['提及實際後果', metrics.reported_consequence_24h || 0, `前期 ${metrics.reported_consequence_prev_24h||0} 組｜需人工核對`],
      ['海上壓力線索', metrics.maritime_pressure_24h || 0, `前期 ${metrics.maritime_pressure_prev_24h||0} 組｜看跨日方向`],
      ['外交活動線索', metrics.diplomacy_24h || 0, `前期 ${metrics.diplomacy_prev_24h||0} 組｜不等於可執行協議`]
    ];
    const kpiGrid = document.getElementById('kpiGrid');
    kpis.forEach(([label,value,note]) => {
      const card=elt('article','card kpi');
      card.append(elt('span','kpi-label',label),elt('strong','kpi-value',String(value)),elt('span','kpi-note',note));
      kpiGrid.append(card);
    });

    const scenarioColors = {iran_weaker:'#43d19e',iran_resilient:'#ff6b6b',middle_stalemate:'#ffc857'};
    const scenarioGrid = document.getElementById('scenarioGrid');
    assessment.scenarios.forEach(s => {
      const card=elt('article','card scenario'); card.style.setProperty('--accent',scenarioColors[s.id]);
      const update=(analysis.route_updates||{})[s.id]||{};
      card.append(elt('span','scenario-update',update.status||(analysis.scenario_updates||{})[s.id]||'持續觀察'),elt('h3','',s.name),elt('p','',s.interpretation));
      const route=elt('div','route-read'); const evidence=elt('div'); evidence.append(elt('strong','','今日證據'),document.createTextNode(update.evidence||'資料不足')); const missing=elt('div'); missing.append(elt('strong','','還缺什麼'),document.createTextNode(update.missing||'需要更多跨日證據')); route.append(evidence,missing); card.append(route);
      [['確認條件',s.confirmers],['推翻條件',s.falsifiers]].forEach(([title,list]) => {
        const d=elt('details'); const summary=elt('summary','',title); const ul=elt('ul'); list.forEach(x=>ul.append(elt('li','',x))); d.append(summary,ul); card.append(d);
      });
      scenarioGrid.append(card);
    });

    document.getElementById('marketAnalysisTitle').textContent = analysis.market?.title || '市場只提供交叉驗證';
    document.getElementById('marketAnalysisText').textContent = analysis.market?.assessment || '市場資料不足以形成終局判讀。';

    function sparkline(history) {
      if (!history || history.length < 2) return '<div class="empty">資料不足</div>';
      const values=history.map(x=>Number(x.value)); const min=Math.min(...values), max=Math.max(...values); const span=max-min||1;
      const points=values.map((v,i)=>`${(i/(values.length-1)*100).toFixed(1)},${(42-(v-min)/span*38).toFixed(1)}`).join(' ');
      return `<svg class="spark" viewBox="0 0 100 44" preserveAspectRatio="none" aria-hidden="true"><polyline fill="none" stroke="var(--green)" stroke-width="2" vector-effect="non-scaling-stroke" points="${points}"/></svg>`;
    }
    const marketGrid=document.getElementById('marketGrid');
    Object.values(snapshot.markets || {}).forEach(m => {
      const card=elt('article','card market');
      if (m.error) { card.append(elt('div','market-top',m.label),elt('div','empty','暫無資料')); marketGrid.append(card); return; }
      const top=elt('div','market-top'); top.append(elt('span','',m.label),elt('span','',m.as_of));
      const value=elt('div','market-value',fmtNumber(m.value));
      const ch=elt('span',`change ${(m.day_change_pct||0)>=0?'up':'down'}`,`${(m.day_change_pct||0)>=0?'+':''}${m.day_change_pct}%`); value.append(ch);
      card.append(top,value); card.insertAdjacentHTML('beforeend',sparkline(m.history)); card.append(elt('div','kpi-note',`5日 ${(m.five_day_change_pct||0)>=0?'+':''}${m.five_day_change_pct}% · ${m.ticker}`));
      marketGrid.append(card);
    });

    const daily=metrics.daily_counts_7d || []; const maxDaily=Math.max(1,...daily.map(d=>categories.reduce((sum,c)=>sum+(d.categories[c]||0),0)));
    const barChart=document.getElementById('barChart');
    daily.forEach(day => {
      const wrap=elt('div','bar-day'); const stack=elt('div','bar-stack');
      categories.forEach(cat=>{ const count=day.categories[cat]||0; if(!count) return; const bar=elt('div','bar'); bar.style.height=`${Math.max(4,count/maxDaily*150)}px`; bar.style.background=categoryColors[cat]; bar.title=`${cat}: ${count}`; stack.append(bar); });
      wrap.append(stack,elt('small','',day.date.slice(5))); barChart.append(wrap);
    });
    const legend=document.getElementById('chartLegend');
    categories.forEach(cat=>{ const span=elt('span'); const dot=elt('i'); dot.style.background=categoryColors[cat]; span.append(dot,document.createTextNode(cat)); legend.append(span); });

    const health=document.getElementById('healthList');
    (snapshot.fetch_status||[]).forEach(row=>{ const wrap=elt('div','health-row'); wrap.append(elt('span','',row.source),elt('strong',row.ok?'ok':'fail',row.ok?`${row.items ?? 0} 筆`:'失敗')); health.append(wrap); });

    const timeline=document.getElementById('timeline');
    events.events.forEach(event=>{ const item=elt('article','timeline-item'); item.append(elt('div','timeline-date',event.date)); const body=elt('div'); body.append(elt('h3','',event.title),elt('p','',event.summary)); const links=elt('div','source-links'); event.sources.forEach(s=>{ const a=elt('a','',s.name+' ↗'); a.href=s.url; a.target='_blank'; a.rel='noopener noreferrer'; links.append(a); }); body.append(links); item.append(body); timeline.append(item); });

    let activeFilter='全部';
    const filters=document.getElementById('filters');
    ['全部',...categories].forEach(cat=>{ const b=elt('button',`filter-btn ${cat==='全部'?'active':''}`,cat); b.type='button'; b.onclick=()=>{activeFilter=cat; [...filters.children].forEach(x=>x.classList.toggle('active',x===b)); renderEvidence();}; filters.append(b); });
    function renderEvidence() {
      const body=document.getElementById('evidenceBody'); body.replaceChildren();
      const rows=(snapshot.items||[]).filter(x=>activeFilter==='全部'||x.category===activeFilter).slice(0,80);
      rows.forEach(item=>{
        const tr=document.createElement('tr');
        tr.append(elt('td','',fmtTime(item.published_at)),elt('td','',item.category));
        const title=elt('td','title-cell'); const a=elt('a','',item.title); a.href=item.url; a.target='_blank'; a.rel='noopener noreferrer'; title.append(a); tr.append(title);
        const cls=item.confidence==='官方發布'?'official':item.confidence==='多方報導'?'multi':''; tr.append(elt('td',`confidence ${cls}`,item.confidence));
        const sources=[...new Set((item.sources||[]).map(s=>s.name))].slice(0,3).join('、') || item.source; tr.append(elt('td','',sources)); body.append(tr);
      });
      if(!rows.length){ const tr=document.createElement('tr'); const td=elt('td','empty','目前沒有這個類別的公開證據項目'); td.colSpan=5; tr.append(td); body.append(tr); }
      document.getElementById('evidenceCount').textContent=`顯示 ${rows.length} / ${(snapshot.items||[]).length}`;
    }
    renderEvidence();

    assessment.method.forEach(x=>document.getElementById('methodList').append(elt('li','',x)));
    (snapshot.limitations||[]).forEach(x=>document.getElementById('limitationList').append(elt('li','',x)));

    const root=document.documentElement; const saved=localStorage.getItem('iran-terminal-theme'); if(saved) root.dataset.theme=saved;
    document.getElementById('themeButton').onclick=()=>{ const next=root.dataset.theme==='light'?'dark':'light'; root.dataset.theme=next; localStorage.setItem('iran-terminal-theme',next); };
  </script>
</body>
</html>'''


def main() -> None:
    snapshot = load_json("snapshot.json")
    assessment = load_json("assessment.json")
    events = load_json("curated_events.json")
    html = HTML.replace("__SNAPSHOT__", safe_json(snapshot))
    html = html.replace("__ASSESSMENT__", safe_json(assessment))
    html = html.replace("__EVENTS__", safe_json(events))
    OUTPUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUTPUT} ({OUTPUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
