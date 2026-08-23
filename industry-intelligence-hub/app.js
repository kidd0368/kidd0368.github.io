
"use strict";

const PASSWORD_HASH = "d1f3a25e249218ef25bcd4d3493783face7e21fae8ce92ea78dd266ffdf0fb8e";
const MAX_HASH_BYTES = 100 * 1024 * 1024;
const REQUIRED_RECORD_KEYS = [
  "schema_version","task_id","created_at","updated_at","analysis_type","industry_id",
  "taxonomy_version_used","source","narrative","findings","financials",
  "operating_assumptions","segment_estimates","metric_claims","relationships",
  "mentioned_entities","evidence","derived_metrics","validation"
];

const state = {
  registry: null,
  taxonomy: null,
  taxonomyVersionDoc: null,
  taxonomySource: "unknown",
  recordsDoc: null,
  records: [],
  manifest: null,
  changelog: null,
  files: [],
  currentTaskPacket: null,
  validatedJson: null,
  initialized: false,
  bound: false
};

const $ = (id) => document.getElementById(id);
const qsa = (selector, root = document) => [...root.querySelectorAll(selector)];

document.addEventListener("DOMContentLoaded", () => {
  bindGate();
  if (sessionStorage.getItem("iih-auth") === "1") {
    unlock();
  } else {
    $("gate-password").focus();
  }
});

function bindGate() {
  $("gate-submit").addEventListener("click", attemptLogin);
  $("gate-password").addEventListener("keydown", (event) => {
    if (event.key === "Enter") attemptLogin();
  });
}

async function attemptLogin() {
  const input = $("gate-password").value;
  const hash = await sha256Text(input);
  if (hash === PASSWORD_HASH) {
    sessionStorage.setItem("iih-auth", "1");
    $("gate-error").textContent = "";
    unlock();
  } else {
    $("gate-error").textContent = "密碼錯誤";
    $("gate-password").select();
  }
}

function unlock() {
  $("gate").classList.add("hidden");
  $("app").classList.remove("hidden");
  if (!state.bound) bindAppEvents();
  if (!state.initialized) initApp();
}

function logout() {
  sessionStorage.removeItem("iih-auth");
  location.reload();
}

async function sha256Text(text) {
  const data = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return hex(digest);
}

function hex(buffer) {
  return [...new Uint8Array(buffer)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function bindAppEvents() {
  state.bound = true;

  qsa(".nav-btn").forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.view));
  });
  qsa("[data-go]").forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.go));
  });

  $("logout-btn").addEventListener("click", logout);
  $("refresh-all").addEventListener("click", loadAll);
  $("refresh-records").addEventListener("click", loadRecords);
  $("refresh-taxonomy").addEventListener("click", loadTaxonomy);
  $("system-refresh").addEventListener("click", loadAll);

  $("new-task-id").addEventListener("click", setNewTaskId);
  $("reset-task").addEventListener("click", resetTask);
  $("generate-prompt").addEventListener("click", generatePrompt);
  $("copy-prompt").addEventListener("click", () => copyText($("prompt-output").value));
  $("download-prompt").addEventListener("click", downloadPrompt);
  $("download-packet").addEventListener("click", downloadTaskPacket);

  const drop = $("file-drop");
  const fileInput = $("file-input");
  drop.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => handleFiles(fileInput.files));
  ["dragenter","dragover"].forEach((name) => drop.addEventListener(name, (event) => {
    event.preventDefault();
    drop.classList.add("dragging");
  }));
  ["dragleave","drop"].forEach((name) => drop.addEventListener(name, (event) => {
    event.preventDefault();
    drop.classList.remove("dragging");
  }));
  drop.addEventListener("drop", (event) => handleFiles(event.dataTransfer.files));
  $("file-list").addEventListener("click", (event) => {
    const button = event.target.closest("[data-remove-file]");
    if (!button) return;
    state.files.splice(Number(button.dataset.removeFile), 1);
    renderFiles();
  });

  ["record-search","record-type-filter","record-status-filter"].forEach((id) => {
    $(id).addEventListener("input", renderRecords);
    $(id).addEventListener("change", renderRecords);
  });
  $("records-table").addEventListener("click", (event) => {
    const row = event.target.closest("[data-record-path]");
    if (row) openRecord(row.dataset.recordPath);
  });
  $("recent-records").addEventListener("click", (event) => {
    const row = event.target.closest("[data-record-path]");
    if (row) openRecord(row.dataset.recordPath);
  });

  $("node-search").addEventListener("input", renderTaxonomyTree);
  $("taxonomy-tree").addEventListener("click", (event) => {
    const row = event.target.closest("[data-node-id]");
    if (!row) return;
    qsa(".tree-row", $("taxonomy-tree")).forEach((el) => el.classList.remove("active"));
    row.classList.add("active");
    renderNodeDetail(row.dataset.nodeId);
  });

  $("validate-json").addEventListener("click", validateJsonInput);
  $("load-example").addEventListener("click", loadExample);
  $("json-file").addEventListener("change", loadJsonFile);
  $("download-validated").addEventListener("click", downloadValidatedJson);

  $("dialog-close").addEventListener("click", () => $("record-dialog").close());
  $("record-dialog").addEventListener("click", (event) => {
    const rect = $("record-dialog").getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) {
      $("record-dialog").close();
    }
  });
}

async function initApp() {
  state.initialized = true;
  const today = taipeiDateParts();
  $("received-date").value = `${today.year}-${today.month}-${today.day}`;
  setNewTaskId();
  await loadAll();
}

