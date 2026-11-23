'use strict';
const $=selector=>document.querySelector(selector);
async function message(value){const result=await chrome.runtime.sendMessage(value);if(result?.error)throw new Error(result.error);return result;}
function status(text,error=false){$('#status').textContent=text;$('#status').classList.toggle('error',error);}
async function update(){const data=await message({type:'status'});$('#pairing').hidden=!!data.token;$('#connected').hidden=!data.token;$('#user').textContent=data.user?'已配对：'+data.user.name:'';for(const source of ['canvas','classroom'])$('#'+source+'Label').textContent=data.sources?.[source]?.label||'尚未绑定';$('#auto').checked=data.auto!==false;if(document.activeElement!==$('#maxPages'))$('#maxPages').value=data.max_pages||150;if(data.last_message)status(data.last_message,data.last_error);}
async function action(fn){try{await fn();await update();}catch(error){status(error.message,true);}}
$('#pair').addEventListener('click',()=>action(async()=>{await message({type:'pair',code:$('#code').value});$('#code').value='';}));
for(const button of document.querySelectorAll('[data-open]'))button.addEventListener('click',()=>action(()=>message({type:'open',source:button.dataset.open})));
for(const button of document.querySelectorAll('[data-bind]'))button.addEventListener('click',()=>action(async()=>{
  const data=await message({type:'status'}),source=button.dataset.bind;
  if(data.sources?.[source]&&!confirm('重新绑定另一个学校账号会清除本学习空间中该平台的旧缓存。确认使用当前官方页面的账号？'))return;
  await message({type:'start',source,intent:'bind',offset:Number($('#offset').value)});status('正在确认官方页面的账号并采集，标签页将在后台打开。');
}));
for(const button of document.querySelectorAll('[data-sync]'))button.addEventListener('click',()=>action(()=>message({type:'start',source:button.dataset.sync,intent:'sync'})));
$('#auto').addEventListener('change',()=>action(()=>message({type:'auto',value:$('#auto').checked})));
$('#maxPages').addEventListener('change',()=>action(()=>message({type:'limit',value:Number($('#maxPages').value)})));
$('#stop').addEventListener('click',()=>action(()=>message({type:'stop'})));
$('#rePair').addEventListener('click',()=>{$('#pairing').hidden=false;$('#code').focus();});
update();setInterval(()=>{if(document.activeElement!==$('#code'))update().catch(()=>{});},1500);
