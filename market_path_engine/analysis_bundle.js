/* Market Path cross-site ChatGPT bundle builder. Runs entirely in the browser. */
const ANALYSIS_SOURCES=[
  {id:'korea_deleveraging',title:'韓股去槓桿壓力儀表板',path:'/',vars:['IND']},
  {id:'taiwan_volatility',title:'台股波動率監控',path:'/taiwan-vol/',vars:['D','QMETA','CAP','PRE','ML']},
  {id:'margin_pressure',title:'個股融資賣壓風險雷達',path:'/margin-pressure/',vars:['DATA']},
  {id:'chip_uptrend',title:'籌碼上漲機會追蹤',path:'/chip-uptrend/',vars:['DATA','IND','STATE','REPORT','MODEL','RESULTS']},
  {id:'rebound_stats',title:'暴跌後長紅的歷史機率',path:'/rebound-stats/',vars:['DATA','STATS','RESULTS']},
  {id:'crash_rebound',title:'台股崩跌反彈候選研究頁',path:'/crash-rebound-screen/',vars:['DATA','STATE','REPORT','MODEL','RESULTS']},
  {id:'ai_capex',title:'AI 算力基建對帳戰情板',path:'/ai-capex-tracker/',vars:['DATA','STATE','REPORT','MODEL','EVENTS']},
  {id:'iran_war',title:'中東戰事 × 市場傳導儀表',path:'/iran-war/',vars:['DATA','STATE','REPORT','MODEL','EVENTS']},
  {id:'tw_event_pulse',title:'事件 × 台股主流人氣股反應監測',path:'/tw-event-pulse/',vars:['DATA','STATE','REPORT','MODEL','EVENTS']},
  {id:'mainstream_index',title:'台股人氣主流股指數',path:'/mainstream-index/',vars:['DATA','STATE','INDEX_DATA','SERIES','CONSTITUENTS']},
  {id:'fed_watch',title:'FED 升降息機率儀表板',path:'/fed-watch/',vars:['DATA','STATE','MEETINGS','PROBABILITIES','HISTORY','FACTORS','COMMENTARY']}
];
const ANALYSIS_SOURCE_COUNT=ANALYSIS_SOURCES.length+1;

let latestBundleJSON='',latestPrompt='',latestBundleName='',bundleBuilding=false;
const analysisEls={
  modal:$('#analysisModal'),open:$('#analysisOpen'),close:$('#analysisClose'),password:$('#bundlePassword'),build:$('#buildBundle'),
  summary:$('#collectionSummary'),list:$('#collectionList'),prompt:$('#analysisPrompt'),size:$('#bundleSize'),message:$('#analysisMessage'),
  download:$('#downloadBundle'),copyPrompt:$('#copyPrompt'),copyAll:$('#copyAll'),openChatGPT:$('#openChatGPT')
};