function showView(name) {
  qsa(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${name}`));
  qsa(".nav-btn").forEach((button) => button.classList.toggle("active", button.dataset.view === name));
  window.scrollTo({top: 0, behavior: "smooth"});
}

async function loadAll() {
  setLoadingState();
  try {
    await loadRegistry();
    populateIndustries();
    await Promise.all([loadTaxonomy(false), loadRecords(false), loadManifest(), loadChangelog()]);
    renderAll();
    toast("同步完成", "good");
  } catch (error) {
    console.error(error);
    toast(`部分資料讀取失敗：${error.message}`, "bad");
    renderAll();
  }
}

function setLoadingState() {
  setDot("taxonomy-dot", "");
  setDot("records-dot", "");
  setDot("sync-dot", "");
  $("sync-state-top").textContent = "檢查中";
}

async function loadRegistry() {
  state.registry = await fetchJson("data/registry.json");
  return state.registry;
}

async function loadTaxonomy(render = true) {
  if (!state.registry) await loadRegistry();
  const industryId = $("industry-select").value || state.registry.industries[0]?.industry_id || "CPO";
  const item = state.registry.industries.find((x) => x.industry_id === industryId) || state.registry.industries[0];
  if (!item) throw new Error("registry 沒有可用產業");

  let taxonomy;
  try {
    taxonomy = await fetchJson(item.taxonomy_url);
    state.taxonomySource = "remote";
    try {
      state.taxonomyVersionDoc = await fetchJson(item.version_url);
    } catch {
      state.taxonomyVersionDoc = null;
    }
  } catch (remoteError) {
    console.warn("remote taxonomy failed", remoteError);
    taxonomy = await fetchJson(item.fallback_snapshot_url);
    state.taxonomySource = "snapshot";
    state.taxonomyVersionDoc = null;
  }
  assertTaxonomy(taxonomy);
  state.taxonomy = taxonomy;
  populateEntityOptions();
  if (render) {
    renderAll();
    toast(state.taxonomySource === "remote" ? "已讀取最新產業分類" : "遠端分類失敗，已使用本地快照", state.taxonomySource === "remote" ? "good" : "bad");
  }
  return taxonomy;
}

async function loadRecords(render = true) {
  try {
    state.recordsDoc = await fetchJson("data/records.json");
    state.records = Array.isArray(state.recordsDoc.records) ? state.recordsDoc.records : [];
  } catch (error) {
    console.warn(error);
    state.recordsDoc = {records: [], valid_record_count: 0, invalid_record_count: 0};
    state.records = [];
  }
  populateRecordFilters();
  if (render) {
    renderAll();
    toast("研究紀錄已重新載入", "good");
  }
}

async function loadManifest() {
  try {
    state.manifest = await fetchJson("data/manifest.json");
  } catch {
    state.manifest = null;
  }
}

async function loadChangelog() {
  try {
    state.changelog = await fetchJson("data/changelog.json");
  } catch {
    state.changelog = null;
  }
}

async function fetchJson(url) {
  const separator = url.includes("?") ? "&" : "?";
  const response = await fetch(`${url}${separator}v=${Date.now()}`, {cache: "no-store"});
  if (!response.ok) throw new Error(`${url}：HTTP ${response.status}`);
  return response.json();
}

function assertTaxonomy(data) {
  if (!data || !Array.isArray(data.nodes) || !Array.isArray(data.entities) || !Array.isArray(data.metric_catalog)) {
    throw new Error("taxonomy 格式不完整");
  }
}

function renderAll() {
  renderHeaderStatus();
  renderOverview();
  renderRecords();
  renderTaxonomyTree();
  renderSystem();
  $("footer-updated").textContent = `最後載入：${formatDateTime(new Date())}`;
}

function renderHeaderStatus() {
  const taxonomyOk = Boolean(state.taxonomy);
  const recordsOk = Boolean(state.recordsDoc);
  setDot("taxonomy-dot", taxonomyOk ? (state.taxonomySource === "remote" ? "good" : "warn") : "bad");
  setDot("records-dot", recordsOk ? "good" : "bad");
  setDot("sync-dot", taxonomyOk && recordsOk ? (state.taxonomySource === "remote" ? "good" : "warn") : "bad");

  $("taxonomy-version").textContent = state.taxonomy?.taxonomy_version || "無法讀取";
  $("record-count-top").textContent = String(state.records.length);
  $("sync-state-top").textContent = taxonomyOk && recordsOk ? (state.taxonomySource === "remote" ? "正常" : "使用快照") : "異常";
}

function setDot(id, status) {
  const el = $(id);
  el.className = `dot${status ? ` ${status}` : ""}`;
}

function renderOverview() {
  const records = state.records || [];
  const metricCount = records.reduce((sum, row) => sum + Number(row.metric_count || 0), 0);
  const reviewCount = records.filter((row) => row.record_status === "review_required" || Number(row.conflicts_found || 0) > 0).length;

  $("stat-records").textContent = records.length;
  $("stat-records-detail").textContent = records.length ? `最近更新 ${formatDate(state.manifest?.latest_record_at)}` : "等待第一筆資料";
  $("stat-nodes").textContent = state.taxonomy?.nodes?.length ?? "—";
  $("stat-entities").textContent = state.taxonomy?.entities?.length ?? "—";
  $("stat-metrics").textContent = metricCount;
  $("stat-review").textContent = reviewCount;

  $("status-taxonomy-source").textContent = state.taxonomySource === "remote" ? "/cpo-notes/data/taxonomy.json" : "data/taxonomy.cpo.snapshot.json";
  $("status-taxonomy-state").innerHTML = state.taxonomy ? tag(state.taxonomySource === "remote" ? "已連線" : "使用快照", state.taxonomySource === "remote" ? "good" : "warn") : tag("失敗", "bad");
  $("status-taxonomy-version").textContent = state.taxonomy?.taxonomy_version || "—";
  const versionMatches = !state.taxonomyVersionDoc || state.taxonomyVersionDoc.taxonomy_version === state.taxonomy?.taxonomy_version;
  $("status-taxonomy-version-state").innerHTML = state.taxonomy ? tag(versionMatches ? "一致" : "版本差異", versionMatches ? "good" : "warn") : "—";
  $("status-records-state").innerHTML = state.recordsDoc ? tag("正常", "good") : tag("失敗", "bad");

  renderRecentRecords();
  renderMetricBars();
}

function renderRecentRecords() {
  const recent = state.records.slice(0, 6);
  if (!recent.length) {
    $("recent-records").innerHTML = `<div class="empty"><b>尚無正式紀錄</b>從「建立分析任務」產生第一份指令，ChatGPT 寫入 GitHub 後會出現在此。</div>`;
    return;
  }
  $("recent-records").innerHTML = `
    <div class="table-wrap">
      <table>
        <thead><tr><th>日期</th><th>標題</th><th>公司</th><th>數值</th><th>狀態</th></tr></thead>
        <tbody>${recent.map((r) => `
          <tr data-record-path="${escAttr(r.record_path || "")}">
            <td class="nowrap">${esc(formatDate(r.updated_at))}</td>
            <td><b>${esc(r.title || r.task_id)}</b><div class="faint">${esc(r.source?.publisher || r.analysis_type || "")}</div></td>
            <td>${(r.entities || []).slice(0,3).map((e) => `<span class="tag">${esc(e.name || e.entity_id)}</span>`).join("") || "—"}</td>
            <td>${Number(r.metric_count || 0)}</td>
            <td>${statusTag(r.record_status, r.conflicts_found)}</td>
          </tr>`).join("")}
        </tbody>
      </table>
    </div>`;
}

function renderMetricBars() {
  const counts = new Map();
  state.records.forEach((record) => {
    (record.metric_ids || []).forEach((id) => counts.set(id, (counts.get(id) || 0) + 1));
  });
  const catalog = new Map((state.taxonomy?.metric_catalog || []).map((m) => [m.metric_id, m.name]));
  const rows = [...counts.entries()].sort((a,b) => b[1]-a[1]).slice(0,10);
  if (!rows.length) {
    const supported = (state.taxonomy?.metric_catalog || []).slice(0,8);
    $("metric-bars").innerHTML = supported.length
      ? supported.map((m) => `<span class="tag info">${esc(m.name)}</span>`).join("")
      : `<div class="empty"><b>尚無指標資料</b>第一筆紀錄寫入後會顯示分布。</div>`;
    return;
  }
  const max = Math.max(...rows.map((x) => x[1]), 1);
  $("metric-bars").innerHTML = rows.map(([id,count]) => `
    <div class="bar-row">
      <div class="bar-label" title="${escAttr(id)}">${esc(catalog.get(id) || id)}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${Math.round(count/max*100)}%"></div></div>
      <div class="bar-value">${count}</div>
    </div>`).join("");
}

function populateIndustries() {
  const select = $("industry-select");
  const current = select.value;
  select.innerHTML = (state.registry?.industries || []).filter((x) => x.enabled).map((x) => `<option value="${escAttr(x.industry_id)}">${esc(x.name)}</option>`).join("");
  if (current && [...select.options].some((o) => o.value === current)) select.value = current;
}

function populateEntityOptions() {
  const list = $("entity-options");
  list.innerHTML = (state.taxonomy?.entities || []).map((entity) => {
    const label = entity.ticker ? `${entity.name} (${entity.ticker})` : entity.name;
    return `<option value="${escAttr(label)}"></option>`;
  }).join("");
}

function populateRecordFilters() {
  const select = $("record-type-filter");
  const current = select.value;
  const types = [...new Set(state.records.map((r) => r.analysis_type).filter(Boolean))].sort();
  select.innerHTML = `<option value="">全部資料類型</option>${types.map((x) => `<option value="${escAttr(x)}">${esc(typeLabel(x))}</option>`).join("")}`;
  if (types.includes(current)) select.value = current;
}

function renderRecords() {
  const container = $("records-table");
  if (!container) return;
  const search = ($("record-search")?.value || "").trim().toLowerCase();
  const type = $("record-type-filter")?.value || "";
  const status = $("record-status-filter")?.value || "";

  const filtered = state.records.filter((record) => {
    if (type && record.analysis_type !== type) return false;
    if (status && record.record_status !== status) return false;
    if (!search) return true;
    const haystack = [
      record.task_id, record.title, record.executive_summary, record.analysis_type,
      record.source?.title, record.source?.publisher,
      ...(record.entities || []).flatMap((e) => [e.name,e.ticker,e.entity_id])
    ].filter(Boolean).join(" ").toLowerCase();
    return haystack.includes(search);
  });

  if (!filtered.length) {
    container.innerHTML = `<div class="empty"><b>${state.records.length ? "沒有符合篩選的紀錄" : "尚無研究紀錄"}</b>${state.records.length ? "調整搜尋或狀態條件。" : "ChatGPT 寫入第一份 record JSON 後，GitHub Action 會自動建立索引。"}</div>`;
    return;
  }
  container.innerHTML = `
    <div class="table-wrap">
      <table>
        <thead><tr><th>更新日期</th><th>標題／來源</th><th>公司</th><th>發現</th><th>數值</th><th>證據</th><th>狀態</th></tr></thead>
        <tbody>${filtered.map((r) => `
          <tr data-record-path="${escAttr(r.record_path || "")}">
            <td class="nowrap">${esc(formatDate(r.updated_at))}<div class="faint mono">${esc(r.task_id || "")}</div></td>
            <td><b>${esc(r.title || r.task_id)}</b><div class="faint">${esc(r.source?.publisher || "")} ${esc(r.source?.published_date || "")}</div><div class="muted">${esc(truncate(r.executive_summary || "",120))}</div></td>
            <td>${(r.entities || []).slice(0,5).map((e) => `<span class="tag">${esc(e.name || e.entity_id)}${e.ticker ? ` ${esc(e.ticker)}` : ""}</span>`).join("") || "—"}</td>
            <td>${Number(r.finding_count || 0)}</td>
            <td>${Number(r.metric_count || 0)}</td>
            <td>${Number(r.evidence_count || 0)}</td>
            <td>${statusTag(r.record_status, r.conflicts_found)}</td>
          </tr>`).join("")}
        </tbody>
      </table>
    </div>`;
}

async function openRecord(path) {
  if (!path) return;
  try {
    const record = await fetchJson(path);
    $("dialog-title").textContent = record.title || record.task_id;
    $("dialog-subtitle").textContent = `${record.task_id} · ${typeLabel(record.analysis_type)} · taxonomy ${record.taxonomy_version_used}`;
    $("dialog-body").innerHTML = renderRecordDetail(record);
    $("record-dialog").showModal();
  } catch (error) {
    toast(`無法載入紀錄：${error.message}`, "bad");
  }
}

function renderRecordDetail(record) {
  const narrative = record.narrative || {};
  const metrics = [...(record.financials || []), ...(record.metric_claims || [])];
  const evidenceById = new Map((record.evidence || []).map((e) => [e.evidence_id, e]));
  return `
    <section class="dialog-section">
      <h4>執行摘要</h4>
      <div class="prose">${esc(narrative.executive_summary || "—")}</div>
    </section>
    <section class="dialog-section">
      <h4>文字擴張版</h4>
      <div class="prose">${esc(narrative.expanded_report || "—")}</div>
    </section>
    <section class="dialog-section">
      <h4>提及公司</h4>
      ${(record.mentioned_entities || []).map((e) => `<div class="card card-pad" style="margin-bottom:8px"><b>${esc(e.name || e.entity_id)} ${esc(e.ticker || "")}</b><div class="muted">${esc(e.reason_mentioned || "")}</div><div>${(e.node_ids || []).map((id) => `<span class="tag">${esc(nodeName(id))}</span>`).join("")}</div></div>`).join("") || "—"}
    </section>
    <section class="dialog-section">
      <h4>數值主張</h4>
      ${metrics.length ? `<div class="table-wrap"><table><thead><tr><th>公司</th><th>指標</th><th>期間</th><th>數值</th><th>性質</th><th>信心</th></tr></thead><tbody>${metrics.map((m) => `<tr><td>${esc(entityName(m.entity_id))}</td><td>${esc(metricName(m.metric_id))}</td><td>${esc(m.reference_period || "")}</td><td>${esc(formatMetricValue(m))}</td><td>${esc(m.fact_type || "")}</td><td>${formatConfidence(m.confidence)}</td></tr>`).join("")}</tbody></table></div>` : "—"}
    </section>
    <section class="dialog-section">
      <h4>營運假設</h4>
      ${(record.operating_assumptions || []).map((a) => `<div class="validation-box"><b>${esc(a.category || "")}</b><div class="prose">${esc(a.description || "")}</div></div>`).join("") || "—"}
    </section>
    <section class="dialog-section">
      <h4>證據</h4>
      ${(record.evidence || []).map((e) => `<div class="validation-box"><b>${esc(e.locator || e.evidence_id)}</b><div class="prose">${esc(e.excerpt || "")}</div></div>`).join("") || "—"}
    </section>
  `;
}

function renderTaxonomyTree() {
  const container = $("taxonomy-tree");
  if (!container) return;
  if (!state.taxonomy) {
    container.innerHTML = `<div class="empty"><b>分類尚未載入</b>請重新同步。</div>`;
    return;
  }
  const search = ($("node-search")?.value || "").trim().toLowerCase();
  const nodes = state.taxonomy.nodes;
  const nodeMap = new Map(nodes.map((n) => [n.node_id,n]));
  const memberCounts = new Map();
  (state.taxonomy.memberships || []).forEach((m) => memberCounts.set(m.node_id,(memberCounts.get(m.node_id)||0)+1));

  const depth = (node) => {
    let d = 0, current = node, guard = 0;
    while (current?.parent_id && guard++ < 20) {
      d++;
      current = nodeMap.get(current.parent_id);
    }
    return d;
  };
  const rows = nodes.filter((node) => !search || `${node.name} ${node.node_id}`.toLowerCase().includes(search));
  if (!rows.length) {
    container.innerHTML = `<div class="empty"><b>找不到節點</b>請調整搜尋文字。</div>`;
    return;
  }
  container.innerHTML = rows.sort((a,b) => Number(a.order||0)-Number(b.order||0)).map((node) => `
    <div class="tree-row" data-node-id="${escAttr(node.node_id)}" style="padding-left:${10 + depth(node)*18}px">
      <div><div class="tree-name">${esc(node.name)}</div><div class="tree-id mono">${esc(node.node_id)}</div></div>
      <div class="tree-count">${memberCounts.get(node.node_id)||0}</div>
    </div>`).join("");
}

function renderNodeDetail(nodeId) {
  const node = state.taxonomy?.nodes?.find((n) => n.node_id === nodeId);
  if (!node) return;
  const parent = state.taxonomy.nodes.find((n) => n.node_id === node.parent_id);
  const children = state.taxonomy.nodes.filter((n) => n.parent_id === node.node_id);
  const memberIds = new Set((state.taxonomy.memberships || []).filter((m) => m.node_id === node.node_id).map((m) => m.entity_id));
  const members = state.taxonomy.entities.filter((e) => memberIds.has(e.entity_id));
  $("node-detail").innerHTML = `
    <h3>${esc(node.name)}</h3>
    <div class="node-id mono">${esc(node.node_id)}</div>
    <div style="margin-bottom:14px">
      <span class="tag info">${esc(node.stage || "未分類")}</span>
      ${parent ? `<span class="tag">上層：${esc(parent.name)}</span>` : ""}
      <span class="tag">公司 ${members.length}</span>
      <span class="tag">子節點 ${children.length}</span>
    </div>
    ${children.length ? `<h4>子節點</h4><div style="margin-bottom:18px">${children.map((c) => `<span class="tag">${esc(c.name)}</span>`).join("")}</div>` : ""}
    <h4>所屬公司／實體</h4>
    ${members.length ? `<div class="entity-grid">${members.map((e) => `<div class="entity-card"><b>${esc(e.name)}</b><small>${esc(e.ticker || "")} · ${esc(e.country || "")}</small><small class="mono">${esc(e.entity_id)}</small></div>`).join("")}</div>` : `<div class="empty"><b>此節點尚未綁定公司</b>新資料可提出公司或關係新增提案。</div>`}
  `;
}

function setNewTaskId() {
  const p = taipeiDateParts();
  const random = randomCode(5);
  $("task-id").value = `TASK-${p.year}${p.month}${p.day}-${p.hour}${p.minute}${p.second}-${random}`;
}

function resetTask() {
  const ids = ["source-title","publisher","published-date","primary-entity","dropbox-path","research-focus","pasted-text","prompt-output","prompt-meta"];
  ids.forEach((id) => {
    const el = $(id);
    if (el) el.value !== undefined ? el.value = "" : el.textContent = "";
  });
  const today = taipeiDateParts();
  $("received-date").value = `${today.year}-${today.month}-${today.day}`;
  $("analysis-type").value = "broker_report";
  $("confidentiality").value = "private";
  $("direct-github").checked = true;
  state.files = [];
  state.currentTaskPacket = null;
  renderFiles();
  ["copy-prompt","download-prompt","download-packet"].forEach((id) => $(id).disabled = true);
  setNewTaskId();
}

async function handleFiles(fileList) {
  const files = [...fileList];
  if (!files.length) return;
  const newItems = [];
  for (const file of files) {
    const item = {
      name: file.name,
      size: file.size,
      mime_type: file.type || null,
      last_modified: file.lastModified ? new Date(file.lastModified).toISOString() : null,
      sha256: null,
      hash_status: file.size <= MAX_HASH_BYTES ? "calculating" : "skipped_large"
    };
    newItems.push(item);
    state.files.push(item);
    renderFiles();
    if (file.size <= MAX_HASH_BYTES) {
      try {
        const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
        item.sha256 = hex(digest);
        item.hash_status = "complete";
      } catch {
        item.hash_status = "failed";
      }
      renderFiles();
    }
  }
  $("file-input").value = "";
}

function renderFiles() {
  const container = $("file-list");
  if (!state.files.length) {
    container.innerHTML = `<div class="help">尚未選擇附件。</div>`;
    return;
  }
  container.innerHTML = state.files.map((file,index) => `
    <div class="file-item">
      <div>
        <div class="file-name" title="${escAttr(file.name)}">${esc(file.name)}</div>
        <div class="faint mono">${file.sha256 ? esc(file.sha256.slice(0,16))+"…" : hashStatusLabel(file.hash_status)}</div>
      </div>
      <div class="file-meta">${formatBytes(file.size)} <button class="btn btn-small" data-remove-file="${index}" type="button">移除</button></div>
    </div>`).join("");
}

function generatePrompt() {
  const sourceTitle = $("source-title").value.trim();
  if (!sourceTitle) {
    toast("請先填寫來源標題", "bad");
    $("source-title").focus();
    return;
  }
  if (!state.taxonomy || !state.registry) {
    toast("分類或系統設定尚未載入", "bad");
    return;
  }

  const taskId = $("task-id").value;
  const industryId = $("industry-select").value;
  const selectedIndustry = state.registry.industries.find((x) => x.industry_id === industryId);
  const entityInput = $("primary-entity").value.trim();
  const entity = findEntity(entityInput);
  const p = parseTaskIdDate(taskId) || taipeiDateParts();
  const recordPath = state.registry.record_path_template
    .replace("{yyyy}",p.year)
    .replace("{mm}",p.month)
    .replace("{task_id}",taskId);

  const pasted = $("pasted-text").value;
  const packet = {
    packet_schema_version: "1.0.0",
    task_id: taskId,
    created_at: new Date().toISOString(),
    timezone: "Asia/Taipei",
    analysis_type: $("analysis-type").value,
    industry_id: industryId,
    industry_name: selectedIndustry?.name || industryId,
    taxonomy_version_expected: state.taxonomy.taxonomy_version,
    taxonomy_source_repository: selectedIndustry?.source_repository,
    source: {
      source_id: `SRC-${taskId.replace("TASK-","")}`,
      source_type: $("analysis-type").value,
      title: sourceTitle,
      publisher: nullIfEmpty($("publisher").value),
      published_date: nullIfEmpty($("published-date").value),
      received_date: $("received-date").value,
      dropbox_path: nullIfEmpty($("dropbox-path").value),
      confidentiality: $("confidentiality").value,
      files: state.files.map(({hash_status,...item}) => item)
    },
    primary_entity: entity ? {entity_id:entity.entity_id,name:entity.name,ticker:entity.ticker,country:entity.country} : (entityInput ? {input:entityInput} : null),
    research_focus: nullIfEmpty($("research-focus").value),
    pasted_text: pasted || null,
    github_write: $("direct-github").checked,
    github_target: {
      repository: state.registry.target_repository,
      record_path: recordPath,
      schema_path: state.registry.schema_path,
      aggregate_path: state.registry.aggregate_path
    }
  };

  const attachmentLines = state.files.length
    ? state.files.map((f,index) => `${index+1}. ${f.name}｜${formatBytes(f.size)}｜${f.mime_type || "unknown"}｜SHA256 ${f.sha256 || "未計算"}`).join("\n")
    : "無檔案；本次以貼入文字或對話內容為主。";

  const primaryEntityText = entity ? `${entity.name}（${entity.ticker || entity.entity_id}；${entity.entity_id}）` : (entityInput || "未指定，請依來源判定");
  const directWrite = $("direct-github").checked;

  const prompt = `【產業情報研究系統｜分析與 GitHub 寫入任務】
任務 ID：${taskId}
時區：Asia/Taipei
資料類型：${typeLabel(packet.analysis_type)}
產業：${packet.industry_name}（${industryId}）
預期分類版本：${state.taxonomy.taxonomy_version}
主要研究對象：${primaryEntityText}
來源標題：${sourceTitle}
發布者：${packet.source.publisher || "未填"}
發布日期：${packet.source.published_date || "未填"}
取得日期：${packet.source.received_date || "未填"}
Dropbox 原始路徑：${packet.source.dropbox_path || "未填"}
機密性：${packet.source.confidentiality}

【附件清單】
${attachmentLines}

【本次特別問題】
${packet.research_focus || "依標準研究框架完整分析。"}

${pasted ? `【貼入文字】\n${pasted.slice(0,20000)}${pasted.length>20000 ? "\n[文字超過 20,000 字，任務封包已截斷；請以對話中的完整原文為準。]" : ""}\n` : ""}
【開始前必做】
1. 先讀取 GitHub：
   - kidd0368/cpo-notes 的 data/version.json
   - kidd0368/cpo-notes 的 data/taxonomy.json
   - kidd0368/kidd0368.github.io 的 industry-intelligence-hub/schemas/analysis-record.schema.json
2. 以實際讀到的 taxonomy_version 為準；不得依賴舊對話記憶。
3. 若附件是 PDF，必須檢查圖表與表格，不能只依文字抽取；來源頁碼、圖表位置與原句都要留下 evidence。
4. 對來源內容保持懷疑，查證重大數據、公司關係與海外競爭者；不得因提問方向而失去客觀性。
5. 不得把原始 PDF、圖片、付費報告全文或 GitHub Token 上傳 GitHub。

【分析內容】
A. 先提供可直接閱讀的繁體中文文字擴張版：
   - 核心結論與營運轉折
   - 去年、今年、明年，以及來源有預估到的更遠年度：營收、稅後淨利、EPS
   - 營運假設：產業需求、價格、出貨量、產能、有效產能、稼動率、良率、毛利率、營益率、新產品、新技術、市占率、新客戶、客戶比重、產品／業務營收比重、交期、資本支出
   - 各業務別在各年度的營收金額或營收比重
   - 來源提到的所有公司，以及為何提到；競爭者不得只列台灣，也要包含全球主要對手、客戶、供應商與替代技術
   - 產業上下游數字交叉驗證，以及對公司營收／獲利貢獻的可驗證推算
B. 明確區分：
   disclosed_actual、management_guidance、analyst_estimate、industry_estimate、model_inference、qualitative_claim。
C. 所有自行推算必須列公式、輸入 claim_id、假設與敏感度；資料不足時保留空值，不得捏造。
D. 百分比變化與百分點（ppt）、月產能與年產能、名目產能與有效產能、幣別與單位必須分清楚。
E. 若新資料與既有紀錄衝突，保留兩筆來源並將 record_status 設為 review_required；不得直接覆蓋舊主張。
F. 若發現分類需要新增／拆分／合併，只在 JSON 加入 taxonomy_change_proposals；除非任務明確授權，不要直接修改 cpo-notes 分類主檔。

【JSON 輸出與驗證】
1. 產出一個完全符合 analysis-record.schema.json 的 UTF-8 JSON 物件。
2. task_id 必須是：${taskId}
3. industry_id 必須是：${industryId}
4. taxonomy_version_used 必須填入本次實際讀取版本。
5. source.files 使用本指令附件清單；原始附件只保留檔名、大小、MIME 與 SHA-256。
6. node_id、entity_id、metric_id 優先使用 taxonomy 既有穩定 ID；找不到時建立待審核提案，不能自行假裝既有 ID。
7. 完成後自行檢查：必要欄位、日期、單位、期間、evidence 引用、重複 claim_id、未知 taxonomy ID、資料衝突。

${directWrite ? `【必須實際寫入 GitHub】
分析與 JSON 驗證完成後，不要只把 JSON 貼在回答中；請實際呼叫 GitHub 工具：
- Repository：${state.registry.target_repository}
- Record path：${recordPath}
- Commit message：industry-intelligence: add ${taskId}
- 若路徑不存在，用 create_file；若同一 task_id 已存在，先 fetch_file 取得 SHA，再用 update_file。
- 只寫入這一份 record JSON。GitHub Actions 會自動重建 records.json、manifest.json 與 changelog.json。
- 寫入失敗時必須如實回報，不能聲稱已提交。
- 最終回答需列出：文字擴張版、record_status、實際 GitHub 路徑、commit SHA、分類版本、數值筆數、衝突筆數、待審核事項。` : `【不寫入 GitHub】
本次只產出文字擴張版與符合 Schema 的 JSON，不執行 GitHub 寫入。`}

【任務封包】
${JSON.stringify(packet,null,2)}
`;

  state.currentTaskPacket = packet;
  $("prompt-output").value = prompt;
  $("prompt-meta").textContent = `分類 ${state.taxonomy.taxonomy_version}｜目標 ${recordPath}｜附件 ${state.files.length} 個`;
  ["copy-prompt","download-prompt","download-packet"].forEach((id) => $(id).disabled = false);
  toast("分析指令已產生", "good");
}

function findEntity(input) {
  if (!input || !state.taxonomy) return null;
  const normalized = input.toLowerCase().replace(/[()（）]/g," ");
  return state.taxonomy.entities.find((e) => {
    const values = [e.entity_id,e.name,e.ticker,`${e.name} ${e.ticker}`].filter(Boolean).map((x) => String(x).toLowerCase());
    return values.some((v) => normalized.includes(v) || v.includes(normalized.trim()));
  }) || null;
}

function downloadPrompt() {
  if (!state.currentTaskPacket) return;
  downloadText(`${state.currentTaskPacket.task_id}_prompt.txt`, $("prompt-output").value, "text/plain;charset=utf-8");
}

function downloadTaskPacket() {
  if (!state.currentTaskPacket) return;
  downloadText(`${state.currentTaskPacket.task_id}_packet.json`, JSON.stringify(state.currentTaskPacket,null,2), "application/json;charset=utf-8");
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("已複製到剪貼簿", "good");
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    document.body.append(area);
    area.select();
    document.execCommand("copy");
    area.remove();
    toast("已複製到剪貼簿", "good");
  }
}

function downloadText(name, text, type) {
  const blob = new Blob([text], {type});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function loadExample() {
  try {
    const data = await fetchJson("examples/analysis-record.example.json");
    $("json-input").value = JSON.stringify(data,null,2);
    validateJsonInput();
  } catch (error) {
    toast(`範例載入失敗：${error.message}`, "bad");
  }
}

async function loadJsonFile(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  $("json-input").value = await file.text();
  event.target.value = "";
  validateJsonInput();
}

function validateJsonInput() {
  const text = $("json-input").value.trim();
  state.validatedJson = null;
  $("download-validated").disabled = true;
  if (!text) {
    renderValidation(["JSON 內容為空"],[],null);
    return;
  }

  let data;
  try {
    data = JSON.parse(text);
  } catch (error) {
    renderValidation([`JSON 語法錯誤：${error.message}`],[],null);
    return;
  }

  const errors = [];
  const warnings = [];
  if (!isObject(data)) {
    errors.push("根層必須是 JSON object。");
    renderValidation(errors,warnings,data);
    return;
  }

  REQUIRED_RECORD_KEYS.forEach((key) => {
    if (!(key in data)) errors.push(`缺少必要欄位：${key}`);
  });
  if (data.schema_version !== "1.0.0") errors.push("schema_version 必須是 1.0.0。");
  if (!/^TASK-\d{8}-\d{6}-[A-Z0-9]{4,8}$/.test(data.task_id || "")) errors.push("task_id 格式不符。");
  if (state.taxonomy && data.industry_id !== state.taxonomy.industry_id) warnings.push(`industry_id ${data.industry_id} 與目前載入分類 ${state.taxonomy.industry_id} 不同。`);
  if (state.taxonomy && data.taxonomy_version_used !== state.taxonomy.taxonomy_version) warnings.push(`使用版本 ${data.taxonomy_version_used}，目前版本為 ${state.taxonomy.taxonomy_version}。匯入前需確認 migration。`);

  const arrayKeys = ["findings","financials","operating_assumptions","segment_estimates","metric_claims","relationships","mentioned_entities","evidence","derived_metrics"];
  arrayKeys.forEach((key) => {
    if (key in data && !Array.isArray(data[key])) errors.push(`${key} 必須是陣列。`);
  });
  if (!isObject(data.source)) errors.push("source 必須是物件。");
  if (!isObject(data.narrative)) errors.push("narrative 必須是物件。");
  if (!isObject(data.validation)) errors.push("validation 必須是物件。");

  const nodeIds = new Set((state.taxonomy?.nodes || []).map((x) => x.node_id));
  const entityIds = new Set((state.taxonomy?.entities || []).map((x) => x.entity_id));
  const metricMap = new Map((state.taxonomy?.metric_catalog || []).map((x) => [x.metric_id,x]));
  const evidenceIds = new Set((data.evidence || []).map((x) => x.evidence_id).filter(Boolean));
  const claimIds = new Set();

  const claims = [...(data.financials || []),...(data.metric_claims || [])];
  claims.forEach((claim,index) => {
    const label = `claim ${index+1}`;
    if (!claim.claim_id) errors.push(`${label} 缺 claim_id。`);
    else if (claimIds.has(claim.claim_id)) errors.push(`重複 claim_id：${claim.claim_id}`);
    else claimIds.add(claim.claim_id);
    if (claim.node_id && !nodeIds.has(claim.node_id)) warnings.push(`${claim.claim_id || label} 使用未知 node_id：${claim.node_id}`);
    if (claim.entity_id && !entityIds.has(claim.entity_id)) warnings.push(`${claim.claim_id || label} 使用未知 entity_id：${claim.entity_id}`);
    if (claim.metric_id && !metricMap.has(claim.metric_id)) warnings.push(`${claim.claim_id || label} 使用未知 metric_id：${claim.metric_id}`);
    const metricDef = metricMap.get(claim.metric_id);
    if (metricDef && claim.unit && Array.isArray(metricDef.allowed_units) && !metricDef.allowed_units.includes(claim.unit)) {
      warnings.push(`${claim.claim_id || label} 單位 ${claim.unit} 不在 ${claim.metric_id} 建議清單。`);
    }
    (claim.evidence_ids || []).forEach((id) => {
      if (!evidenceIds.has(id)) errors.push(`${claim.claim_id || label} 引用不存在 evidence_id：${id}`);
    });
  });

  (data.findings || []).forEach((finding) => (finding.evidence_ids || []).forEach((id) => {
    if (!evidenceIds.has(id)) errors.push(`${finding.finding_id || "finding"} 引用不存在 evidence_id：${id}`);
  }));
  (data.relationships || []).forEach((rel) => {
    if (rel.from_entity_id && !entityIds.has(rel.from_entity_id)) warnings.push(`${rel.relationship_id || "relationship"} from_entity_id 尚未存在：${rel.from_entity_id}`);
    if (rel.to_entity_id && !entityIds.has(rel.to_entity_id)) warnings.push(`${rel.relationship_id || "relationship"} to_entity_id 尚未存在：${rel.to_entity_id}`);
    if (rel.node_id && !nodeIds.has(rel.node_id)) warnings.push(`${rel.relationship_id || "relationship"} 使用未知 node_id：${rel.node_id}`);
    (rel.evidence_ids || []).forEach((id) => {
      if (!evidenceIds.has(id)) errors.push(`${rel.relationship_id || "relationship"} 引用不存在 evidence_id：${id}`);
    });
  });

  if (claims.length === 0) warnings.push("沒有任何 financials 或 metric_claims；確認來源是否真的沒有可量化資訊。");
  if ((data.evidence || []).length === 0) warnings.push("沒有 evidence；正式紀錄通常至少應保留頁碼、圖表或原句。");
  if (data.validation?.conflicts_found > 0 && data.record_status !== "review_required") warnings.push("conflicts_found > 0，但 record_status 不是 review_required。");

  if (!errors.length) {
    state.validatedJson = data;
    $("download-validated").disabled = false;
  }
  renderValidation(errors,warnings,data);
}

function renderValidation(errors,warnings,data) {
  const boxes = [];
  if (!errors.length && data) boxes.push(`<div class="validation-box good"><h4>格式可匯入</h4><div class="muted">必要欄位與主要引用檢查通過。仍應由研究者判讀內容正確性。</div></div>`);
  if (errors.length) boxes.push(`<div class="validation-box bad"><h4>錯誤 ${errors.length} 項</h4><ul>${errors.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>`);
  if (warnings.length) boxes.push(`<div class="validation-box warn"><h4>警示 ${warnings.length} 項</h4><ul>${warnings.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>`);
  $("validation-result").innerHTML = boxes.join("") || `<div class="empty"><b>尚未驗證</b>貼入 JSON 後執行檢查。</div>`;
  $("json-preview").textContent = data ? JSON.stringify({
    task_id:data.task_id,
    title:data.title,
    industry_id:data.industry_id,
    taxonomy_version_used:data.taxonomy_version_used,
    record_status:data.record_status,
    findings:Array.isArray(data.findings)?data.findings.length:null,
    financials:Array.isArray(data.financials)?data.financials.length:null,
    metric_claims:Array.isArray(data.metric_claims)?data.metric_claims.length:null,
    relationships:Array.isArray(data.relationships)?data.relationships.length:null,
    evidence:Array.isArray(data.evidence)?data.evidence.length:null
  },null,2) : "—";
}

function downloadValidatedJson() {
  if (!state.validatedJson) return;
  downloadText(`${state.validatedJson.task_id || "validated-record"}.json`, JSON.stringify(state.validatedJson,null,2)+"\n", "application/json;charset=utf-8");
}

function renderSystem() {
  const repo = state.registry?.target_repository || "—";
  const base = state.registry?.base_path || "—";
  $("github-contract").textContent = [
    `Repository: ${repo}`,
    `Record path: ${state.registry?.record_path_template || "—"}`,
    `Schema: ${state.registry?.schema_path || "—"}`,
    `Aggregate: ${state.registry?.aggregate_path || "—"}`,
    `Pages path: /${base}/`
  ].join("\n");

  const checks = [
    ["Registry",Boolean(state.registry),"data/registry.json"],
    ["Taxonomy",Boolean(state.taxonomy),state.taxonomySource === "remote" ? "遠端主檔" : "本地快照"],
    ["Taxonomy version",Boolean(state.taxonomy?.taxonomy_version),state.taxonomy?.taxonomy_version || "—"],
    ["Records index",Boolean(state.recordsDoc),`${state.records.length} 筆`],
    ["Manifest",Boolean(state.manifest),state.manifest?.status || "—"],
    ["Schema",true,"schemas/analysis-record.schema.json"],
    ["Auto rebuild",true,".github/workflows/industry-intelligence-hub-rebuild.yml"]
  ];
  $("system-checks").innerHTML = checks.map(([name,ok,detail]) => `
    <div class="status-row">
      <div class="status-name">${esc(name)}</div>
      <div class="status-value mono">${esc(String(detail))}</div>
      <div class="status-state">${tag(ok ? "正常" : "失敗",ok ? "good" : "bad")}</div>
    </div>`).join("");

  $("version-info").textContent = JSON.stringify({
    hub_schema:"1.0.0",
    taxonomy_version:state.taxonomy?.taxonomy_version || null,
    taxonomy_source:state.taxonomySource,
    taxonomy_updated_at:state.taxonomy?.updated_at || null,
    index_generated_at:state.recordsDoc?.generated_at || null,
    manifest_generated_at:state.manifest?.generated_at || null,
    records:state.records.length,
    invalid_records:state.manifest?.invalid_record_count || 0
  },null,2);
}

function typeLabel(value) {
  return ({
    broker_report:"個股券商報告",earnings_call:"法說／會後紀要",industry_report:"產業報告",
    image_screenshot:"圖片／截圖",interview_notes:"訪談／文字紀錄",news:"新聞",
    company_filing:"公司公告／財報",multi_source:"多來源綜合",other:"其他"
  })[value] || value || "未分類";
}

function statusTag(status, conflicts = 0) {
  if (status === "rejected") return tag("拒絕","bad");
  if (status === "review_required" || Number(conflicts) > 0) return tag(`待審核${conflicts ? ` · ${conflicts}` : ""}`,"warn");
  return tag("已接受","good");
}

function tag(text,kind="") {
  return `<span class="tag ${kind}">${esc(String(text))}</span>`;
}

function nodeName(id) {
  return state.taxonomy?.nodes?.find((x) => x.node_id === id)?.name || id || "—";
}

function entityName(id) {
  return state.taxonomy?.entities?.find((x) => x.entity_id === id)?.name || id || "—";
}

function metricName(id) {
  return state.taxonomy?.metric_catalog?.find((x) => x.metric_id === id)?.name || id || "—";
}

function formatMetricValue(m) {
  if (m.value_type === "range" && (m.value_low !== undefined || m.value_high !== undefined)) {
    return `${m.value_low ?? "?"}–${m.value_high ?? "?"} ${m.unit || ""}`.trim();
  }
  return `${m.value ?? "—"} ${m.unit || ""}`.trim();
}

function formatConfidence(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return `${Math.round(Number(value)*100)}%`;
}

function taipeiDateParts(date = new Date()) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-CA",{
    timeZone:"Asia/Taipei",year:"numeric",month:"2-digit",day:"2-digit",
    hour:"2-digit",minute:"2-digit",second:"2-digit",hourCycle:"h23"
  }).formatToParts(date).filter((x) => x.type !== "literal").map((x) => [x.type,x.value]));
  return parts;
}

function parseTaskIdDate(taskId) {
  const m = /^TASK-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})-/.exec(taskId);
  return m ? {year:m[1],month:m[2],day:m[3],hour:m[4],minute:m[5],second:m[6]} : null;
}

function randomCode(length) {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  const bytes = crypto.getRandomValues(new Uint8Array(length));
  return [...bytes].map((b) => chars[b % chars.length]).join("");
}

function formatBytes(bytes) {
  if (bytes === null || bytes === undefined) return "—";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB","MB","GB"];
  let value = bytes / 1024, unit = units[0];
  for (let i=1;i<units.length && value>=1024;i++) { value/=1024; unit=units[i]; }
  return `${value>=10 ? value.toFixed(1) : value.toFixed(2)} ${unit}`;
}

function hashStatusLabel(status) {
  return ({calculating:"計算 SHA-256 中",skipped_large:"超過 100MB，略過雜湊",failed:"雜湊失敗",complete:"完成"})[status] || "未計算";
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("zh-TW",{timeZone:"Asia/Taipei",year:"numeric",month:"2-digit",day:"2-digit"}).format(date);
}

function formatDateTime(value) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-TW",{timeZone:"Asia/Taipei",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",second:"2-digit",hourCycle:"h23"}).format(date);
}

function truncate(text,length) {
  const value = String(text || "");
  return value.length > length ? `${value.slice(0,length)}…` : value;
}

function nullIfEmpty(value) {
  const text = String(value || "").trim();
  return text || null;
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g,(ch) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
}

function escAttr(value) {
  return esc(value).replace(/`/g,"&#96;");
}

let toastTimer;
function toast(message,kind="") {
  const el = $("toast");
  el.textContent = message;
  el.className = `toast show ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = "toast"; }, 2600);
}
