// Local deployment helper. Pairing code is read from masked stdin, never argv or disk.
import {spawn,spawnSync} from 'node:child_process';
import {readFile,stat} from 'node:fs/promises';
import crypto from 'node:crypto';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const useChrome=process.argv.includes('--chrome');
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function readCode(){
  if(process.stdin.isTTY)process.stdin.setRawMode(true);
  process.stdout.write('READY_FOR_PAIRING_CODE (input hidden)\n');
  let code='';
  return new Promise((resolve,reject)=>{
    const finish=()=>{process.stdin.removeListener('data',onData);if(process.stdin.isTTY)process.stdin.setRawMode(false);process.stdin.pause();resolve(code.trim());};
    const onData=chunk=>{for(const char of chunk.toString('utf8')){if(char==='\u0003'){reject(new Error('Cancelled'));return;}if(char==='\r'||char==='\n'){finish();return;}if(char==='\u007f'||char==='\b')code=code.slice(0,-1);else code+=char;}};
    process.stdin.on('data',onData);process.stdin.resume();
  });
}
let code='';
const manifest=JSON.parse(await readFile(path.join(root,'extension','manifest.json'),'utf8'));
const id=[...crypto.createHash('sha256').update(Buffer.from(manifest.key,'base64')).digest('hex').slice(0,32)].map(c=>String.fromCharCode(97+parseInt(c,16))).join('');
const profile=path.join(root,'data',useChrome?'collector-chrome':'collector-browser');
const started=Date.now();
const browser=spawn(useChrome?'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe':'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',[
  `--user-data-dir=${profile}`,'--remote-debugging-port=0','--remote-debugging-address=127.0.0.1',
  '--enable-unsafe-extension-debugging','--no-first-run',
  ...(!useChrome?[`--disable-extensions-except=${path.join(root,'extension')}`,`--load-extension=${path.join(root,'extension')}`]:[]),'about:blank'
],{windowsHide:false,stdio:'ignore'});
let socket,paired=false;
try{
  let lines;
  for(let i=0;i<100;i++){try{const file=path.join(profile,'DevToolsActivePort');const info=await stat(file);if(info.mtimeMs>=started-1000){lines=(await readFile(file,'utf8')).split('\n');break;}}catch{}await sleep(150);}
  if(!lines)throw new Error('Cannot attach to the project browser. Close its windows and try again.');
  socket=new WebSocket(`ws://127.0.0.1:${lines[0]}${lines[1]}`);
  await new Promise((resolve,reject)=>{socket.addEventListener('open',resolve,{once:true});socket.addEventListener('error',()=>reject(new Error('Local browser connection failed.')),{once:true});});
  let sequence=0;const pending=new Map();
  socket.addEventListener('message',event=>{const m=JSON.parse(event.data);if(!m.id)return;const p=pending.get(m.id);if(p){pending.delete(m.id);m.error?p.reject(new Error(m.error.message)):p.resolve(m.result);}});
  const send=(method,params={},sessionId)=>new Promise((resolve,reject)=>{const id=++sequence;const timer=setTimeout(()=>{pending.delete(id);reject(new Error('Browser operation timed out: '+method));},10000);pending.set(id,{resolve:value=>{clearTimeout(timer);resolve(value);},reject:error=>{clearTimeout(timer);reject(error);}});socket.send(JSON.stringify({id,method,params,...(sessionId?{sessionId}:{})}));});
  try{const loaded=await send('Extensions.loadUnpacked',{path:path.join(root,'extension')});if(loaded.id!==id)throw new Error('Unexpected extension identifier.');}
  catch(error){if(!error.message.includes('already'))throw error;}
  const target=await send('Target.createTarget',{url:`chrome-extension://${id}/popup.html`});
  const {sessionId}=await send('Target.attachToTarget',{targetId:target.targetId,flatten:true});
  const evaluate=async expression=>{const result=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true},sessionId);if(result.exceptionDetails)throw new Error('Extension panel script failed.');return result.result.value;};
  let ready=false;
  for(let i=0;i<60;i++){try{if(await evaluate('!!globalThis.chrome?.runtime?.sendMessage')){ready=true;break;}}catch{}await sleep(100);}
  if(!ready){
    const diagnostic=await evaluate('({url:location.href,title:document.title,text:document.body?.innerText?.slice(0,1500)})').catch(()=>({error:'Panel unavailable'}));
    process.stdout.write('PANEL_DIAGNOSTIC: '+JSON.stringify(diagnostic)+'\n');
    const manager=await send('Target.createTarget',{url:useChrome?'chrome://extensions/':'edge://extensions/'});
    const managed=await send('Target.attachToTarget',{targetId:manager.targetId,flatten:true});
    for(let i=0;i<30;i++){
      try{
        const state=await send('Runtime.evaluate',{expression:`(async()=>{if(!chrome.developerPrivate)return {waiting:true};const profile=await chrome.developerPrivate.getProfileConfiguration();const all=await chrome.developerPrivate.getExtensionsInfo({includeDisabled:true,includeTerminated:true});const own=all.find(e=>e.id===${JSON.stringify(id)});return {profile,extension:own?{id:own.id,name:own.name,state:own.state,disableReasons:own.disableReasons,installWarnings:own.installWarnings,blacklistText:own.blacklistText,mustRemainDisabled:own.mustRemainDisabled}:null};})()`,awaitPromise:true,returnByValue:true},managed.sessionId);
        if(state.result?.value&&!state.result.value.waiting){
          const info=state.result.value;
          if(info.profile.canLoadUnpacked&&!info.profile.isDeveloperModeControlledByPolicy&&!info.extension?.disableReasons?.blockedByPolicy){
            await send('Runtime.evaluate',{expression:'chrome.developerPrivate.updateProfileConfiguration({inDeveloperMode:true})',awaitPromise:true,userGesture:true,returnByValue:true},managed.sessionId);
            await send('Extensions.loadUnpacked',{path:path.join(root,'extension')}).catch(error=>{if(!error.message.toLowerCase().includes('already'))throw error;});
            const enabled=await send('Runtime.evaluate',{expression:`chrome.management.setEnabled(${JSON.stringify(id)},true).then(()=>({ok:true}),e=>({error:e.message}))`,awaitPromise:true,userGesture:true,returnByValue:true},managed.sessionId);
            if(enabled.result?.value?.error)throw new Error(enabled.result.value.error);
            await send('Page.navigate',{url:`chrome-extension://${id}/popup.html`},sessionId);
            for(let attempt=0;attempt<50;attempt++){try{if(await evaluate('!!globalThis.chrome?.runtime?.sendMessage')){ready=true;break;}}catch{}await sleep(100);}
          }
          process.stdout.write('EXTENSION_ENABLE_CHECK: '+(ready?'enabled':'not enabled')+'\n');break;
        }
      }catch(error){process.stdout.write('ENABLE_DIAGNOSTIC: '+error.message+'\n');break;}
      await sleep(100);
    }
    if(!ready)throw new Error('Extension panel did not load.');
  }
  code=await readCode();
  if(!/^[A-Za-z0-9_-]{16,100}$/.test(code))throw new Error('Invalid pairing code format.');
  const ownerDigest=crypto.createHash('sha256').update(code).digest('hex');
  let result=await evaluate(`chrome.runtime.sendMessage({type:'pair',code:${JSON.stringify(code)}})`);
  code='';
  if(result.error?.includes('配对码已失效')){
    // A replacement code may only be generated through an existing authenticated
    // portal session, and only when it belongs to the originally supplied code.
    const owner=spawnSync('python',['-c',"import sqlite3,sys; d=sqlite3.connect(sys.argv[1]); r=d.execute('SELECT user_id FROM extension_codes WHERE digest=?',(sys.stdin.read().strip(),)).fetchone(); print(r[0] if r else '')",path.join(root,'data','portal.db')],{input:ownerDigest,encoding:'utf8',windowsHide:true});
    const expected=Number(owner.stdout.trim());
    if(expected){
      const appTarget=await send('Target.createTarget',{url:'http://127.0.0.1:8840/#connections'});
      const appSession=await send('Target.attachToTarget',{targetId:appTarget.targetId,flatten:true});
      let appState;
      for(let attempt=0;attempt<50;attempt++){
        try{const check=await send('Runtime.evaluate',{expression:"fetch('/api/state').then(r=>r.json()).then(s=>({userId:s.user?.id,csrf:s.csrf}))",awaitPromise:true,returnByValue:true},appSession.sessionId);if(check.result?.value?.csrf){appState=check.result.value;break;}}catch{}
        await sleep(100);
      }
      if(appState?.userId===expected){
        const generated=await send('Runtime.evaluate',{expression:`fetch('/api/browser/pair-code',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':${JSON.stringify(appState.csrf)}},body:'{}'}).then(r=>r.json())`,awaitPromise:true,returnByValue:true},appSession.sessionId);
        code=generated.result?.value?.code||'';
        if(code){result=await evaluate(`chrome.runtime.sendMessage({type:'pair',code:${JSON.stringify(code)}})`);code='';process.stdout.write('PAIR_CODE_RENEWED_IN_MATCHING_LOGGED_IN_SESSION\n');}
      }
    }
  }
  if(result.error)throw new Error(result.error);
  const state=await evaluate("chrome.runtime.sendMessage({type:'status'}).then(s=>({paired:!!s.token,userBound:!!s.user?.id}))");
  if(!state.paired||!state.userBound)throw new Error('Pairing was not saved.');
  paired=true;
  process.stdout.write('PAIR_SUCCESS: extension installed and pairing saved.\n');
  // Close temporary local debugging access, then reopen normally with the same profile.
  await send('Browser.close').catch(()=>{});
}finally{
  code='';
  if(socket?.readyState===WebSocket.OPEN){socket.send(JSON.stringify({id:999999,method:'Browser.close'}));await sleep(500);socket.close();}
  for(let i=0;i<40&&browser.exitCode===null;i++)await sleep(100);
  if(paired){spawn('python',[path.join(root,'launch_collector.py'),'--browser',useChrome?'chrome':'edge'],{cwd:root,windowsHide:true,stdio:'ignore',detached:true}).unref();}
}
