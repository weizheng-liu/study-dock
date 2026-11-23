// Install only into the project's dedicated Chrome profile. No existing Chrome
// profiles, school sessions, pairing credentials or school pages are accessed.
import {spawn} from 'node:child_process';
import {readFile,stat,mkdir,writeFile} from 'node:fs/promises';
import crypto from 'node:crypto';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const manifest=JSON.parse(await readFile(path.join(root,'extension','manifest.json'),'utf8'));
const id=[...crypto.createHash('sha256').update(Buffer.from(manifest.key,'base64')).digest('hex').slice(0,32)].map(c=>String.fromCharCode(97+parseInt(c,16))).join('');
const profile=path.join(root,'data','collector-chrome');
const started=Date.now();
const browser=spawn('C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',[
  `--user-data-dir=${profile}`,'--remote-debugging-port=0','--remote-debugging-address=127.0.0.1',
  '--enable-unsafe-extension-debugging','--no-first-run','--no-default-browser-check','about:blank'
],{windowsHide:false,stdio:'ignore'});
let socket,installed=false;
try{
  let lines;
  for(let attempt=0;attempt<100;attempt++){
    try{const file=path.join(profile,'DevToolsActivePort');if((await stat(file)).mtimeMs>=started-1000){lines=(await readFile(file,'utf8')).split('\n');break;}}catch{}
    await pause(150);
  }
  if(!lines)throw new Error('The dedicated Chrome profile could not be opened. Close only its windows and retry.');
  socket=new WebSocket(`ws://127.0.0.1:${lines[0]}${lines[1]}`);
  await new Promise((resolve,reject)=>{socket.addEventListener('open',resolve,{once:true});socket.addEventListener('error',()=>reject(new Error('Local Chrome connection failed.')),{once:true});});
  let sequence=0;const pending=new Map();
  socket.addEventListener('message',event=>{const value=JSON.parse(event.data);const request=pending.get(value.id);if(request){pending.delete(value.id);value.error?request.reject(new Error(value.error.message)):request.resolve(value.result);}});
  const send=(method,params={},sessionId)=>new Promise((resolve,reject)=>{
    const requestId=++sequence;const timeout=setTimeout(()=>{pending.delete(requestId);reject(new Error('Chrome operation timed out: '+method));},15000);
    pending.set(requestId,{resolve:value=>{clearTimeout(timeout);resolve(value);},reject:error=>{clearTimeout(timeout);reject(error);}});
    socket.send(JSON.stringify({id:requestId,method,params,...(sessionId?{sessionId}:{})}));
  });
  const evaluate=async(session,expression)=>{const value=await send('Runtime.evaluate',{expression,awaitPromise:true,userGesture:true,returnByValue:true},session);if(value.exceptionDetails)throw new Error(value.exceptionDetails.exception?.description||value.exceptionDetails.text);return value.result.value;};
  const open=async address=>{const target=await send('Target.createTarget',{url:address});return (await send('Target.attachToTarget',{targetId:target.targetId,flatten:true})).sessionId;};
  const manager=await open('chrome://extensions/');
  let configuration;
  for(let attempt=0;attempt<80;attempt++){try{configuration=await evaluate(manager,'chrome.developerPrivate.getProfileConfiguration()');if(configuration)break;}catch{}await pause(100);}
  if(!configuration)throw new Error('Chrome extension settings are unavailable.');
  if(configuration.canLoadUnpacked===false || (!configuration.inDeveloperMode&&configuration.isDeveloperModeControlledByPolicy))throw new Error('This browser is managed and does not allow local extension installation.');
  if(!configuration.inDeveloperMode)await evaluate(manager,'chrome.developerPrivate.updateProfileConfiguration({inDeveloperMode:true})');
  const loaded=await send('Extensions.loadUnpacked',{path:path.join(root,'extension')});
  if(loaded.id!==id)throw new Error('Unexpected extension identifier.');
  let info=await evaluate(manager,`chrome.developerPrivate.getExtensionsInfo({includeDisabled:true,includeTerminated:true}).then(list=>{const e=list.find(v=>v.id===${JSON.stringify(id)});return e?{state:e.state,disableReasons:e.disableReasons}:null;})`);
  if(info?.disableReasons?.blockedByPolicy)throw new Error('Extension installation was blocked by browser policy.');
  if(info?.state!=='ENABLED')await evaluate(manager,`chrome.management.setEnabled(${JSON.stringify(id)},true)`);
  const popup=await open(`chrome-extension://${id}/popup.html`);
  let ready=false;
  for(let attempt=0;attempt<80;attempt++){try{if(await evaluate(popup,`globalThis.chrome?.runtime?.id===${JSON.stringify(id)}`)){ready=true;break;}}catch{}await pause(100);}
  if(!ready)throw new Error('Installed extension panel did not become available.');
  const status=await evaluate(popup,"chrome.runtime.sendMessage({type:'status'}).then(s=>({paired:!!s.token,userBound:!!s.user?.id}))");
  await mkdir(path.join(root,'test-output'),{recursive:true});
  await writeFile(path.join(root,'test-output','chrome-deployment.json'),JSON.stringify({browser:'Google Chrome',extensionId:id,extensionVersion:manifest.version,installed:true,panelVerified:true,paired:status.paired,profile:'data/collector-chrome'},null,2));
  installed=true;
  console.log('CHROME_DEPLOYMENT_SUCCESS: extension installed, enabled and panel verified. Paired: '+status.paired);
  await send('Browser.close').catch(()=>{});
}finally{
  if(socket?.readyState===WebSocket.OPEN){socket.send(JSON.stringify({id:999999,method:'Browser.close'}));await pause(300);socket.close();}
  for(let attempt=0;attempt<50&&browser.exitCode===null;attempt++)await pause(100);
  if(installed)spawn('python',[path.join(root,'launch_collector.py'),'--browser','chrome'],{cwd:root,windowsHide:true,stdio:'ignore',detached:true}).unref();
}
