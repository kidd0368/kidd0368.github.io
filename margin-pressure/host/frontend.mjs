// Preserve the dashboard calculations; add host authentication and input reminders.
export function hostFrontend(source) {
  const reminder = `<section class="panel excel-reminder" aria-labelledby="excelTitle">
    <div class="section-head"><div><h2 id="excelTitle">每天要更新哪些 Excel？</h2><p>每日更新三份，另永久保留一份固定基準。</p></div><button id="checkExcel" type="button" class="ghost">重新檢查檔案</button></div>
    <div class="excel-target"><label for="excelTargetDate">目標資料日</label><input id="excelTargetDate" type="date"><button id="excelTargetToday" type="button" class="ghost">跟隨今天</button><span id="excelCheckedAt" class="note"></span></div>
    <p class="note">預設使用台北今天；盤前或休市日，請改成最近已收盤的交易日。會逐檔標出「尚未更新」與應補的檔名。</p>
    <p id="excelSummary" role="status">登入後檢查來源檔案。</p>
    <p id="excelWebsite" class="excel-website"></p>
    <p class="note">這個網站的實際資料日：<b id="excelAnalysisDate">—</b>；來源資料夾：<span id="excelSourceDirectory">—</span></p>
    <p id="excelDataSource" class="note"></p>
    <div class="table-wrap"><table><thead><tr><th>每天更新</th><th>最新找到的檔案</th><th>檔名日期／檔內日期</th><th>更新狀態與處理方式</th><th>用途</th></tr></thead><tbody id="excelFiles"></tbody></table></div>
    <p id="excelAnchor" class="note"></p>
    <p class="note">會在本機讀取必要工作表的日期表頭，不上傳Excel；個股數值完整性仍由原本重算流程驗證。只改檔名不會更新內容。專用「chatgpt 計算融資維持率」檔也支援放在「gpt 維持率追蹤」第一層；同日優先主資料夾。</p>
    <details><summary>更新順序與資料套用</summary><ol><li>從CMoney重新匯出三份 Excel，儲存並關閉；確認檔內日期已到目標。</li><li>使用原本「更新融資資料（本機）」流程，完成重算、當日 AI 判讀與本機建置。</li><li>主機會自動驗證並讀取「gpt 維持率追蹤／融資雷達本機版」已完成的分析。回到本頁後重新登入，核對實際資料日；只更新 Excel 還不會產生新分析。</li></ol></details>
  </section>`;
  source = source.replace('    <div class="wrap">', '    <div class="wrap">' + reminder)
    .replace('</style>', '.excel-reminder{padding:22px;margin-bottom:20px}.excel-reminder #excelSummary{padding:12px 14px;background:var(--amber2);border-radius:10px;line-height:1.7}.excel-reminder[data-tone="danger"] #excelSummary{background:var(--red2);color:var(--red);font-weight:800}.excel-reminder td,.excel-reminder th{text-align:left;white-space:normal;overflow-wrap:anywhere}.excel-reminder td{vertical-align:top;line-height:1.65}.excel-reminder td:first-child{min-width:150px}.excel-reminder td:nth-child(3),.excel-reminder th:nth-child(3){white-space:nowrap;min-width:110px}.excel-reminder td:nth-child(4){min-width:210px}.excel-reminder tr.excel-outdated{background:var(--red2)}.excel-status{display:inline-block;padding:4px 8px;border-radius:8px;font-weight:850;color:var(--blue);background:var(--surface2)}.excel-status.outdated,.excel-status.missing,.excel-status.unavailable{color:var(--red);background:var(--red2)}.excel-status.future,.excel-status.duplicate,.excel-status.unknown{color:var(--amber);background:var(--amber2)}.excel-action{display:block;font-size:12px;line-height:1.7;margin-top:7px}.excel-target{display:flex;flex-wrap:wrap;align-items:center;gap:10px;font-size:13px}.excel-target input{padding:8px;border:1px solid var(--line);border-radius:9px;background:var(--surface);color:var(--ink)}.excel-website{font-size:13px;line-height:1.7;font-weight:800}.excel-website.outdated{color:var(--red)}.excel-reminder .note{overflow-wrap:anywhere}.excel-reminder details{margin-top:12px;font-size:13px;line-height:1.8}.excel-reminder summary{cursor:pointer;font-weight:800}@media(max-width:600px){.excel-reminder{padding:16px}.excel-reminder .section-head{align-items:start;flex-direction:column}.excel-reminder table{min-width:900px}}\n</style>');
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
    let excelCustomTarget=false;
    async function checkExcel(){
      const button=$('checkExcel');if(button.disabled)return;
      button.disabled=true;$('excelTargetDate').disabled=true;$('excelTargetToday').disabled=true;$('excelSummary').textContent='正在逐檔檢查更新狀態…';
      try{
        const target=excelCustomTarget?$('excelTargetDate').value.replaceAll('-',''):'';
        const response=await fetch('/api/input-status'+(target?'?target='+encodeURIComponent(target):''),{cache:'no-store',credentials:'same-origin'});
        if(!response.ok){
          const result=await response.json().catch(()=>({}));
          if(response.status===401&&result.code==='data_updated'){location.reload();return}
          throw new Error(response.status===401?'登入已失效，請重新整理並登入。':'暫時無法檢查來源檔案。');
        }
        const status=await response.json();
        $('excelAnalysisDate').textContent=date(status.analysisDate);
        $('excelSourceDirectory').textContent=status.sourceDirectory;
        $('excelDataSource').textContent=status.dataSource?'分析來源：'+status.dataSource.label+'；'+status.dataSource.file+(status.dataSource.warning?'。'+status.dataSource.warning:''):'';
        $('excelSummary').textContent=status.alert;
        $('excelSummary').closest('.excel-reminder').dataset.tone=status.tone;
        $('excelTargetDate').value=status.targetDate.slice(0,4)+'-'+status.targetDate.slice(4,6)+'-'+status.targetDate.slice(6,8);
        $('excelCheckedAt').textContent='最後檢查 '+new Date(status.checkedAt).toLocaleTimeString('zh-TW',{timeZone:'Asia/Taipei',hour12:false});
        $('excelWebsite').textContent=status.website.label;
        $('excelWebsite').className='excel-website '+status.website.code;
        const rows=status.files.map(file=>{
          const tr=document.createElement('tr');
          if(['outdated','missing'].includes(file.freshness.code))tr.className='excel-outdated';
          [file.expectedName,file.latest?file.latest.name+(file.duplicate?'（同日重複，需確認）':''):'未找到',file.latest?'檔名 '+date(file.latest.date)+'／檔內 '+(file.inspection?.lastDate?date(file.inspection.lastDate):'待確認'):'—'].forEach(value=>{const td=document.createElement('td');td.textContent=value;tr.append(td)});
          const state=document.createElement('td'),badge=document.createElement('span'),action=document.createElement('small');
          badge.className='excel-status '+file.freshness.code;badge.textContent=file.freshness.label;
          action.className='excel-action';action.textContent=file.action;state.append(badge,action);tr.append(state);
          const purpose=document.createElement('td');purpose.textContent=file.purpose;tr.append(purpose);
          return tr;
        });
        $('excelFiles').replaceChildren(...rows);
        $('excelAnchor').textContent='固定基準（不用每日更新）：'+(status.anchor.found?status.anchor.path:'未找到 '+status.anchor.expectedName)+'。'+status.anchor.note;
      }catch(error){$('excelSummary').textContent=error.message}
      finally{button.disabled=false;$('excelTargetDate').disabled=false;$('excelTargetToday').disabled=false}
    }
    $('checkExcel').addEventListener('click',checkExcel);
    $('excelTargetDate').addEventListener('change',()=>{excelCustomTarget=Boolean($('excelTargetDate').value);checkExcel()});
    $('excelTargetToday').addEventListener('click',()=>{excelCustomTarget=false;checkExcel()});
    const checkExcelWhenVisible=()=>{if(!document.hidden&&!$('app').classList.contains('hidden'))checkExcel()};
    window.addEventListener('focus',checkExcelWhenVisible);
    document.addEventListener('visibilitychange',checkExcelWhenVisible);
    setInterval(checkExcelWhenVisible,60000);
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
