'use strict';
const PORTAL='http://127.0.0.1:8840';
const CANVAS='https://nu.instructure.com';
const GOOGLE='https://classroom.google.com';
let serial=Promise.resolve();
const exclusive=fn=>{serial=serial.then(fn,fn).catch(async error=>{await fail(error.message);});return serial;};
const read=()=>chrome.storage.local.get(null);
const save=value=>chrome.storage.local.set(value);
const sourceOrigin=source=>source==='canvas'?CANVAS:GOOGLE;
async function hash(value){return [...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(value)))].map(v=>v.toString(16).padStart(2,'0')).join('');}
async function api(path,body,override){
  const data=override||await read();
  const headers={'X-Study-Dock-Extension':chrome.runtime.id};
  if(data.token)headers.Authorization='Bearer '+data.token;
  if(body!==undefined)headers['Content-Type']='application/json';
  let response;
  try{response=await fetch(PORTAL+path,{method:body===undefined?'GET':'POST',headers,body:body===undefined?undefined:JSON.stringify(body),credentials:'omit',signal:AbortSignal.timeout(15000)});}
  catch{throw new Error('无法连接本机学习空间，请先启动“打开作业日历.cmd”。');}
  const value=await response.json();if(!response.ok)throw new Error(value.error||'连接失败。');return value;
}
async function closeOwned(run){if(run?.tab_id)await chrome.tabs.remove(run.tab_id).catch(()=>{});}
async function fail(message){
  const data=await read(),run=data.run;
  await closeOwned(run);
  await save({run:null,last_message:message,last_error:true});
  if(run?.account_hash&&data.token)await api('/api/extension/report',{source:run.source,origin:sourceOrigin(run.source),account_hash:run.account_hash,request_id:run.request_id,message}).catch(()=>{});
}
function merge(run,result){
  for(const key of ['courses','items','resources']){
    const map=new Map(run.snapshot[key].map(item=>[item.url,item]));
    for(const item of result[key]||[]){const old=map.get(item.url);if(!old||(item.detail_level||0)>=(old.detail_level||0))map.set(item.url,item);}
    run.snapshot[key]=[...map.values()];
    const limit={courses:200,items:2000,resources:5000}[key];
    if(run.snapshot[key].length>limit){run.snapshot[key]=run.snapshot[key].slice(0,limit);run.warnings.push('部分记录超过本次读取上限，已有内容保留。');}
  }
  run.warnings.push(...(result.warnings||[]));
  const known=new Set([...run.visited,...run.queue.map(item=>item.url)]);
  const complete=new Set(run.snapshot.items.filter(item=>item.detail_level===2).map(item=>item.url));
  for(const item of result.links||[]){if(!complete.has(item.url)&&!known.has(item.url)&&allowed(item.url,run.source)){known.add(item.url);run.queue.push(item);}}
  if(run.source==='classroom'){
    const order={assignment:0,'my-work':1,coursework:2,course:3};
    run.queue.sort((a,b)=>(order[a.kind]??4)-(order[b.kind]??4));
  }
}
function allowed(value,source){
  try{const u=new URL(value);return u.origin===sourceOrigin(source)&&!u.username&&
    (source==='canvas'?/^\/(?:profile\/settings|courses(?:[/?]|$))/.test(u.pathname):/^\/(?:u\/\d+\/)?(?:h(?:\/|$)|[cw]\/)/.test(u.pathname));}catch{return false;}
}
async function navigate(run,page){
  if(!allowed(page.url,run.source))throw new Error('采集地址不属于已绑定平台。');
  run.current=page;run.page_started=Date.now();run.capturing=false;
  await save({run,last_message:`正在读取 ${run.source==='canvas'?'Canvas':'Classroom'}：第 ${run.pages+1} 页`,last_error:false});
  await chrome.tabs.update(run.tab_id,{url:page.url});
}
async function upload(run,checkpoint=false){
  const warnings=[...new Set(run.warnings)];
  const payload={source:run.source,origin:sourceOrigin(run.source),account_hash:run.account_hash,
    request_id:checkpoint?null:run.request_id,snapshot:run.snapshot,warnings,diagnostics:{pages:run.pages,trace:run.trace||[]}};
  if(checkpoint)warnings.push('已先更新作业日历，课程资料还在采集中。');
  if(run.snapshot.courses.length&&!run.snapshot.items.length)warnings.push('已读取课程，但未识别出作业；采集不完整，请勿据此判断没有待交作业。');
  if(new TextEncoder().encode(JSON.stringify(payload)).length>3500000)throw new Error('本次内容过多，请在插件中减少采集页数后重新同步。');
  try{await api('/api/extension/import',payload);}
  catch(error){if(checkpoint)throw error;run.phase='upload';await closeOwned(run);run.tab_id=null;await save({run,last_message:error.message+' 采集结果已暂存，连接恢复后重试。',last_error:true});return;}
  if(checkpoint)return;
  const data=await read();const sources=data.sources||{};
  if(sources[run.source])sources[run.source].last_sync=Date.now();
  await closeOwned(run);
  await save({run:null,sources,last_message:`已更新 ${run.snapshot.courses.length} 门课程、${run.snapshot.items.length} 项作业、${run.snapshot.resources.length} 项资料。${warnings.length?'部分日期或页面待确认。':''}`,last_error:false});
}
async function next(run){
  if(run.pages>=run.max_pages&&run.queue.length){run.warnings.push(`本次达到 ${run.max_pages} 页上限，仍有页面未读取；已有数据保留。`);run.queue=[];}
  if(run.queue.length){const page=run.queue.shift();run.visited.push(page.url);await navigate(run,page);}
  else{run.phase='finish';await navigate(run,{url:run.identity_url,kind:'identity'});}
}
async function capture(tabId){
  const data=await read();const run=data.run;
  if(!run||run.tab_id!==tabId||run.capturing||run.phase==='upload')return;
  const tab=await chrome.tabs.get(tabId);
  if(tab.url==='about:blank'||tab.status!=='complete')return;
  if(run.phase==='walk' && (!tab.url || new URL(tab.url).origin!==sourceOrigin(run.source))){
    run.warnings.push('部分课程链接已跳转至其他站点或需要重新登录，请从原平台查看。');
    run.pages++;return next(run);
  }
  run.capturing=true;await save({run});
  let result;
  try{result=await chrome.tabs.sendMessage(tabId,{type:'study-dock-collect',identityOnly:['checkpoint','finish'].includes(run.phase),context:{...run.current,offset:run.offset}});}
  catch{throw new Error('页面未能读取，可能已退出登录。请用插件的“打开登录页”登录后重试。');}
  if(result?.login)throw new Error('平台需要重新登录；请打开官方登录页完成登录后再同步。');
  if(!result||result.error||result.source!==run.source||result.origin!==sourceOrigin(run.source))throw new Error('页面来源不匹配或未能加载，已有数据保留。');
  run.trace||=[];if(result.diagnostics)run.trace.push(result.diagnostics);
  run.trace=run.trace.slice(-160);
  if(run.phase==='start'||run.phase==='finish'||run.phase==='checkpoint'){
    if(!result.identity)throw new Error('无法确认当前平台账号。请先在官方页面打开账号设置（Canvas）或确认右上角学校账号（Classroom），再绑定。');
    const account=await hash(result.origin+'|'+result.identity.key);
    if(run.phase!=='start'){
      if(account!==run.account_hash)throw new Error('采集期间账号发生变化，已停止导入；请重新绑定目标账号。');
      if(run.phase==='checkpoint'){
        await upload(run,true);
        run.phase='walk';
        return next(run);
      }
      return upload(run);
    }
    if(run.intent==='bind'){
      await api('/api/extension/bind',{source:run.source,origin:sourceOrigin(run.source),account_hash:account,label:result.identity.label,replace:true});
      const sources=data.sources||{};sources[run.source]={account_hash:account,label:result.identity.label,root:run.root,identity_url:run.identity_url,offset:run.offset,last_sync:0,last_attempt:Date.now()};
      await save({sources});
    }else if(account!==run.account_hash)throw new Error('当前学校账号与绑定账号不同，已有数据保留；请主动重新绑定。');
    run.account_hash=account;run.phase='walk';
    merge(run,result);
    if(run.source==='classroom' && !run.snapshot.courses.length){
      for(const tab of await chrome.tabs.query({url:GOOGLE+'/*'})){
        if(tab.id===tabId || !/^\/(?:u\/\d+\/)?h(?:\/st)?\/?$/.test(new URL(tab.url).pathname))continue;
        const home=await chrome.tabs.sendMessage(tab.id,{type:'study-dock-collect',expectedIdentity:result.identity.key,
          context:{kind:'student-home',offset:run.offset}}).catch(()=>null);
        if(home?.identity?.key===result.identity.key && home.courses.length){merge(run,home);break;}
      }
      if(!run.snapshot.courses.length && !run.queue.some(p=>p.kind==='student-home'))
        run.queue.unshift({url:run.root.replace(/\/h\/?$/,'/h/st'),kind:'student-home'});
    }
    if(run.source==='classroom' && run.snapshot.courses.length){run.phase='checkpoint';return navigate(run,{url:run.identity_url,kind:'identity'});}
    if(run.source==='canvas')run.queue.unshift({url:CANVAS+'/courses',kind:'courses'});
    return next(run);
  }
  run.pages++;
  if(!result.recognized)run.warnings.push('有页面未识别或尚未加载完毕，已有内容保留：'+run.current.url);
  else merge(run,result);
  if((run.current.kind==='courses'&&run.snapshot.items.some(i=>i.detail_level===2)) ||
     (run.current.kind==='student-home' && run.snapshot.courses.length) ||
     (run.pages%6===0 && run.queue.length && (run.snapshot.resources.length || run.snapshot.items.length))){
    run.phase='checkpoint';return navigate(run,{url:run.identity_url,kind:'identity'});
  }
  return next(run);
}
async function start(source,intent='sync',options={}){
  const data=await read();if(!data.token)throw new Error('请先输入网页的一次性配对码。');
  if(data.run)throw new Error('已有采集任务运行中，请等待或停止后重试。');
  const sources=data.sources||{},binding=sources[source];
  if(intent!=='bind'&&!binding)throw new Error('请先绑定这个平台的学校账号。');
  let root=binding?.root || (source==='canvas'?CANVAS+'/courses':GOOGLE+'/u/0/h');
  if(intent==='bind'&&source==='classroom'){
    const [active]=await chrome.tabs.query({active:true,currentWindow:true});
    if(active?.url?.startsWith(GOOGLE+'/'))root=GOOGLE+(new URL(active.url).pathname.match(/^\/u\/\d+/)?.[0]||'')+'/h';
  }
  const identity_url=source==='canvas'?CANVAS+'/profile/settings':root.replace(/\/h\/?$/,'/h/st');
  const run={source,intent,root,identity_url,phase:'start',account_hash:binding?.account_hash||null,
    offset:options.offset??binding?.offset??540,max_pages:Math.min(300,Math.max(20,data.max_pages||150)),pages:0,
    queue:[],visited:[],warnings:[],trace:[],snapshot:{courses:[],items:[],resources:[]},request_id:options.request_id||null,started:Date.now()};
  if(!run.request_id)run.request_id=(await api('/api/extension/status')).requests?.[source]||null;
  await save({paused:false});
  if(binding){sources[source].last_attempt=Date.now();await save({sources});}
  // Create a neutral owned tab first; store its id before starting navigation.
  const tab=await chrome.tabs.create({url:'about:blank',active:source==='classroom' && options.foreground===true});run.tab_id=tab.id;
  await navigate(run,{url:identity_url,kind:'identity'});
}
async function tick(){
  const data=await read();if(!data.token)return;
  if(data.paused&&!data.run)return;
  if(data.run){
    if(data.run.phase==='upload')return upload(data.run);
    if(Date.now()-data.run.page_started>60000){
      if(data.run.phase!=='walk')throw new Error('账号确认页面加载超时，已有数据保留。请重新登录后再试。');
      data.run.warnings.push('部分课程页面加载超时，已跳过：'+data.run.current.url);
      data.run.pages++;
      return next(data.run);
    }
    return;
  }
  const status=await api('/api/extension/status');
  for(const source of ['canvas','classroom']){
    const binding=data.sources?.[source];if(!binding)continue;
    const request=status.requests?.[source];
    if(request || (data.auto!==false&&Date.now()-(binding.last_attempt||binding.last_sync||0)>15*60000))return start(source,'sync',{request_id:request});
  }
}
chrome.runtime.onInstalled.addListener(()=>{
  chrome.storage.local.setAccessLevel({accessLevel:'TRUSTED_CONTEXTS'});
  chrome.alarms.create('study-dock-tick',{periodInMinutes:1});
});
chrome.runtime.onStartup.addListener(()=>chrome.alarms.create('study-dock-tick',{periodInMinutes:1}));
chrome.alarms.onAlarm.addListener(alarm=>{if(alarm.name==='study-dock-tick')exclusive(tick);});
chrome.tabs.onUpdated.addListener((tabId,change)=>{if(change.status==='complete')exclusive(()=>capture(tabId));});
chrome.tabs.onRemoved.addListener(tabId=>exclusive(async()=>{const data=await read();if(data.run?.tab_id===tabId)await fail('采集标签页已关闭，已有缓存保留。');}));
chrome.runtime.onMessage.addListener((message,sender,respond)=>{
  if(message.type==='assignment-draft' && sender.tab && sender.frameId===0) {
    (async()=>{
      const target=new URL(sender.url);
      const source=target.origin===CANVAS?'canvas':target.origin===GOOGLE?'classroom':null;
      const correctPath=source==='canvas'?/^\/courses\/\d+\/assignments\/\d+\/?$/:/^\/(?:u\/\d+\/)?c\/[\w-]+\/(?:sa|a)\/[\w-]+\/details\/?$/;
      if(!source||!correctPath.test(target.pathname)||typeof message.identity!=='string')throw new Error('请从原平台的文字作业页面打开草稿。');
      const account=await hash(target.origin+'|'+message.identity);
      return api('/api/extension/text-draft',{source,origin:target.origin,account_hash:account,url:target.origin+target.pathname,consume:message.consume===true});
    })().then(respond,error=>respond({error:error.message}));
    return true;
  }
  if(sender.url!==chrome.runtime.getURL('popup.html'))return;
  const task=async()=>{
    if(message.type==='status')return read();
    if(message.type==='pair'){
      const old=await read();await closeOwned(old.run);
      const result=await api('/api/extension/pair',{code:String(message.code||'').trim()},{});
      await chrome.storage.local.clear();
      await save({token:result.token,user:result.user,sources:{},auto:true,last_message:'配对成功。请先登录学校平台，再绑定当前账号。',last_error:false,run:null});return {ok:true};
    }
    if(message.type==='start'){await start(message.source,message.intent,{offset:message.offset,foreground:true});return {ok:true};}
    if(message.type==='stop'){const data=await read();await closeOwned(data.run);await save({run:null,auto:false,paused:true,last_message:'采集已停止，自动更新已关闭。',last_error:false});return {ok:true};}
    if(message.type==='auto'){await save({auto:!!message.value,paused:!message.value});return {ok:true};}
    if(message.type==='limit'){await save({max_pages:Math.min(300,Math.max(20,Number(message.value)||150))});return {ok:true};}
    if(message.type==='poll'){await tick();return {ok:true};}
    if(message.type==='open'){
      const target=message.source==='canvas'?CANVAS+'/profile/settings':message.source==='classroom'?GOOGLE+'/u/0/h':PORTAL+'/#connections';
      await chrome.tabs.create({url:target,active:true});return {ok:true};
    }
    throw new Error('未知插件操作。');
  };
  // Popup failures are displayed without destroying a separate running job.
  const job=serial.then(task);serial=job.catch(()=>{});
  job.then(value=>respond(value),error=>respond({error:error.message}));return true;
});
