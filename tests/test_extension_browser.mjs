// Load the real MV3 extension in a disposable Edge profile. School HTML is intercepted
// before network access and served as explicit fixtures; this is not a live-school test.
import {spawn} from 'node:child_process';
import {mkdtemp,readFile,writeFile,cp,rm,mkdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
const root=process.cwd(),temp=await mkdtemp(path.join(tmpdir(),'study-dock-extension-'));
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const assert=(value,label)=>{if(!value)throw new Error(label);};
let browser,server,socket;
const faults=[];
const html=(body,identity='')=>'<!doctype html><meta charset="utf-8">'+identity+'<main>'+body+'</main>';
const googleIdentity='<a href="https://accounts.google.com/" aria-label="Google Account: Test Student (student@example.edu)">账号</a>';
const fixtures={
  '/api/v1/courses/17/modules':JSON.stringify([{id:41,name:'第7回',items:[{id:22,type:'File',content_id:22,
    title:'参考 PDF',html_url:'https://nu.instructure.com/courses/17/modules/items/584199'}]}]),
  '/api/v1/courses/17/assignments':JSON.stringify([{id:21,course_id:17,name:'计算题',due_at:'2026-11-20T08:00:00Z',
    description:'<p>写出全部计算步骤。</p>',submission_types:['online_text_entry'],submission:{workflow_state:'unsubmitted'}}]),
  '/profile/settings':html('<h1>个人设置</h1><form id="edit_user_77" action="/users/77"><input id="user_name" value="Fixture Student"><input type="password" value="must-not-read"></form>'),
  '/courses':html('<h1>我的课程</h1><a href="/courses/17">电子回路</a>'),
  '/courses/17':html('<h1>电子回路</h1><section class="context_module"><h2>第7回</h2><ul class="context_module_items"><li class="context_module_item assignment student-view Assignment_21"><span>課題</span><a href="/courses/17/modules/items/584198">计算题</a><span class="due-date">11月20日</span></li><li class="context_module_item attachment Attachment_22"><a href="/courses/17/modules/items/584199">参考 PDF</a></li><li class="context_module_item wiki_page"><a href="/courses/17/modules/items/58800">讲义</a></li></ul></section>'),
  '/courses/17/assignments':html('<h1>作业</h1><ul><li class="assignment"><a href="/courses/17/assignments/21">计算题</a><span class="due-date">Due Nov 20, 2026 at 11:59pm JST</span></li></ul>'),
  '/courses/17/assignments/21':html('<h1>计算题</h1><ul class="student-assignment-overview"><li>期限 <span class="display_date" data-html-tooltip-title="2026年11月20日 17:00">11月20日（17:00までに）</span></li><li>使用可能 11月12日 12:30 ～ 11月20日 17:00</li></ul><div class="description user_content">写出全部计算步骤。<a href="/courses/17/files/22">题目 PDF</a></div><div class="submission_status">未提交</div>'),
  '/courses/17/pages/notes':html('<h1>讲义</h1><div class="user_content">学习资料正文</div>'),
  '/u/0/h':html('<h1>课程</h1><div id="delayed"></div><script>setTimeout(()=>document.querySelector("#delayed").innerHTML=\'<a href="/u/0/c/COURSE21">微观经济学</a>\',1200)</script>',googleIdentity),
  '/u/0/c/COURSE21':html('<h1>微观经济学</h1><a href="/u/0/w/COURSE21/t/all">Classwork</a>',googleIdentity),
  '/u/0/w/COURSE21/t/all':html('<h1>Classwork</h1><article><a href="/u/0/c/COURSE21/a/WORK201/details">需求练习</a></article><a href="/u/0/c/COURSE21/m/MAT202/details">第二章讲义</a>',googleIdentity),
  '/u/0/c/COURSE21/a/WORK201/details':html('<h1>需求练习</h1><div class="due-date" aria-label="Due Nov 21, 2026 at 11:59pm JST">截止日期</div><div data-field="description">解释需求曲线。<a href="https://docs.google.com/document/d/example">参考文档</a></div><div data-submission-state>Turned in</div>',googleIdentity),
  '/u/0/c/COURSE21/m/MAT202/details':html('<h1>第二章讲义</h1><div data-field="description">阅读第二章。</div>',googleIdentity)
};
fixtures['/u/0/h/st']=fixtures['/u/0/h'];
try{
  const serverCode="from pathlib import Path; from app import Portal,make_server; import sys,json; p=Portal(Path(sys.argv[1]),{}); s=make_server(p,port=0); p.base_url='http://127.0.0.1:'+str(s.server_address[1]); print(json.dumps({'url':p.base_url}),flush=True); s.serve_forever()";
  server=spawn('python',['-u','-c',serverCode,path.join(temp,'data')],{cwd:root,windowsHide:true,stdio:['ignore','pipe','pipe']});
  const base=await new Promise((resolve,reject)=>{let data='';server.stdout.on('data',chunk=>{data+=chunk;if(data.includes('\n'))resolve(JSON.parse(data.split('\n')[0]).url);});server.on('error',reject);server.stderr.on('data',chunk=>faults.push(String(chunk)));});
  const extension=path.join(temp,'extension');await cp(path.join(root,'extension'),extension,{recursive:true});
  for(const file of ['manifest.json','background.js']){const value=await readFile(path.join(extension,file),'utf8');await writeFile(path.join(extension,file),value.replaceAll('http://127.0.0.1:8840',base));}
  const edge='C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
  browser=spawn(edge,['--headless=new','--remote-debugging-port=0',`--user-data-dir=${path.join(temp,'profile')}`,`--disable-extensions-except=${extension}`,`--load-extension=${extension}`,'--enable-unsafe-extension-debugging','--no-first-run','--no-default-browser-check','--disable-background-networking','--host-resolver-rules=MAP nu.instructure.com ~NOTFOUND, MAP classroom.google.com ~NOTFOUND','about:blank'],{windowsHide:true,stdio:'ignore'});
  let lines;
  for(let i=0;i<100;i++){try{lines=(await readFile(path.join(temp,'profile','DevToolsActivePort'),'utf8')).split('\n');break;}catch{await sleep(150);}}
  assert(lines,'Edge did not start');
  socket=new WebSocket(`ws://127.0.0.1:${lines[0]}${lines[1]}`);
  await new Promise((resolve,reject)=>{socket.addEventListener('open',resolve,{once:true});socket.addEventListener('error',reject,{once:true});});
  let sequence=0;const pending=new Map(),pages=new Map();
  const send=(method,params={},sessionId)=>new Promise((resolve,reject)=>{const id=++sequence;const timeout=setTimeout(()=>{pending.delete(id);reject(new Error('CDP timeout: '+method));},15000);pending.set(id,{resolve:v=>{clearTimeout(timeout);resolve(v);},reject:e=>{clearTimeout(timeout);reject(e);}});socket.send(JSON.stringify({id,method,params,...(sessionId?{sessionId}:{})}));});
  socket.addEventListener('message',async event=>{
    const m=JSON.parse(event.data);
    if(m.id){const p=pending.get(m.id);if(p){pending.delete(m.id);m.error?p.reject(new Error(JSON.stringify(m.error))):p.resolve(m.result);}return;}
    try{
      if(m.method==='Target.attachedToTarget'){
        const session=m.params.sessionId;pages.set(m.params.targetInfo.targetId,session);
        if(m.params.targetInfo.type==='page'){
          await send('Fetch.enable',{patterns:[{urlPattern:'https://nu.instructure.com/*',requestStage:'Request'},{urlPattern:'https://classroom.google.com/*',requestStage:'Request'}]},session);
        }
        await send('Runtime.runIfWaitingForDebugger',{},session);
      }
      if(m.method==='Fetch.requestPaused'){
        const u=new URL(m.params.request.url);let body=u.pathname==='/favicon.ico'?'':fixtures[u.pathname];
        if(u.pathname==='/courses/17/modules/items/58800'){
          await send('Fetch.fulfillRequest',{requestId:m.params.requestId,responseCode:302,responseHeaders:[{name:'Location',value:'https://nu.instructure.com/courses/17/pages/notes'}],body:''},m.sessionId);return;
        }
        if(body===undefined)faults.push('Unexpected fixture path: '+u.pathname);
        await send('Fetch.fulfillRequest',{requestId:m.params.requestId,responseCode:body!==undefined?200:404,responseHeaders:[{name:'Content-Type',value:'text/html; charset=utf-8'}],body:Buffer.from(body??html('<h1>Not found</h1>')).toString('base64')},m.sessionId);
      }
      if(m.method==='Page.javascriptDialogOpening')await send('Page.handleJavaScriptDialog',{accept:true},m.sessionId);
    }catch(error){faults.push(error.message);}
  });
  await send('Target.setAutoAttach',{autoAttach:true,waitForDebuggerOnStart:true,flatten:true,filter:[{type:'page',exclude:false}]});
  let extensionId,loadMethod='command-line';
  for(let i=0;i<30;i++){const targets=(await send('Target.getTargets')).targetInfos;for(const target of targets.filter(t=>t.url.startsWith('chrome-extension://')&&t.url.endsWith('/background.js'))){const {sessionId}=await send('Target.attachToTarget',{targetId:target.targetId,flatten:true});const value=await send('Runtime.evaluate',{expression:'chrome.runtime.getManifest().name',returnByValue:true},sessionId);if(value.result?.value==='Study Dock · 课程采集助手'){extensionId=target.url.split('/')[2];break;}}if(extensionId)break;await sleep(100);}
  if(!extensionId){const loaded=await send('Extensions.loadUnpacked',{path:extension});extensionId=loaded.id;loadMethod='CDP';}
  assert(extensionId,'Unpacked extension did not load');
  const newPage=async address=>{const {targetId}=await send('Target.createTarget',{url:address});for(let i=0;i<50&&!pages.has(targetId);i++)await sleep(100);const session=pages.get(targetId);assert(session,'Missing page session');for(let i=0;i<80;i++){try{const ready=await send('Runtime.evaluate',{expression:'document.readyState',returnByValue:true},session);if(ready.result?.value==='complete')return session;}catch(error){if(!error.message.includes('execution context'))throw error;}await sleep(100);}throw new Error('Page did not become ready: '+address);};
  const evaluate=async(session,expression)=>{const result=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true},session);if(result.exceptionDetails)throw new Error(result.exceptionDetails.exception?.description||result.exceptionDetails.text);return result.result.value;};
  const popup=await newPage(`chrome-extension://${extensionId}/popup.html`);
  for(let i=0;i<50;i++){if(await evaluate(popup,'!!globalThis.chrome?.runtime?.sendMessage'))break;await sleep(100);}
  assert(await evaluate(popup,'!!globalThis.chrome?.runtime?.sendMessage'),'Popup did not load: '+await evaluate(popup,'location.href+" | "+document.body.innerText'));
  // Actual browser DOM parser checks, including incomplete and malformed deadlines.
  const parserPage=await newPage('about:blank');const collector=await readFile(path.join(root,'extension','collector.js'),'utf8');await evaluate(parserPage,collector);
  const parsed=await evaluate(parserPage,`StudyDockDOM.collect(new DOMParser().parseFromString(${JSON.stringify(fixtures['/courses/17/assignments/21'])},'text/html'),'https://nu.instructure.com/courses/17/assignments/21',{course_name:'电子回路',offset:540})`);
  assert(parsed.items[0].due_at==='2026-11-20T08:00:00.000Z','Japanese Canvas due field selection');
  assert(parsed.items[0].attachments[0].title==='题目 PDF','Attachment title');
  assert(await evaluate(parserPage,"StudyDockDOM.parseDue('Nov 20 at 11:59pm').date_uncertain"),'Missing year was guessed');
  assert(await evaluate(parserPage,"StudyDockDOM.parseDue('明天 17:00',540,Date.parse('2026-11-17T15:01:00Z')).due_at==='2026-11-19T08:00:00.000Z'"),'Relative deadline shifted in JST');
  assert(await evaluate(parserPage,"StudyDockDOM.parseDue('2026/02/31 23:59').date_uncertain"),'Invalid date accepted');
  let cookie='';
  const request=async(url,body,csrf)=>{const headers={Cookie:cookie};if(body!==undefined){headers['Content-Type']='application/json';headers.Origin=base;headers['X-CSRF-Token']=csrf;}
    const response=await fetch(base+url,{method:body===undefined?'GET':'POST',headers,body:body===undefined?undefined:JSON.stringify(body)});if(response.headers.get('set-cookie'))cookie=response.headers.get('set-cookie').split(';')[0];const value=await response.json();if(!response.ok)throw new Error(value.error);return value;};
  let state=await request('/api/state');await request('/api/register',{username:'extension-test',password:'disposable-test-password'},state.csrf);state=await request('/api/state');
  const {code}=await request('/api/browser/pair-code',{},state.csrf);
  const pair=await evaluate(popup,`chrome.runtime.sendMessage({type:'pair',code:${JSON.stringify(code)}})`);assert(!pair.error,'Pairing failed: '+pair.error);
  for(const source of ['canvas','classroom']){
    const result=await evaluate(popup,`chrome.runtime.sendMessage({type:'start',source:${JSON.stringify(source)},intent:'bind',offset:540})`);assert(!result.error,'Start failed: '+result.error);
    let complete=false;
    for(let i=0;i<180;i++){await sleep(150);const s=await evaluate(popup,"chrome.storage.local.get(['run','last_message','last_error'])");if(!s.run){assert(!s.last_error,s.last_message);complete=true;break;}}
    assert(complete,'Extension run did not finish for '+source);
  }
  state=await request('/api/state');
  assert(state.items.length===2,'Expected both platform assignments; got '+state.items.length);
  assert(state.resources.length>=3,'Materials were not imported');
  assert(state.items.some(i=>i.description.includes('计算步骤')),'Assignment requirements missing');
  assert(state.items.find(i=>i.source==='classroom').status==='submitted','Classroom submission state');
  assert(Object.keys(state.browser.bindings).length===2,'Both account bindings missing');
  const textTask=state.items.find(i=>i.source==='canvas');
  assert(textTask.text_entry && textTask.due_at==='2026-11-20T08:00:00+00:00','Personal Canvas deadline or type missing');
  await request('/api/assistant/save-draft',{id:textTask.id,text:'A fixture answer'},state.csrf);
  fixtures['/courses/17/assignments/21']+=
    '<form id="submit_online_text_entry_form"><textarea name="submission[body]"></textarea><button type="submit">Submit</button></form>'+
    '<script>document.querySelector("form").onsubmit=e=>{e.preventDefault();document.body.dataset.submitted=document.querySelector("textarea").value}</script>';
  const answerPage=await newPage('about:blank');
  await send('Page.enable',{},answerPage);
  await send('Fetch.enable',{patterns:[{urlPattern:'https://nu.instructure.com/*'}]},answerPage);
  await send('Page.navigate',{url:textTask.url},answerPage);
  await send('Page.bringToFront',{},answerPage);
  const clickSchoolButton=async(name)=>{
    for(let i=0;i<60;i++){
      const tree=await send('Accessibility.getFullAXTree',{},answerPage);
      const node=tree.nodes.find(n=>n.role?.value==='button'&&n.name?.value===name);
      if(node){
        const box=(await send('DOM.getBoxModel',{backendNodeId:node.backendDOMNodeId},answerPage)).model.content;
        for(const type of ['mousePressed','mouseReleased'])await send('Input.dispatchMouseEvent',{type,x:(box[0]+box[4])/2,y:(box[1]+box[5])/2,button:'left',clickCount:1},answerPage);
        return;
      }
      await sleep(100);
    }
    throw new Error('Missing fixture button '+name+' '+await evaluate(answerPage,'JSON.stringify([location.pathname,document.hidden,!!document.querySelector("#submit_online_text_entry_form"),document.body.innerText.slice(-240),document.querySelector("textarea")?.getBoundingClientRect().width])'));
  };
  await clickSchoolButton('填入学习空间草稿');
  for(let i=0;i<50 && await evaluate(answerPage,'document.querySelector("textarea").value')!=='A fixture answer';i++)await sleep(100);
  assert(await evaluate(answerPage,'document.querySelector("textarea").value==="A fixture answer" && !document.body.dataset.submitted'),'Fill must not send');
  await evaluate(answerPage,'document.querySelector("textarea").value="Reviewed fixture"');
  await clickSchoolButton('确认并提交这段文字');
  for(let i=0;i<50 && !await evaluate(answerPage,'document.body.dataset.submitted');i++)await sleep(100);
  assert(await evaluate(answerPage,'document.body.dataset.submitted==="Reviewed fixture"'),'Reviewed fixture text was not submitted');
  assert(faults.length===0,faults.join('\n'));
  await mkdir(path.join(root,'test-output'),{recursive:true});
  const popupImage=await send('Page.captureScreenshot',{format:'png'},popup);await writeFile(path.join(root,'test-output','extension-popup.png'),Buffer.from(popupImage.data,'base64'));
  fixtures['/profile/settings']=fixtures['/profile/settings'].replaceAll('77','78');
  const switched=await evaluate(popup,"chrome.runtime.sendMessage({type:'start',source:'canvas',intent:'sync'})");assert(!switched.error,'Failed to start account-switch test');
  let blocked=false;for(let i=0;i<80;i++){await sleep(100);const s=await evaluate(popup,"chrome.storage.local.get(['run','last_error','last_message'])");if(!s.run){assert(s.last_error&&s.last_message.includes('账号'),'Account switch was not blocked');blocked=true;break;}}
  assert(blocked,'Account switch check did not finish');
  const retained=await request('/api/state');assert(retained.items.length===2,'Account switch removed valid cached work');
  await writeFile(path.join(root,'test-output','extension-verification.json'),JSON.stringify({test:'real MV3 extension, intercepted school DOM fixtures',loadedVia:loadMethod,extensionId,assignments:state.items.length,resources:state.resources.length,bindings:Object.keys(state.browser.bindings),accountSwitchBlocked:true,liveSchoolVerified:false},null,2));
  console.log('PASS: real unpacked extension, content scripts, two account bindings, page traversal, local pairing/import, requirements, deadlines, attachments and materials. School pages were fixtures, not live accounts.');
}finally{
  if(socket?.readyState===WebSocket.OPEN){socket.send(JSON.stringify({id:999999,method:'Browser.close'}));await sleep(300);socket.close();}
  browser?.kill();server?.kill();await sleep(500);await rm(temp,{recursive:true,force:true}).catch(()=>{});
}