function normalizeBundleText(value){return String(value||'').replace(/\u00a0/g,' ').replace(/[ \t]+\n/g,'\n').replace(/\n{3,}/g,'\n\n').trim()}
function isSensitiveBundleKey(key){return /^(?:password|passwd|secret|token|api[_-]?key|authorization|auth|salt|iv|ciphertext|payload)$/i.test(String(key||''))}
function safeBundleStringify(value){
  const seen=new WeakSet();
  return JSON.stringify(value,function(key,item){
    if(key&&isSensitiveBundleKey(key))return '[redacted]';
    if(typeof item==='bigint')return String(item);
    if(typeof item==='object'&&item!==null){if(seen.has(item))return '[circular]';seen.add(item)}
    return item;
  });
}
function safeBundleValue(value){const serialized=safeBundleStringify(value);return serialized===undefined?null:JSON.parse(serialized)}
function extractTables(doc){
  return Array.from(doc.querySelectorAll('table')).map((table,index)=>({
    index:index+1,
    caption:normalizeBundleText(table.caption?.innerText||table.previousElementSibling?.innerText||'').slice(0,240),
    rows:Array.from(table.rows).map(row=>Array.from(row.cells).map(cell=>normalizeBundleText(cell.innerText)))
  }));
}
function isBundleElementVisible(el,win){if(!el)return false;const style=win.getComputedStyle(el);return style.display!=='none'&&style.visibility!=='hidden'&&style.opacity!=='0'&&!el.hidden&&el.getClientRects().length>0}
function declaredBundleNames(doc){
  const found=new Set(),pattern=/\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=/g;
  for(const script of Array.from(doc.scripts)){let match,count=0;const source=script.textContent||'';while((match=pattern.exec(source))&&count<240){found.add(match[1]);count++}}
  return Array.from(found);
}
function extractMachineData(frame,priorityNames){
  const win=frame.contentWindow,doc=frame.contentDocument;
  const skip=/password|passwd|secret|token|auth|salt|cipher|payload|private|credential/i;
  const names=Array.from(new Set([...(priorityNames||[]),...declaredBundleNames(doc)])).filter(name=>!skip.test(name)).slice(0,260);
  const rows=[],fingerprints=new Set(),omitted=[];let total=0;const maxTotal=24*1024*1024;
  for(const name of names){
    try{
      const value=win.eval(`typeof ${name}!=="undefined"?${name}:undefined`);
      if(value===null||typeof value!=='object'||value===win||value===doc||value instanceof win.Node)continue;
      const serialized=safeBundleStringify(value);if(!serialized||serialized.length<24)continue;
      const fingerprint=`${serialized.length}:${serialized.slice(0,160)}:${serialized.slice(-160)}`;if(fingerprints.has(fingerprint))continue;
      if(total+serialized.length>maxTotal){omitted.push({name,size_chars:serialized.length,reason:'per-source 24 MB safety limit'});continue}
      fingerprints.add(fingerprint);total+=serialized.length;rows.push({name,size_chars:serialized.length,value:JSON.parse(serialized)});
    }catch(_){}
  }
  rows.sort((a,b)=>b.size_chars-a.size_chars);
  return {variables:rows,omitted,serialized_chars:total};
}
function bundleB64Bytes(value){return Uint8Array.from(atob(value),char=>char.charCodeAt(0))}
async function decryptBundleEnvelope(box,password){
  const material=await crypto.subtle.importKey('raw',new TextEncoder().encode(password),'PBKDF2',false,['deriveKey']);
  const key=await crypto.subtle.deriveKey({name:'PBKDF2',salt:bundleB64Bytes(box.salt),iterations:Number(box.iterations),hash:'SHA-256'},material,{name:'AES-GCM',length:256},false,['decrypt']);
  let ciphertext=bundleB64Bytes(box.ciphertext);
  if(box.tag){const tag=bundleB64Bytes(box.tag),joined=new Uint8Array(ciphertext.length+tag.length);joined.set(ciphertext);joined.set(tag,ciphertext.length);ciphertext=joined}
  const plain=await crypto.subtle.decrypt({name:'AES-GCM',iv:bundleB64Bytes(box.iv),tagLength:128},key,ciphertext);
  return new TextDecoder().decode(plain);
}
function extractDecryptedDocument(html){
  const doc=new DOMParser().parseFromString(html,'text/html'),scripts=[];let total=0;const maxTotal=24*1024*1024;
  for(const [index,script] of Array.from(doc.scripts).entries()){
    const content=script.textContent||'';
    if(content.length<80||/AUTH_HASH|PBKDF2|ciphertext|const\s+PAYLOAD\s*=|type=["']password/i.test(content))continue;
    if(total+content.length>maxTotal)continue;
    total+=content.length;scripts.push({index:index+1,size_chars:content.length,content});
  }
  return {title:normalizeBundleText(doc.title),visible_text:normalizeBundleText(doc.body?.innerText),tables:extractTables(doc),data_scripts:scripts,data_script_chars:total};
}
async function readProtectedBundlePayload(frame,password){
  const doc=frame.contentDocument,base=frame.contentWindow.location.href,scriptText=Array.from(doc.scripts).map(script=>script.textContent||'').join('\n');
  const resourceMatch=scriptText.match(/fetch\(["']([^"']*payload\.enc[^"']*)["']/i);
  const manifestMatch=scriptText.match(/fetch\(["']([^"']*payload-manifest\.json[^"']*)["']/i);
  let decrypted='',kind='';
  if(resourceMatch){
    const response=await fetch(new URL(resourceMatch[1],base),{cache:'no-store'});if(!response.ok)throw new Error('完整加密資料檔載入失敗');
    decrypted=await decryptBundleEnvelope(await response.json(),password);kind='encrypted-json-or-html';
  }else if(manifestMatch){
    const manifestResponse=await fetch(new URL(manifestMatch[1],base),{cache:'no-store'});if(!manifestResponse.ok)throw new Error('完整加密資料清單載入失敗');
    const manifest=await manifestResponse.json(),parts=await Promise.all(manifest.files.map(async name=>{const response=await fetch(new URL(name,base),{cache:'no-store'});if(!response.ok)throw new Error('完整加密資料分片載入失敗');return response.text()}));
    decrypted=await decryptBundleEnvelope(JSON.parse(parts.join('')),password);kind='encrypted-sharded-html';
  }else{
    const payloadMatch=scriptText.match(/const\s+PAYLOAD\s*=\s*["']([A-Za-z0-9+/=]+)["']/),iterationsMatch=scriptText.match(/const\s+ITER\s*=\s*(\d+)/);
    if(payloadMatch&&iterationsMatch){
      const raw=bundleB64Bytes(payloadMatch[1]),material=await crypto.subtle.importKey('raw',new TextEncoder().encode(password),'PBKDF2',false,['deriveKey']);
      const key=await crypto.subtle.deriveKey({name:'PBKDF2',salt:raw.slice(0,16),iterations:Number(iterationsMatch[1]),hash:'SHA-256'},material,{name:'AES-GCM',length:256},false,['decrypt']);
      const plain=await crypto.subtle.decrypt({name:'AES-GCM',iv:raw.slice(16,28)},key,raw.slice(28));decrypted=new TextDecoder().decode(plain);kind='encrypted-inline-html';
    }
  }
  if(!decrypted)return null;
  try{const value=JSON.parse(decrypted);return {kind,format:'json',size_chars:decrypted.length,value:safeBundleValue(value)}}
  catch(_){return {kind,format:'html',size_chars:decrypted.length,value:extractDecryptedDocument(decrypted)}}
}
function bundleWait(ms){return new Promise(resolve=>setTimeout(resolve,ms))}
function loadBundleFrame(url,timeout=25000){
  return new Promise((resolve,reject)=>{
    const frame=document.createElement('iframe');frame.className='collector-frame';frame.setAttribute('aria-hidden','true');
    const timer=setTimeout(()=>{frame.remove();reject(new Error('頁面載入逾時'))},timeout);
    frame.addEventListener('load',()=>{clearTimeout(timer);resolve(frame)},{once:true});
    frame.addEventListener('error',()=>{clearTimeout(timer);frame.remove();reject(new Error('頁面載入失敗'))},{once:true});
    frame.src=url;document.body.appendChild(frame);
  });
}
async function unlockBundleFrame(frame,password){
  const win=frame.contentWindow,initialDoc=frame.contentDocument,initialLength=normalizeBundleText(initialDoc.body?.innerText).length;
  const input=Array.from(initialDoc.querySelectorAll('input[type="password"]')).find(el=>isBundleElementVisible(el,win));
  if(!input)return {needed:false,unlocked:true};
  if(!password)throw new Error('需要共用密碼');
  for(const checkbox of Array.from(initialDoc.querySelectorAll('input[type="checkbox"]'))){
    const label=normalizeBundleText(checkbox.closest('label')?.innerText||checkbox.parentElement?.innerText);
    if(/記住|remember/i.test(label)){checkbox.checked=false;checkbox.dispatchEvent(new Event('change',{bubbles:true}))}
  }
  input.value=password;input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));
  const form=input.closest('form');
  const button=(form&&form.querySelector('button[type="submit"],button:not([type])'))||Array.from(initialDoc.querySelectorAll('button,input[type="submit"]')).find(el=>/解鎖|開啟|進入|登入|unlock|open/i.test(el.innerText||el.value||''));
  if(button)button.click();else if(form&&form.requestSubmit)form.requestSubmit();else input.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',code:'Enter',bubbles:true}));
  const started=Date.now();
  while(Date.now()-started<30000){
    await bundleWait(280);const doc=frame.contentDocument;if(!doc)continue;
    const visiblePassword=Array.from(doc.querySelectorAll('input[type="password"]')).some(el=>isBundleElementVisible(el,frame.contentWindow));
    const textLength=normalizeBundleText(doc.body?.innerText).length;
    if(!visiblePassword&&(textLength>Math.max(120,initialLength)||doc!==initialDoc))return {needed:true,unlocked:true};
    const error=normalizeBundleText(doc.querySelector('[role="alert"],.err,.error,#error,#err')?.innerText);
    if(error&&/錯|誤|不正確|失敗|wrong|invalid/i.test(error))throw new Error(error.slice(0,160));
  }
  throw new Error('解鎖逾時或密碼不正確');
}
async function collectBundleSource(source,password){
  const url=new URL(source.path,location.origin);url.searchParams.set('_mpe_bundle',`${Date.now()}-${source.id}`);
  const frame=await loadBundleFrame(url.href);
  try{
    let protectedPayload=null;
    try{protectedPayload=await readProtectedBundlePayload(frame,password)}catch(error){throw new Error(`完整資料解密失敗：${String(error?.message||error)}`)}
    const unlock=await unlockBundleFrame(frame,password);await bundleWait(180);
    const doc=frame.contentDocument;if(!doc||!doc.body)throw new Error('無法讀取頁面內容');
    const text=normalizeBundleText(doc.body.innerText),tables=extractTables(doc),structured=extractMachineData(frame,source.vars);
    if(/^(?:404|error response)/i.test(normalizeBundleText(doc.title))||/(?:error code:\s*404|file not found|404\s*[—-]\s*there isn't a github pages site here)/i.test(text.slice(0,900)))throw new Error('頁面不存在（404）');
    if(text.length<40)throw new Error('頁面沒有足夠的可讀內容');
    if(protectedPayload){structured.variables.unshift({name:'DECRYPTED_FULL_PAGE_PAYLOAD',size_chars:protectedPayload.size_chars,value:protectedPayload});structured.serialized_chars+=protectedPayload.size_chars}
    return {
      id:source.id,title:source.title,url:new URL(source.path,location.origin).href,collected_at:new Date().toISOString(),
      status:structured.variables.length?'ok':'partial',unlock_used:unlock.needed,full_encrypted_payload_decrypted:Boolean(protectedPayload),visible_text:text,tables,structured_data:structured,
      collection_note:protectedPayload?'已在本機解密完整頁面 payload，並收集可見內容、表格及資料腳本。':structured.variables.length?'已收集可見內容、表格及可讀取的頁面資料物件。':'已收集可見內容與表格；頁面未暴露可安全匯出的資料物件。'
    };
  }finally{frame.src='about:blank';frame.remove()}
}
function collectCurrentBundleSource(){
  const main=document.querySelector('main'),serialized=safeBundleStringify(DATA);
  return {
    id:'market_path',title:'Market Path Engine',url:location.href.split('#')[0],collected_at:new Date().toISOString(),status:'ok',unlock_used:false,
    visible_text:normalizeBundleText(main.innerText),tables:extractTables(main),
    structured_data:{variables:[{name:'DATA',size_chars:serialized.length,value:JSON.parse(serialized)}],omitted:[],serialized_chars:serialized.length},
    collection_note:'完整 Market Path payload，含模組、歷史、來源、proxy、預測封存與驗證。'
  };
}
function renderBundleSourceItem(source,state='pending',detail='等待中'){
  let node=document.querySelector(`[data-source-id="${source.id}"]`);
  if(!node){node=document.createElement('div');node.className='collection-item';node.dataset.sourceId=source.id;node.innerHTML='<i></i><span></span>';analysisEls.list.appendChild(node)}
  node.className=`collection-item ${state}`;node.querySelector('span').textContent=`${source.title} · ${detail}`;
}
function resetBundleSourceList(){analysisEls.list.innerHTML='';renderBundleSourceItem({id:'market_path',title:'Market Path Engine'});ANALYSIS_SOURCES.forEach(source=>renderBundleSourceItem(source))}
function setBundleMessage(text,state=''){analysisEls.message.textContent=text;analysisEls.message.className=`analysis-message ${state}`}
function formatBundleBytes(bytes){if(bytes<1024)return `${bytes} B`;if(bytes<1024*1024)return `${(bytes/1024).toFixed(1)} KB`;return `${(bytes/1024/1024).toFixed(1)} MB`}

function createAnalysisPrompt(bundle,fileName){
  const sourceLines=bundle.sources.map(source=>`- ${source.title}｜狀態：${source.status}｜${source.url}`).join('\n');
  const failed=bundle.sources.filter(source=>source.status==='error').map(source=>source.title);
  return `你是一位資深的全球總經、跨資產與台美韓股策略分析師。請讀取我上傳的「${fileName}」，使用其中全部可用資料，撰寫一份繁體中文、詳細但容易閱讀的股市盤勢推演報告。

【核心限制】
1. 不納入、推估或引用 EPS／企業獲利預估。
2. 先檢查每個資料源的 as-of 日期、新鮮度、缺漏與定義；不可把不同日期的數據假裝成同一時點。
3. 清楚區分：客觀觀測值、模型／proxy、以及你的推論。不得把 proxy 寫成官方統計或真實部位。
4. 只根據附件提供的資料推演；資料沒有回答的問題請明說「資料不足」，不要編造數字。
5. 若不同頁面互相矛盾，必須列出矛盾、判斷哪個訊號較領先／落後、給權重理由，不可只挑支持單一結論的證據。
6. Market Path 的 V1 機率是尚未完整校準的 heuristic prior。先引用原始機率，再用其他頁面證據做透明調整；調整後每個 horizon 的上行／盤整／下行必須合計 100%。
7. 這是研究報告，不是個人化投資建議；不要給保證式結論。

【分析方法】
- 先做資料品質審計：逐頁列出用途、資料日期、完整度、是否為歷史研究／即時監控／事件研究、可否直接用於當前盤勢。
- 建立傳導鏈：事件與地緣政治 → 油價／通膨預期 → 利率／實質利率／美元 → 流動性與信用 → VIX／VVIX／期限結構 → CTA、vol-control、CFTC 與融資籌碼 → 美股 → 台股／韓股。
- 綜合 Financial Conditions、Liquidity、Volatility、Positioning、Cross-Asset、Event Shock、AI 資本支出、台股波動／市場寬度、融資斷頭風險、籌碼上漲名單、主流股指數、事件反應、歷史反彈統計與韓股去槓桿壓力。
- 分開討論美股大盤、台股加權／櫃買／主流人氣股、韓股；不要把指數走勢與個股橫斷面機會混為一談。
- 歷史事件研究只能當條件式基本率；請說明樣本數、時代差異與本次情境是否匹配。

【必須輸出的報告結構】
1. 一頁式執行摘要：當前 regime、最重要的 5 個支持訊號、5 個反對訊號、整體信心。
2. 資料品質與時點表：每一頁一列，標示可用／降權／不可用及原因。
3. 市場傳導鏈：用清楚的因果步驟解釋目前壓力如何傳到股市，不要只羅列指標。
4. 三個 horizon 路徑表：
   - 1–5 個交易日
   - 1–4 週
   - 1–3 個月
   每段都列：原始 Market Path 機率、調整後上行／盤整／下行機率、調整依據、預期波動型態、主要觸發條件、失效條件。
5. Bull／Base／Bear 三情境：各自的傳導過程、可觀察確認訊號、會推翻情境的訊號。
6. 台股專章：加權、櫃買、主流人氣股、籌碼、融資壓力、事件反應與反彈歷史如何互相驗證；指出「大盤方向」和「個股機會」可能不同的地方。
7. 美股與韓股確認：說明它們對台股的領先或交叉確認作用。
8. 接下來要盯的 10 個觀測：依重要性排序，寫出指標、目前值／狀態、轉強門檻、轉弱門檻、可影響的 horizon。若附件沒有明確門檻，請標示為研究建議而非既有模型門檻。
9. 結論：用「目前最可能 → 次可能 → 尾部風險」收束，並列出何時需要更新判斷。

【寫作要求】
- 使用繁體中文與 Markdown；先結論、後證據。
- 多用短段落、表格與清楚的小標；第一次出現的專有名詞要用白話解釋。
- 每個重要判斷旁標註資料頁名稱與 as-of 日期；proxy 旁明寫「proxy」。
- 數字不要假精準；信心低時要明確降級措辭。

【附件內來源清單】
${sourceLines}
${failed.length?`\n收集失敗、不得假裝已讀的頁面：${failed.join('、')}`:''}

請先確認你已讀到附件中的 sources 陣列，再開始報告。`;
}

async function buildFullBundle(){
  if(bundleBuilding)return;
  const password=analysisEls.password.value||analysisSessionPassword;
  if(!password){setBundleMessage('請先輸入各研究頁的共用密碼。','error');analysisEls.password.focus();return}
  bundleBuilding=true;analysisEls.build.disabled=true;analysisEls.download.disabled=true;analysisEls.copyPrompt.disabled=true;analysisEls.copyAll.disabled=true;analysisEls.openChatGPT.disabled=true;
  setBundleMessage('正在逐頁收集，請不要關閉這個視窗。');resetBundleSourceList();analysisEls.summary.className='collection-summary';analysisEls.summary.querySelector('span').textContent=`開始建立 · 0 / ${ANALYSIS_SOURCE_COUNT}`;
  const sources=[];
  try{
    const current=collectCurrentBundleSource();sources.push(current);renderBundleSourceItem({id:'market_path',title:'Market Path Engine'},'ok','完成');
    let completed=1;
    for(const source of ANALYSIS_SOURCES){
      renderBundleSourceItem(source,'loading','收集中');
      try{
        const result=await collectBundleSource(source,password);sources.push(result);renderBundleSourceItem(source,result.status,result.full_encrypted_payload_decrypted?'完整 payload':result.status==='ok'?'完整資料':'完成（可見資料）');
      }catch(error){
        sources.push({id:source.id,title:source.title,url:new URL(source.path,location.origin).href,collected_at:new Date().toISOString(),status:'error',error:String(error?.message||error),visible_text:'',tables:[],structured_data:{variables:[],omitted:[],serialized_chars:0}});
        renderBundleSourceItem(source,'error',String(error?.message||'失敗').slice(0,80));
      }
      completed++;analysisEls.summary.querySelector('span').textContent=`正在建立 · ${completed} / ${ANALYSIS_SOURCE_COUNT}`;
    }
    const bundle={
      schema_version:'mpe-cross-site-analysis-v1',generated_at:new Date().toISOString(),generated_from:location.href,inventory_url:new URL('/github/',location.origin).href,
      privacy:'Password is never stored in this bundle. Collection happens locally in the browser; transfer occurs only when the user downloads or copies.',
      instructions:'Use visible_text, tables and structured_data together. Respect source dates, quality labels and proxy disclosures. Directory metadata is not a market signal.',
      source_count_expected:ANALYSIS_SOURCE_COUNT,source_count_collected:sources.filter(source=>source.status!=='error').length,sources
    };
    latestBundleJSON=JSON.stringify(bundle,null,2);
    const stamp=new Date().toISOString().replace(/[:.]/g,'-');latestBundleName=`market-path-full-analysis-bundle-${stamp}.json`;
    latestPrompt=createAnalysisPrompt(bundle,latestBundleName);analysisEls.prompt.value=latestPrompt;
    const bytes=new Blob([latestBundleJSON],{type:'application/json'}).size,errors=sources.filter(source=>source.status==='error').length;
    analysisEls.size.textContent=`完整資料 ${formatBundleBytes(bytes)} · 指令 ${latestPrompt.length.toLocaleString()} 字`;
    analysisEls.summary.className=`collection-summary ${errors?'error':'ok'}`;
    analysisEls.summary.querySelector('span').textContent=errors?`完成，但有 ${errors} 個頁面未能收集；詳見下方狀態`:`完成 · ${ANALYSIS_SOURCE_COUNT} / ${ANALYSIS_SOURCE_COUNT} 份來源已收集`;
    analysisEls.download.disabled=false;analysisEls.copyPrompt.disabled=false;analysisEls.copyAll.disabled=false;analysisEls.openChatGPT.disabled=false;
    setBundleMessage(errors?'資料包已建立；請留意紅色失敗項目，ChatGPT 指令會要求不得假裝已讀。':'資料包已建立。請先下載 JSON，再複製指令交給 ChatGPT。',errors?'error':'ok');
  }finally{
    analysisEls.password.value='';analysisSessionPassword='';bundleBuilding=false;analysisEls.build.disabled=false;
  }
}
function downloadBundleText(text,fileName,type){
  const blob=new Blob([text],{type}),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=fileName;document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
async function copyBundleText(text){
  try{await navigator.clipboard.writeText(text)}
  catch(_){const area=document.createElement('textarea');area.value=text;area.style.cssText='position:fixed;left:-9999px;top:0';document.body.appendChild(area);area.focus();area.select();const ok=document.execCommand('copy');area.remove();if(!ok)throw new Error('瀏覽器拒絕剪貼簿存取')}
}
function openAnalysisModal(){analysisEls.modal.hidden=false;document.body.style.overflow='hidden';resetBundleSourceList();if(analysisSessionPassword)analysisEls.password.placeholder='已沿用本次登入密碼，可直接建立';setTimeout(()=>analysisEls.build.focus(),0)}
function closeAnalysisModal(){if(bundleBuilding){setBundleMessage('資料正在建立；完成前請先保留這個視窗。','error');return}analysisEls.modal.hidden=true;document.body.style.overflow='';analysisEls.open.focus()}

analysisEls.open.addEventListener('click',openAnalysisModal);
analysisEls.close.addEventListener('click',closeAnalysisModal);
analysisEls.modal.addEventListener('click',event=>{if(event.target===analysisEls.modal)closeAnalysisModal()});
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!analysisEls.modal.hidden)closeAnalysisModal()});
analysisEls.build.addEventListener('click',buildFullBundle);
analysisEls.password.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();buildFullBundle()}});
analysisEls.download.addEventListener('click',()=>{if(!latestBundleJSON)return;downloadBundleText(latestBundleJSON,latestBundleName,'application/json;charset=utf-8');setBundleMessage(`已下載 ${latestBundleName}。接著複製分析指令。`,'ok')});
analysisEls.copyPrompt.addEventListener('click',async()=>{try{await copyBundleText(latestPrompt);setBundleMessage('分析指令已複製。請在 ChatGPT 上傳 JSON 後貼上。','ok')}catch(error){setBundleMessage(String(error.message||error),'error')}});
analysisEls.copyAll.addEventListener('click',async()=>{try{await copyBundleText(`${latestPrompt}\n\n【完整資料 JSON】\n${latestBundleJSON}`);setBundleMessage('分析指令和全部資料已複製；若貼上時過大，請改用「下載 JSON＋複製分析指令」。','ok')}catch(error){setBundleMessage(`完整內容太大或無法複製：${String(error.message||error)}。請改下載 JSON。`,'error')}});
analysisEls.openChatGPT.addEventListener('click',()=>{window.open('https://chatgpt.com/','_blank','noopener,noreferrer')});

resetBundleSourceList();
