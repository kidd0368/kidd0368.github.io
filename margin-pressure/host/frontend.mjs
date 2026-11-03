// Keep the existing dashboard and its calculations; replace only authentication.
export function hostFrontend(source) {
  const reminder = `<section class="panel excel-reminder" aria-labelledby="excelTitle">
    <div class="section-head"><div><h2 id="excelTitle">每天要更新哪些 Excel？</h2><p>每日更新三份，另永久保留一份固定基準。</p></div><button id="checkExcel" type="button" class="ghost">重新檢查檔案</button></div>
    <p id="excelSummary" role="status">登入後檢查來源檔案。</p>
    <p class="note">這個網站的實際資料日：<b id="excelAnalysisDate">—</b>；來源資料夾：<span id="excelSourceDirectory">—</span></p>
    <div class="table-wrap"><table><thead><tr><th>每天更新</th><th>最新找到的檔案</th><th>檔名日期</th><th>用途</th></tr></thead><tbody id="excelFiles"></tbody></table></div>
    <p id="excelAnchor" class="note"></p>
    <p class="note">檔名日期是匯出日，不保證等於檔內最新交易日；這裡只檢查檔名與檔案是否存在，不會讀取或上傳 Excel 內容。專用「chatgpt 計算融資維持率」檔也支援放在「gpt 維持率追蹤」第一層；同日優先主資料夾。</p>
    <details><summary>更新順序與資料套用</summary><ol><li>在來源資料夾更新三份 Excel，儲存並關閉。</li><li>使用原本「更新融資資料（本機）」流程，完成資料重算及當日 AI 判讀。</li><li>將完成判讀後的新 payload.enc 套用到此主機版，再重新啟動，核對畫面實際資料日。只更新 Excel 不會自動更新本頁數據。</li></ol></details>
  </section>`;
  source = source.replace('    <div class="wrap">', '    <div class="wrap">' + reminder)
    .replace('</style>', '.excel-reminder{padding:22px;margin-bottom:20px}.excel-reminder #excelSummary{padding:12px 14px;background:var(--amber2);border-radius:10px;line-height:1.7}.excel-reminder td,.excel-reminder th{text-align:left;white-space:normal;overflow-wrap:anywhere}.excel-reminder td{vertical-align:top;line-height:1.65}.excel-reminder td:first-child{min-width:160px}.excel-reminder td:nth-child(3),.excel-reminder th:nth-child(3){white-space:nowrap;min-width:110px}.excel-reminder .note{overflow-wrap:anywhere}.excel-reminder details{margin-top:12px;font-size:13px;line-height:1.8}.excel-reminder summary{cursor:pointer;font-weight:800}@media(max-width:600px){.excel-reminder{padding:16px}.excel-reminder .section-head{align-items:start;flex-direction:column}.excel-reminder table{min-width:700px}}\n</style>');
  const oldStart = source.indexOf('    async function unlock(password){');
  const oldEnd = source.indexOf('    function init(){', oldStart);
  if (oldStart < 0 || oldEnd < 0) throw new Error('找不到原頁面登入區段，請檢查範本版本。');
  source = source.slice(0, oldStart) + `
    async function loadData(){
      const response=await fetch('/api/data',{cache:'no-store',credentials:'same-origin'});
      if(!response.ok)throw new Error('登入已失效，請重新登入。');
      return response.json();
    }
    async function unlock(password){
      const response=await fetch('/api/login',{
        method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({password})
      });
      if(!response.ok){
        const result=await response.json().catch(()=>({}));
        throw new Error(result.error||'登入失敗，請稍後重試。');
      }
      return loadData();
    }
    function showDashboard(data){
      DATA=data;init();$('login').classList.add('hidden');$('app').classList.remove('hidden');checkExcel();
      $('password').value='';$('loginError').textContent='';
    }
    $('loginForm').addEventListener('submit',async e=>{
      e.preventDefault();const button=e.submitter||$('loginForm').querySelector('button');
      button.disabled=true;$('loginError').textContent='正在登入…';
      try{showDashboard(await unlock($('password').value))}
      catch(error){$('loginError').textContent=error.message}
      finally{button.disabled=false;$('password').value=''}
    });
    $('logout').addEventListener('click',async()=>{
      try{
        const response=await fetch('/api/logout',{method:'POST',credentials:'same-origin'});
        if(!response.ok)throw new Error();
        location.reload();
      }catch{toast('登出失敗，請重試。')}
    });
    async function checkExcel(){
      const button=$('checkExcel');button.disabled=true;$('excelSummary').textContent='正在檢查來源檔案…';
      try{
        const response=await fetch('/api/input-status',{cache:'no-store',credentials:'same-origin'});
        if(!response.ok)throw new Error(response.status===401?'登入已失效，請重新整理並登入。':'暫時無法檢查來源檔案。');
        const status=await response.json();
        $('excelAnalysisDate').textContent=date(status.analysisDate);
        $('excelSourceDirectory').textContent=status.sourceDirectory;
        $('excelSummary').textContent=status.summary;
        const rows=status.files.map(file=>{
          const tr=document.createElement('tr');
          [file.expectedName,file.latest?file.latest.name+(file.duplicate?'（同日重複，需確認）':''):'未找到',file.latest?date(file.latest.date):'—',file.purpose].forEach(value=>{const td=document.createElement('td');td.textContent=value;tr.append(td)});
          return tr;
        });
        $('excelFiles').replaceChildren(...rows);
        $('excelAnchor').textContent='固定基準（不用每日更新）：'+(status.anchor.found?status.anchor.path:'未找到 '+status.anchor.expectedName)+'。'+status.anchor.note;
      }catch(error){$('excelSummary').textContent=error.message}
      finally{button.disabled=false}
    }
    $('checkExcel').addEventListener('click',checkExcel);
    loadData().then(showDashboard).catch(()=>{});

` + source.slice(oldEnd);
  return source
    .replace('const dec=new TextDecoder();', '')
    .replace('    const b64=s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));', '')
    .replace('<title>私人融資賣壓風險雷達</title>', '<title>融資賣壓風險雷達｜主機版</title>')
    .replace('<h1>私人融資壓力頁面</h1>', '<h1>融資賣壓風險雷達</h1>')
    .replace('資料以瀏覽器端 AES-256-GCM 加密。輸入密碼後，瀏覽器才會解開市場與個股資料。', '輸入原本的頁面密碼登入，即可查詢市場與個股的融資壓力。')
    .replace('這是靜態私人頁，不會把密碼傳到伺服器；但它不是銀行等級的登入系統，請勿把連結與密碼交給不相關的人。', '由你的主機驗證密碼。重新整理可保留登入，使用完畢可按右上角登出。')
    .replace('<button id="theme" class="ghost">深色</button>', '<button id="theme" class="ghost">深色</button><button id="logout" class="ghost">登出</button>')
    .replace('私人加密檢視', '主機版');
}
