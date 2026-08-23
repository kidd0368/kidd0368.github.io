"use strict";

(() => {
  const GATE_VERSION = "1.0.0";
  const STORAGE_KEY = "iih-completion-gate-receipts-v1";
  const DEFAULT_REPOSITORY = "kidd0368/kidd0368.github.io";
  const DEFAULT_BRANCH = "main";
  const DEFAULT_BASE_PATH = "industry-intelligence-hub";
  const DEFAULT_RECORD_TEMPLATE = `${DEFAULT_BASE_PATH}/data/records/{yyyy}/{mm}/{task_id}.json`;
  const DEFAULT_INDEX_PATH = `${DEFAULT_BASE_PATH}/data/records.json`;
  const DEFAULT_MANIFEST_PATH = `${DEFAULT_BASE_PATH}/data/manifest.json`;

  document.addEventListener("DOMContentLoaded", () => {
    injectStyles();
    injectGateCard();
    hardenWorkflowCopy();
    bindGateEvents();
    restoreLatestReceipt();
  });

  function injectStyles() {
    if (document.getElementById("completion-gate-styles")) return;
    const style = document.createElement("style");
    style.id = "completion-gate-styles";
    style.textContent = `
      .completion-gate-card{grid-column:1/-1}
      .completion-gate-grid{display:grid;grid-template-columns:minmax(240px,1fr) minmax(320px,1.35fr);gap:18px}
      .completion-gate-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
      .completion-gate-result{margin-top:14px}
      .completion-gate-receipt{max-height:310px;overflow:auto;white-space:pre-wrap;word-break:break-word}
      .completion-gate-status .status-row{grid-template-columns:minmax(140px,.8fr) minmax(220px,1.6fr) auto}
      .completion-gate-spinner{display:inline-block;width:13px;height:13px;border:2px solid currentColor;border-right-color:transparent;border-radius:50%;animation:iih-spin .8s linear infinite;vertical-align:-2px;margin-right:6px}
      @keyframes iih-spin{to{transform:rotate(360deg)}}
      @media(max-width:900px){.completion-gate-grid{grid-template-columns:1fr}}
    `;
    document.head.append(style);
  }

  function injectGateCard() {
    if (document.getElementById("completion-gate-card")) return;
    const promptCard = document.querySelector("#view-task > .split-grid > article.card");
    if (!promptCard?.parentElement) return;

    const card = document.createElement("article");
    card.id = "completion-gate-card";
    card.className = "card card-pad completion-gate-card";
    card.innerHTML = `
      <div class="view-head" style="margin-bottom:12px">
        <div>
          <h3>GitHub 完成閘門</h3>
          <p>只有 record 已存在於 <span class="mono">main</span>、task ID 一致、commit 可查、索引收據與內容雜湊一致時，任務才會標記完成。</p>
        </div>
        <div class="actions">
          <button class="btn" id="completion-use-current" type="button">帶入目前任務</button>
          <button class="btn btn-primary" id="completion-verify" type="button">驗證 GitHub 寫入</button>
        </div>
      </div>
      <div class="completion-gate-grid">
        <div>
          <div class="field">
            <label for="completion-task-id">任務 ID</label>
            <input id="completion-task-id" class="mono" placeholder="TASK-YYYYMMDD-HHMMSS-XXXX">
          </div>
          <div class="field" style="margin-top:10px">
            <label for="completion-record-path">預期 record path</label>
            <input id="completion-record-path" class="mono" readonly>
          </div>
          <div class="completion-gate-actions">
            <button class="btn btn-small" id="completion-copy-receipt" type="button" disabled>複製驗證收據</button>
          </div>
          <div id="completion-gate-result" class="completion-gate-result callout info">
            尚未驗證。完成 ChatGPT 分析後，回到這裡按「驗證 GitHub 寫入」。
          </div>
        </div>
        <div>
          <div id="completion-gate-status" class="status-list completion-gate-status"></div>
          <pre id="completion-gate-receipt" class="code-block completion-gate-receipt">—</pre>
        </div>
      </div>`;
    promptCard.parentElement.append(card);
    renderChecks(emptyChecks());
  }

  function hardenWorkflowCopy() {
    const steps = document.querySelectorAll("#view-overview .flow-step");
    const last = steps[steps.length - 1];
    if (!last) return;
    const bold = last.querySelector("b");
    const detail = last.querySelector("span:last-child");
    if (bold) bold.textContent = "回讀驗證後才完成";
    if (detail) detail.textContent = "record、commit、索引收據與雜湊必須一致";
  }

  function bindGateEvents() {
    const verify = document.getElementById("completion-verify");
    const useCurrent = document.getElementById("completion-use-current");
    const taskInput = document.getElementById("completion-task-id");
    const copy = document.getElementById("completion-copy-receipt");
    const generate = document.getElementById("generate-prompt");
    if (!verify || !useCurrent || !taskInput || !copy) return;

    verify.addEventListener("click", verifyCurrentTask);
    useCurrent.addEventListener("click", () => syncFromCurrentTask(true));
    taskInput.addEventListener("input", updateExpectedPath);
    taskInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") verifyCurrentTask();
    });
    copy.addEventListener("click", copyReceipt);

    if (generate) {
      generate.addEventListener("click", () => {
        setTimeout(() => {
          syncFromCurrentTask(true);
          hardenGeneratedPrompt();
        }, 0);
      });
    }
  }

  function registryConfig() {
    const registry = typeof state !== "undefined" ? state.registry : null;
    return {
      repository: registry?.target_repository || DEFAULT_REPOSITORY,
      branch: registry?.completion_gate?.branch || DEFAULT_BRANCH,
      basePath: registry?.base_path || DEFAULT_BASE_PATH,
      recordTemplate: registry?.record_path_template || DEFAULT_RECORD_TEMPLATE,
      indexPath: registry?.aggregate_path || DEFAULT_INDEX_PATH,
      manifestPath: registry?.completion_gate?.manifest_path || DEFAULT_MANIFEST_PATH
    };
  }

  function syncFromCurrentTask(showMessage = false) {
    const taskId = document.getElementById("task-id")?.value?.trim();
    const input = document.getElementById("completion-task-id");
    if (!taskId || !input) return;
    input.value = taskId;
    updateExpectedPath();
    if (showMessage) setResult("info", "已帶入目前任務；GitHub 寫入完成後再執行驗證。");
  }

  function updateExpectedPath() {
    const taskId = document.getElementById("completion-task-id")?.value?.trim() || "";
    const pathInput = document.getElementById("completion-record-path");
    if (!pathInput) return;
    pathInput.value = buildRecordPath(taskId, registryConfig().recordTemplate) || "任務 ID 格式不符";
  }

  function buildRecordPath(taskId, template) {
    const match = /^TASK-(\d{4})(\d{2})(\d{2})-(\d{6})-[A-Z0-9]{4,8}$/.exec(taskId || "");
    if (!match) return null;
    return template
      .replace("{yyyy}", match[1])
      .replace("{mm}", match[2])
      .replace("{task_id}", taskId);
  }

  function hardenGeneratedPrompt() {
    const output = document.getElementById("prompt-output");
    const taskId = document.getElementById("task-id")?.value?.trim();
    const config = registryConfig();
    const recordPath = buildRecordPath(taskId, config.recordTemplate);
    if (!output || !taskId || !recordPath || !output.value.trim()) return;

    const section = `\n【GitHub 完成閘門｜硬性完成條件】\n只有下列條件全部成立，最終回答才可把 github_write_result.status 寫成 committed：\n1. GitHub create_file／update_file 已回傳非空 commit SHA。\n2. 必須從 ${config.branch} 分支重新 fetch_file：${recordPath}。\n3. 回讀 JSON 的 task_id、industry_id、taxonomy_version_used 與本任務完全一致。\n4. 必須從 ${config.branch} 分支回讀 ${config.indexPath}，並找到相同 task_id 與 record_path。\n5. 該索引項目的 write_receipt.status 必須為 committed_and_indexed；record_commit_sha 必須等於實際寫入 commit；record_content_sha256 必須與回讀 record 內容一致。\n6. ${config.manifestPath} 不得把該 record 列為 invalid。\n若 record 已寫入但索引尚未完成，只能回報 index_pending，不得宣告完成；任何一項不符則回報 failed。不得把本地 JSON、下載檔或僅有 create_file 呼叫意圖視為已提交。\n\n最終回答固定附上：\n\`\`\`yaml\ngithub_write_result:\n  status: committed | index_pending | failed\n  repository: ${config.repository}\n  branch: ${config.branch}\n  path: ${recordPath}\n  commit_sha: 實際SHA或null\n  post_write_fetch_verified: true | false\n  task_id_verified: true | false\n  indexed_in_records_json: true | false\n  receipt_hash_verified: true | false\n\`\`\`\n`;

    if (!output.value.includes("【GitHub 完成閘門｜硬性完成條件】")) output.value += section;

    if (typeof state !== "undefined" && state.currentTaskPacket) {
      state.currentTaskPacket.github_target = {
        ...(state.currentTaskPacket.github_target || {}),
        branch: config.branch,
        aggregate_path: config.indexPath,
        manifest_path: config.manifestPath
      };
      state.currentTaskPacket.github_completion_gate = {
        version: GATE_VERSION,
        required_status: "committed_and_indexed",
        required_checks: [
          "record_exists_on_main",
          "task_id_matches",
          "commit_sha_exists",
          "record_is_indexed",
          "content_sha256_matches",
          "manifest_has_no_invalid_entry"
        ]
      };
    }
  }

  async function verifyCurrentTask() {
    const taskId = document.getElementById("completion-task-id")?.value?.trim();
    const config = registryConfig();
    const recordPath = buildRecordPath(taskId, config.recordTemplate);
    const button = document.getElementById("completion-verify");

    if (!recordPath) {
      setResult("bad", "任務 ID 格式不正確，無法計算 GitHub 路徑。");
      renderChecks(emptyChecks());
      return;
    }

    if (button) {
      button.disabled = true;
      button.innerHTML = '<span class="completion-gate-spinner"></span>驗證中';
    }
    setResult("info", "正在直接查驗 GitHub main、commit、records.json 與 manifest.json…");
    renderChecks(pendingChecks());

    const receipt = {
      gate_version: GATE_VERSION,
      checked_at: new Date().toISOString(),
      status: "failed",
      repository: config.repository,
      branch: config.branch,
      task_id: taskId,
      record_path: recordPath,
      commit_sha: null,
      record_content_sha256: null,
      checks: {}
    };

    try {
      const recordUrl = rawUrl(config.repository, config.branch, recordPath);
      const indexUrl = rawUrl(config.repository, config.branch, config.indexPath);
      const manifestUrl = rawUrl(config.repository, config.branch, config.manifestPath);

      const recordResponse = await fetch(recordUrl, {cache: "no-store"});
      receipt.checks.record_exists_on_main = recordResponse.ok;
      if (!recordResponse.ok) {
        receipt.status = recordResponse.status === 404 ? "not_found" : "failed";
        throw new Error(`record 讀取失敗：HTTP ${recordResponse.status}`);
      }

      const recordText = await recordResponse.text();
      const record = JSON.parse(recordText);
      const contentSha = await sha256(recordText);
      receipt.record_content_sha256 = contentSha;
      receipt.checks.task_id_matches = record.task_id === taskId;
      receipt.checks.industry_id_present = Boolean(record.industry_id);
      receipt.checks.taxonomy_version_present = Boolean(record.taxonomy_version_used);

      const [indexResponse, manifestResponse, commitResponse] = await Promise.all([
        fetch(indexUrl, {cache: "no-store"}),
        fetch(manifestUrl, {cache: "no-store"}),
        fetch(commitListUrl(config.repository, config.branch, recordPath), {
          cache: "no-store",
          headers: {Accept: "application/vnd.github+json"}
        })
      ]);

      const indexDoc = indexResponse.ok ? await indexResponse.json() : null;
      const manifest = manifestResponse.ok ? await manifestResponse.json() : null;
      const commits = commitResponse.ok ? await commitResponse.json() : [];
      const latestCommit = Array.isArray(commits) ? commits[0]?.sha || null : null;
      receipt.commit_sha = latestCommit;
      receipt.checks.commit_sha_exists = Boolean(latestCommit);

      const indexRow = indexDoc?.records?.find((row) => row.task_id === taskId) || null;
      const indexedFullPath = indexRow ? normalizeIndexedPath(indexRow.record_path, config.basePath) : null;
      receipt.checks.record_is_indexed = Boolean(indexRow && indexedFullPath === recordPath);

      const indexedReceipt = indexRow?.write_receipt || null;
      receipt.checks.receipt_status_complete = indexedReceipt?.status === "committed_and_indexed";
      receipt.checks.receipt_commit_matches = Boolean(latestCommit && indexedReceipt?.record_commit_sha === latestCommit);
      receipt.checks.receipt_hash_matches = indexedReceipt?.record_content_sha256 === contentSha;
      receipt.checks.manifest_has_no_invalid_entry = Boolean(
        manifestResponse.ok &&
        !(manifest?.validation_errors || []).some((item) => item.task_id === taskId || normalizeIndexedPath(item.path, config.basePath) === recordPath)
      );

      const hardChecks = [
        "record_exists_on_main",
        "task_id_matches",
        "commit_sha_exists",
        "record_is_indexed",
        "receipt_status_complete",
        "receipt_commit_matches",
        "receipt_hash_matches",
        "manifest_has_no_invalid_entry"
      ];
      const complete = hardChecks.every((key) => receipt.checks[key] === true);
      const indexPending = receipt.checks.record_exists_on_main && receipt.checks.task_id_matches && receipt.checks.commit_sha_exists && !complete;
      receipt.status = complete ? "committed" : (indexPending ? "index_pending" : "failed");

      renderChecks(checksForReceipt(receipt));
      renderReceipt(receipt);
      persistReceipt(receipt);

      if (receipt.status === "committed") {
        setResult("good", `驗證完成：record、commit、索引收據與內容雜湊一致。Commit ${latestCommit.slice(0, 12)}…`);
      } else if (receipt.status === "index_pending") {
        setResult("warn", "record 已存在，但索引收據尚未全部一致；目前不能標記完成。稍後重新驗證即可。");
      } else {
        setResult("bad", "GitHub 寫入驗證失敗；請依右側檢查結果修正，不得把任務標記完成。");
      }
    } catch (error) {
      receipt.error = error.message;
      renderChecks(checksForReceipt(receipt));
      renderReceipt(receipt);
      persistReceipt(receipt);
      setResult("bad", `驗證失敗：${error.message}`);
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = "驗證 GitHub 寫入";
      }
    }
  }

  function emptyChecks() {
    return [
      ["main 上存在 record", null, "尚未檢查"],
      ["task ID 一致", null, "尚未檢查"],
      ["commit SHA 可查", null, "尚未檢查"],
      ["已進入 records.json", null, "尚未檢查"],
      ["索引收據與雜湊一致", null, "尚未檢查"],
      ["manifest 無 invalid", null, "尚未檢查"]
    ];
  }

  function pendingChecks() {
    return emptyChecks().map(([name]) => [name, null, "檢查中…"]);
  }

  function checksForReceipt(receipt) {
    const c = receipt.checks || {};
    return [
      ["main 上存在 record", c.record_exists_on_main, receipt.record_path],
      ["task ID 一致", c.task_id_matches, receipt.task_id],
      ["commit SHA 可查", c.commit_sha_exists, receipt.commit_sha || "—"],
      ["已進入 records.json", c.record_is_indexed, c.record_is_indexed ? "路徑一致" : "未找到或路徑不同"],
      ["索引收據與雜湊一致", Boolean(c.receipt_status_complete && c.receipt_commit_matches && c.receipt_hash_matches), c.receipt_status_complete ? "receipt 已產生" : "receipt 尚未完成"],
      ["manifest 無 invalid", c.manifest_has_no_invalid_entry, c.manifest_has_no_invalid_entry ? "正常" : "未確認或有錯誤"]
    ];
  }

  function renderChecks(rows) {
    const container = document.getElementById("completion-gate-status");
    if (!container) return;
    container.innerHTML = rows.map(([name, ok, detail]) => {
      const kind = ok === true ? "good" : ok === false ? "bad" : "info";
      const label = ok === true ? "通過" : ok === false ? "失敗" : "待檢查";
      return `<div class="status-row"><div class="status-name">${escapeHtml(name)}</div><div class="status-value mono">${escapeHtml(detail || "—")}</div><div class="status-state"><span class="tag ${kind}">${label}</span></div></div>`;
    }).join("");
  }

  function renderReceipt(receipt) {
    const output = document.getElementById("completion-gate-receipt");
    const copy = document.getElementById("completion-copy-receipt");
    if (output) output.textContent = JSON.stringify(receipt, null, 2);
    if (copy) copy.disabled = false;
  }

  function setResult(kind, message) {
    const result = document.getElementById("completion-gate-result");
    if (!result) return;
    result.className = `completion-gate-result callout ${kind}`;
    result.textContent = message;
  }

  async function copyReceipt() {
    const text = document.getElementById("completion-gate-receipt")?.textContent || "";
    if (!text || text === "—") return;
    try {
      await navigator.clipboard.writeText(text);
      setResult("good", "驗證收據已複製。");
    } catch {
      setResult("warn", "瀏覽器無法直接複製，請手動選取右側收據。");
    }
  }

  function persistReceipt(receipt) {
    try {
      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
      stored[receipt.task_id] = receipt;
      stored.__latest = receipt.task_id;
      localStorage.setItem(STORAGE_KEY, JSON.stringify(stored));
    } catch (error) {
      console.warn("completion receipt storage failed", error);
    }
  }

  function restoreLatestReceipt() {
    try {
      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
      const receipt = stored[stored.__latest];
      if (!receipt) {
        syncFromCurrentTask(false);
        return;
      }
      const input = document.getElementById("completion-task-id");
      if (input) input.value = receipt.task_id;
      updateExpectedPath();
      renderChecks(checksForReceipt(receipt));
      renderReceipt(receipt);
      if (receipt.status === "committed") setResult("good", `上次驗證完成：${receipt.task_id}`);
      else if (receipt.status === "index_pending") setResult("warn", `上次狀態為索引待完成：${receipt.task_id}`);
      else setResult("info", `已載入上次驗證結果：${receipt.task_id}`);
    } catch {
      syncFromCurrentTask(false);
    }
  }

  function normalizeIndexedPath(path, basePath) {
    if (!path) return null;
    const value = String(path).replace(/^\/+/, "");
    return value.startsWith(`${basePath}/`) ? value : `${basePath}/${value}`;
  }

  function rawUrl(repository, branch, path) {
    return `https://raw.githubusercontent.com/${repository}/${encodeURIComponent(branch)}/${encodePath(path)}?v=${Date.now()}`;
  }

  function commitListUrl(repository, branch, path) {
    return `https://api.github.com/repos/${repository}/commits?sha=${encodeURIComponent(branch)}&path=${encodeURIComponent(path)}&per_page=1`;
  }

  function encodePath(path) {
    return String(path).split("/").map(encodeURIComponent).join("/");
  }

  async function sha256(text) {
    const bytes = new TextEncoder().encode(text);
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (ch) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
  }

  window.IIHCompletionGate = {
    version: GATE_VERSION,
    buildRecordPath,
    normalizeIndexedPath,
    checksForReceipt
  };
})();
