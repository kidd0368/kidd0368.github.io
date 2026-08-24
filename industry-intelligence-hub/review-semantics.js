"use strict";

(() => {
  const VERSION = "1.0.0";
  const originalGeneratePrompt = generatePrompt;
  const originalRenderOverview = renderOverview;
  const originalPopulateRecordFilters = populateRecordFilters;
  const originalRenderRecordDetail = renderRecordDetail;
  const originalValidateJsonInput = validateJsonInput;

  generatePrompt = function generatePromptWithReviewSemantics() {
    originalGeneratePrompt();
    hardenGeneratedPrompt();
  };

  renderOverview = function renderOverviewWithActionableReviewCount() {
    originalRenderOverview();
    const actionCount = (state.records || []).filter((row) => userActionCount(row) > 0).length;
    const value = document.getElementById("stat-review");
    if (value) value.textContent = String(actionCount);
    const card = value?.closest(".stat-card");
    const label = card?.querySelector(".stat-label");
    const detail = card?.querySelector(".stat-detail");
    if (label) label.textContent = "待你確認";
    if (detail) detail.textContent = "只有需要你選擇的項目";
  };

  populateRecordFilters = function populateRecordFiltersWithClearLabels() {
    originalPopulateRecordFilters();
    const select = document.getElementById("record-status-filter");
    if (!select) return;
    const labels = {
      "": "全部狀態",
      accepted: "已完成",
      review_required: "待你確認",
      rejected: "拒絕"
    };
    [...select.options].forEach((option) => {
      if (option.value in labels) option.textContent = labels[option.value];
    });
  };

  statusTag = function statusTagWithReviewSemantics(status, conflicts = 0) {
    if (status === "rejected") return tag("拒絕", "bad");
    const action = Number(conflicts || 0);
    if (status === "review_required" || action > 0) return tag(`待你確認${action ? ` · ${action}` : ""}`, "warn");
    return tag("已完成", "good");
  };

  renderRecentRecords = function renderRecentRecordsWithReviewSemantics() {
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
              <td>${researchStatusTag(r)}</td>
            </tr>`).join("")}
          </tbody>
        </table>
      </div>`;
  };

  renderRecords = function renderRecordsWithReviewSemantics() {
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
              <td>${researchStatusTag(r)}</td>
            </tr>`).join("")}
          </tbody>
        </table>
      </div>`;
  };

  renderRecordDetail = function renderRecordDetailWithReviewSemantics(record) {
    const actionItems = (record.review_items || []).filter((item) =>
      item?.requires_user_action === true && !["resolved", "closed", "dismissed"].includes(String(item.status || "open"))
    );
    const notes = Array.isArray(record.important_notes) ? record.important_notes : [];
    const statusSection = `
      <section class="dialog-section">
        <h4>研究狀態</h4>
        <div class="validation-box ${actionItems.length ? "warn" : "good"}">
          <b>${actionItems.length ? `待你確認 ${actionItems.length} 項` : "已完成"}</b>
          <div class="muted">${actionItems.length ? "以下項目需要你的選擇；一般來源差異與檔名問題不會列入。" : "目前沒有需要你採取動作的項目。"}</div>
        </div>
      </section>`;
    const actionSection = actionItems.length ? `
      <section class="dialog-section">
        <h4>待你確認</h4>
        ${actionItems.map((item) => `
          <div class="validation-box warn">
            <b>${esc(item.title || item.question || item.review_id || "待確認事項")}</b>
            <div class="prose">${esc(item.question || item.description || "")}</div>
            ${item.why_user_input_needed ? `<div class="muted">為何需要你決定：${esc(item.why_user_input_needed)}</div>` : ""}
            ${Array.isArray(item.options) && item.options.length ? `<div>${item.options.map((option) => `<span class="tag">${esc(typeof option === "string" ? option : (option.label || option.value || JSON.stringify(option)))}</span>`).join("")}</div>` : ""}
            ${item.recommended_option ? `<div class="muted">系統建議：${esc(String(item.recommended_option))}</div>` : ""}
          </div>`).join("")}
      </section>` : "";
    const noteSection = notes.length ? `
      <section class="dialog-section">
        <h4>來源與口徑註記</h4>
        ${notes.map((note) => `
          <div class="validation-box ${["important","warning","critical"].includes(note.severity) ? "warn" : ""}">
            <b>${esc(note.title || note.note_id || "註記")}</b>
            <div class="prose">${esc(note.description || "")}</div>
            ${note.resolution ? `<div class="muted">處理方式：${esc(note.resolution)}</div>` : ""}
          </div>`).join("")}
      </section>` : "";
    return `${statusSection}${actionSection}${noteSection}${originalRenderRecordDetail(record)}`;
  };

  validateJsonInput = function validateJsonInputWithReviewSemantics() {
    originalValidateJsonInput();
    const text = document.getElementById("json-input")?.value?.trim();
    if (!text) return;
    let data;
    try { data = JSON.parse(text); } catch { return; }
    const actionItems = (data.review_items || []).filter((item) =>
      item?.requires_user_action === true && !["resolved", "closed", "dismissed"].includes(String(item.status || "open"))
    );
    const result = document.getElementById("validation-result");
    if (!result) return;
    if (data.record_status === "review_required" && actionItems.length === 0) {
      result.insertAdjacentHTML("afterbegin", `<div class="validation-box warn"><h4>狀態語意不完整</h4><div class="muted">record_status 是 review_required，但沒有任何 requires_user_action=true 的 review_items。應改為 accepted，或補上明確問題、選項與建議。</div></div>`);
    }
    const filenameConflicts = (data.conflicts || []).filter((item) => /檔名/.test(JSON.stringify(item)));
    if (filenameConflicts.length) {
      result.insertAdjacentHTML("afterbegin", `<div class="validation-box warn"><h4>檔名不應列為衝突</h4><div class="muted">公司身分應以正文與股票代碼判定；檔名差異請改存 important_notes，且 requires_user_action=false。</div></div>`);
    }
  };

  document.addEventListener("DOMContentLoaded", () => {
    installStaticLabels();
  });

  function userActionCount(record) {
    if (record?.user_action_required_count !== undefined) return Number(record.user_action_required_count || 0);
    if (record?.validation?.user_action_required_count !== undefined) return Number(record.validation.user_action_required_count || 0);
    return record?.record_status === "review_required" ? Number(record.conflicts_found || 1) : 0;
  }

  function importantNoteCount(record) {
    if (record?.important_note_count !== undefined) return Number(record.important_note_count || 0);
    if (record?.validation?.important_note_count !== undefined) return Number(record.validation.important_note_count || 0);
    return (record?.important_notes || []).filter((note) => ["important","warning","critical"].includes(note?.severity)).length;
  }

  function researchStatusTag(record) {
    const receiptStatus = record?.write_receipt?.status;
    if (receiptStatus && receiptStatus !== "committed_and_indexed") return tag("寫入驗證失敗", "bad");
    if (record?.record_status === "rejected") return tag("拒絕", "bad");
    const action = userActionCount(record);
    if (action > 0) return tag(`待你確認 · ${action}`, "warn");
    const important = importantNoteCount(record);
    if (important > 0) return tag(`已完成 · ${important}項註記`, "info");
    return tag("已完成", "good");
  }

  function installStaticLabels() {
    const statusFilter = document.getElementById("record-status-filter");
    if (statusFilter) {
      [...statusFilter.options].forEach((option) => {
        if (option.value === "accepted") option.textContent = "已完成";
        if (option.value === "review_required") option.textContent = "待你確認";
      });
    }
  }

  function hardenGeneratedPrompt() {
    const output = document.getElementById("prompt-output");
    if (!output?.value?.trim() || output.value.includes("【審核狀態語意｜硬性規則】")) return;
    output.value += `

【審核狀態語意｜硬性規則】
1. 公司與來源身分判定優先順序：正文公司全名與股票代碼 → 表格與業務內容 → 官方來源交叉驗證 → 檔名。檔名錯誤或截斷只作 source metadata 註記，不得列為 conflict，不得增加待審核數。
2. 不同來源的發布日、引用日、事件日或更新日應各自保留並註明其意義。日期不同本身不是衝突；只有在兩者明確宣稱同一事件且日期差異會改變財務認列期間或核心結論時，才可能升級。
3. 券商估計、公司展望、官方實際值或不同券商預估不同，是來源口徑差異，不自動構成待使用者審核。
4. 同一份報告內部出現年度、單位或數值不一致時，分析者應依主文語境、估值公式、表格標題與其他證據選擇可防禦的主要解讀；替代解讀保留為 important_notes。除非沒有任何合理預設且會污染下游數字，否則不要求使用者決定。
5. record_status 只有在存在至少一項未解決的 review_items，且該項 requires_user_action=true 時，才能設為 review_required。每個 review_item 必須列出明確問題、為何需要使用者決定、可選方案與系統建議。
6. 若 user_action_required_count=0，即使有 important_notes、source notes、不同來源日期或已合理處理的歧義，record_status 必須為 accepted。
7. validation.conflicts_found 僅計算真正需要使用者選擇的未解決事項；一般註記不得計入。另填 validation.user_action_required_count、validation.important_note_count 與 validation.source_note_count。
8. 最終回答必須分開列出「需要使用者處理的事項」與「僅供知悉的來源／口徑註記」。若前者為0，直接寫明「你不需要做任何事」。
`;
    if (typeof state !== "undefined" && state.currentTaskPacket) {
      state.currentTaskPacket.review_semantics = {
        version: VERSION,
        review_required_only_when_user_action_required: true,
        filename_is_metadata_only: true,
        different_source_dates_are_notes_by_default: true,
        required_review_item_fields: ["question", "why_user_input_needed", "options", "recommended_option", "requires_user_action"]
      };
    }
  }
})();
