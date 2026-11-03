// Keep the existing dashboard and its calculations; replace only authentication.
export function hostFrontend(source) {
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
      DATA=data;init();$('login').classList.add('hidden');$('app').classList.remove('hidden');
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
