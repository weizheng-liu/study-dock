/* This runs only on the visible school form. The collection loop never activates it. */
(() => {
  'use strict';
  const canvas = location.hostname === 'nu.instructure.com';
  const supported = () => canvas ? /^\/courses\/\d+\/assignments\/\d+\/?$/.test(location.pathname)
    : /^\/(?:u\/\d+\/)?c\/[\w-]+\/(?:sa|a)\/[\w-]+\/details\/?$/.test(location.pathname);
  const visible = node => node && !!node.getClientRects().length && !node.disabled &&
    node.getAttribute('aria-disabled') !== 'true';
  function controls() {
    if (!supported() || document.hidden) return null;
    if (canvas) {
      const scope = [...document.querySelectorAll('#submit_online_text_entry_form,[data-testid="text-entry"]')].find(visible);
      if (!scope) return null;
      const frame = [...scope.querySelectorAll('iframe.tox-edit-area__iframe,iframe[id$="_ifr"]')].find(visible);
      const editor = frame?.contentDocument?.body?.isContentEditable ? frame.contentDocument.body :
        [...scope.querySelectorAll('textarea[name="submission[body]"],[contenteditable="true"]')].find(visible);
      if (!editor) return null;
      const button = scope.querySelector('button[type="submit"],input[type="submit"]') ||
        document.querySelector('button[data-testid="submit-button"]');
      return {scope, editor, button};
    }
    const editors = [...document.querySelectorAll('textarea[aria-label],[contenteditable="true"][aria-label]')].filter(n =>
      visible(n) && /^(?:your answer|your response|自分の回答|あなたの回答|你的回答|您的回答)$/i.test(n.getAttribute('aria-label').trim()));
    if (editors.length !== 1) return null;
    const editor = editors[0], scope = editor.closest('form,section,[role="region"]') || editor.parentElement;
    const buttons = [...scope.querySelectorAll('button,[role="button"]')].filter(n =>
      /^(?:turn in|submit|提出|提出する|上交|提交)$/i.test((n.innerText || n.getAttribute('aria-label') || '').trim()));
    return {scope, editor, button:buttons.length === 1 ? buttons[0] : null};
  }
  async function fetchDraft(consume=false) {
    let doc=document;
    if (canvas) {
      const res=await fetch('/profile/settings',{credentials:'same-origin',redirect:'error',signal:AbortSignal.timeout(8000)});
      if(!res.ok) throw new Error('请重新确认 Canvas 登录状态。');
      doc=new DOMParser().parseFromString(await res.text(),'text/html');
    }
    const id=StudyDockDOM.identity(doc, canvas?'canvas':'classroom');
    if(!id) throw new Error('无法确认这个页面的学校账号。');
    const response=await chrome.runtime.sendMessage({type:'assignment-draft',identity:id.key,consume});
    if(!response || response.error) throw new Error(response?.error || '采集助手尚未连接。');
    return response;
  }
  const read = n => n.tagName==='TEXTAREA'?n.value:n.innerText;
  function fill(editor, value) {
    if(editor.tagName==='TEXTAREA') Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(editor,value);
    else {
      editor.replaceChildren();
      value.split('\n').forEach((line,index)=>{
        if(index)editor.append(editor.ownerDocument.createElement('br'));
        editor.append(editor.ownerDocument.createTextNode(line));
      });
    }
    editor.dispatchEvent(new Event('input',{bubbles:true}));
    editor.dispatchEvent(new Event('change',{bubbles:true}));
    editor.dispatchEvent(new Event('blur'));
  }
  let panel, installedEditor, installedPath;
  function mount() {
    const form=controls();
    if(!form){panel?.remove();panel=null;return;}
    if(panel?.isConnected && installedEditor===form.editor && installedPath===location.pathname)return;
    panel?.remove();
    panel=document.createElement('div'); installedEditor=form.editor; installedPath=location.pathname;
    const shell=panel.attachShadow({mode:'closed'});
    const load=document.createElement('button'), send=document.createElement('button'), info=document.createElement('span');
    load.type=send.type='button';load.textContent='填入学习空间草稿';send.textContent='确认并提交这段文字';send.hidden=true;
    info.setAttribute('role','status');
    shell.append(load,send,info);form.scope.after(panel);
    const path=location.pathname, editor=form.editor;
    const sameForm=()=>location.pathname===path && controls()?.editor===editor;
    let draftTitle='', submitted=false;
    load.onclick=async event=>{
      if(!event.isTrusted || !sameForm())return;
      load.disabled=true;
      try {
        const draft=await fetchDraft();
        if(!sameForm())throw new Error('作业页面已改变，请重新选择。');
        if(read(editor).trim() && !confirm('用学习空间草稿替换这个回答框里的文字？'))return;
        fill(editor,draft.text);draftTitle=draft.title;
        send.hidden=!controls()?.button;
        info.textContent=send.hidden?' 已填入，请核对后使用原平台的提交按钮。':' 请核对回答框里的文字。';
      }catch(error){info.textContent=' '+error.message;}finally{load.disabled=false;}
    };
    send.onclick=async event=>{
      if(!event.isTrusted || submitted || !sameForm())return;
      const value=read(editor);
      if(!value.trim() || !confirm('向老师提交「'+draftTitle+'」当前回答框中的文字？'))return;
      send.disabled=true;
      try{
        await fetchDraft(true);
        const current=controls();
        if(!sameForm() || read(editor)!==value || !visible(current?.button))throw new Error('表单已变化，请核对原页面。');
        submitted=true;load.disabled=true;
        current.button.click();info.textContent=' 已点击原平台提交，请查看平台回执或继续其确认步骤。';
      }catch(error){info.textContent=' '+error.message;send.disabled=false;}
    };
  }
  let timer;
  const schedule=()=>{if(!timer)timer=setTimeout(()=>{timer=null;mount();},200);};
  new MutationObserver(schedule).observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['class','hidden','aria-hidden']});
  document.addEventListener('visibilitychange',schedule);schedule();
})();
