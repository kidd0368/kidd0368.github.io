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
  return `你是一位資深的全球總經、跨資產與台美韓股策略分析師，同時也是擅長向一般讀者說故事的財經編輯。請讀取我上傳的「${fileName}」，使用其中全部可用資料，寫成一份可以直接轉傳給朋友、客戶或一般投資人閱讀的繁體中文市場研究報告。

【讀者與成品定位】
1. 讀者沒有看過這些儀表板，也不熟悉金融工程；只假設他知道股票會漲跌、利率會影響市場。
2. 報告必須能獨立閱讀。正文不要出現「JSON、sources 陣列、你上傳的附件、依照指令」等製作過程用語。
3. 先用白話說明發生什麼事、為什麼重要、可能如何影響股市，再補專有名詞與數字。不可只把數據、訊號或表格逐項貼出。
4. 第一次出現專有名詞時，立刻用一句白話翻譯，並說明它和股市的關係。例如：實質利率是扣除通膨後的資金成本；信用利差是企業借錢相對政府債券多付的風險價格。
5. 成品是可公開分享的研究報告，不是寫給模型作者的技術紀錄，也不是個人化投資建議。

【核心限制】
1. 不納入、推估或引用 EPS／企業獲利預估。
2. 先在分析過程中檢查每個來源的資料日期、新鮮度、缺漏與定義；不可把不同日期的數據假裝成同一時點。正文只交代會改變結論的重要時點問題，完整審計放在文末附錄。
3. 清楚區分客觀觀測值、模型／proxy，以及分析推論。不得把 proxy 寫成官方統計或真實部位。
4. 只根據附件資料推演；沒有資料支持的地方明說「目前資料不足」，不要編造數字、門檻或因果。
5. 若不同頁面互相矛盾，要說明矛盾為什麼會出現、哪個訊號可能較領先或落後，以及如何影響結論，不可只挑支持單一方向的證據。
6. Market Path 的 V1 機率是尚未完整校準的初步機率。先引用原始機率，再用其他頁面證據透明調整；每個時間範圍的上行／盤整／下行必須合計 100%。
7. 不用保證式語氣；用「較可能、條件式、目前證據偏向」等符合不確定性的措辭。

【先建立報告主線，再寫正文】
- 先找出一個中心判斷：市場目前最主要在交易什麼，以及多空最大的拉扯是什麼。
- 把因果串成一條讀者跟得上的故事：Fed 升降息預期 → 市場利率與美元 → 資金與信用環境 → 波動與系統性資金部位 → 美股 → 台股與韓股。油價、地緣政治、AI 資本支出、籌碼與融資壓力應放在這條主線中解釋，不要各寫成互不相干的小抄。
- 每個主要段落依序回答四件事：看到了什麼證據 → 白話代表什麼 → 對股市可能有何影響 → 哪個訊號會讓判斷改變。
- 將「大盤方向、波動風險、個股機會」分開說明，避免把指數偏弱誤寫成所有股票都沒有機會。
- 歷史事件研究只能當條件式參考；說明樣本數、時代差異與本次情境是否相似。

【必須輸出的閱讀順序】
1. 報告標題與資料截止日：標題要像財經文章，簡短、具體，不用模型名稱當標題。
2. 「給一般讀者的三分鐘結論」：用 3–5 個短段落回答目前盤勢、最可能路徑、最大風險與最重要觀察點。每段先用粗體寫一句結論，再用 2–4 句完整敘事解釋。開頭不要放表格、方法或資料品質清單。
3. 「市場現在到底在交易什麼」：用完整敘事交代背景、核心矛盾與目前多空力量。讀者只看這一節也應理解市場故事。
4. 「壓力如何一步一步傳到股市」：沿著政策預期、利率／美元、流動性／信用、波動／部位、美股、台韓股的順序寫。可以先放一行箭頭摘要，但每一步都必須另用白話段落解釋。
5. 「未來三段時間可能怎麼走」：分別討論 1–5 個交易日、1–4 週、1–3 個月。每段先用 2–4 個段落說明主路徑，再放一張精簡表列原始機率、調整後上行／盤整／下行機率、主要觸發與失效條件。解釋這些百分比是條件式可能性，不是報酬率或保證。
6. 「三個可能劇本」：Bull／Base／Bear 各寫成一段可想像的市場故事，說明事情會按什麼順序發生、哪些訊號會確認、哪些訊號會推翻它。
7. 「台股投資人應如何理解」：分開解釋加權指數、櫃買、主流人氣股、籌碼、融資壓力、事件反應與反彈歷史；明確指出大盤與個股機會可能不同。
8. 「美股與韓股提供什麼線索」：說明兩者為何可能領先台股或提供交叉確認，不要只重複漲跌。
9. 「接下來最值得盯的 10 件事」：依重要性排序。每項用白話名稱、目前狀態、為何重要、轉強／轉弱條件、影響的時間範圍。資料沒有門檻時，清楚標示為研究建議。
10. 「如果只記得三件事」：用三個完整句子收束目前最可能、次可能與尾部風險，並說明何時需要更新報告。
11. 「附錄：資料日期、品質與名詞」：每個來源一列，標示可用／降權／不可用、日期與原因；再列出文中必要名詞的白話解釋。技術細節放這裡，不要阻斷前面的故事。

【白話寫作規則】
- 使用繁體中文與 Markdown；完整內容應足以獨立成篇，正文以約 3,000–5,000 個中文字為目標，不含表格與附錄。
- 段落以 2–4 句為主；多用「因為、所以、但如果、這代表」連接因果。避免只有名詞和冒號的碎片句。
- 專有名詞第一次出現時，用「中文解釋（專有名詞）」格式。不能直接丟出 VIX、VVIX、CTA、vol-control、CFTC、OAS、RRP、TGA 等縮寫。
- 建議的白話翻譯：VIX＝市場對未來波動的警報器；VVIX＝這個警報器本身有多不穩；CTA＝依價格趨勢自動加減部位的資金；vol-control＝市場越震盪就越縮小風險的資金；CFTC 部位＝期貨市場大型交易人的站位；信用利差＝企業借錢相對政府債券多付的風險價格。
- 每個重要數字後都要回答「這個數字高或低代表什麼、和什麼相比、會如何影響市場」。不要出現沒有解釋的數字堆。
- 表格前一定先有一段告訴讀者該看什麼；表格後用一段解釋結論與限制。表格是證據，不是敘事的替代品。
- 小標題要直接說重點，例如「利率壓力仍在，但信用市場尚未失控」，避免只寫「利率」「信用」「流動性」。
- 每個重要判斷在段末以不打斷閱讀的方式標註來源頁名稱與資料日期；proxy 明寫「代理指標」。
- 日期用一般讀者看得懂的格式；小數通常最多一位。沒有必要時不要展示欄位名稱、模型代碼或原始資料結構。

【完成前自我檢查】
- 一位第一次看到報告的人，是否只看標題、三分鐘結論和各節標題，就能說出目前盤勢與主要理由？
- 每個主要結論是否都有證據、白話解釋、對股市的意義與可能推翻它的條件？
- 是否先完成市場故事，再用表格支持，而不是讓讀者自己從表格找答案？
- 是否把技術審計、來源缺漏與方法細節放在附錄，且沒有掩蓋重要限制？
- 是否避免把資料相關性寫成確定因果，並保持可分享、專業但不艱澀的語氣？

【附件內來源清單】
${sourceLines}
${failed.length?`\n收集失敗、不得假裝已讀的頁面：${failed.join('、')}`:''}

請先在內部確認已讀到 sources 陣列，再直接輸出完整報告；不要把確認過程或分析步驟寫給讀者。`;
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
      instructions:'Use all sources together. Produce a shareable Traditional Chinese market report for non-specialists: answer first, then tell a coherent causal story in plain language; explain technical terms and every important number; separate observations, proxies and inference; move detailed data-quality review to an appendix. Respect source dates, quality labels and disclosures. Directory metadata is not a market signal.',
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
