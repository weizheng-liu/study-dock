'use strict';
let conversation = [], questionInput = '', asking = false, conversationOwner, conversationEpoch = 0;

function assistantOwner(user) {
  const owner = user?.id ?? user?.name ?? null;
  if (owner === conversationOwner) return;
  conversationOwner = owner;
  conversationEpoch++;
  conversation = [];
  questionInput = '';
  asking = false;
}

function renderAssistant(main) {
  main.append(heading('学习助手', '按日本时间查截止日期，也可以让 AI 根据作业要求和课程资料回答。', syncButton()));
  const panel = E('section', 'panel assistant');
  const prompts = E('div', 'row wrap');
  for (const prompt of ['今天有什么作业', '明天要交什么作业', '未来七天有什么作业', '总结最近的作业和课程资料']) {
    const quick = button(prompt, () => sendQuestion(prompt), 'button secondary');
    quick.disabled = asking;
    prompts.append(quick);
  }
  panel.append(prompts);
  for (const message of conversation) {
    const block = E('article', 'chat-message');
    block.append(E('strong', '', message.role === 'user' ? '你' : message.mode === 'calendar' ? '作业日历' : '学习助手'),
      E('div', 'preline', message.text));
    for (const row of message.sources || []) {
      const due = row.due_at ? dateFormat.format(new Date(row.due_at))+' '+timeFormat.format(new Date(row.due_at))+' · ' : '';
      const label = (row.number ? '['+row.number+'] ' : '')+due+row.course+' · '+row.title;
      block.append(link(label, row.url, 'assistant-source'));
    }
    if (message.coverage) block.append(E('p','caption',message.coverage));
    if (message.updated) block.append(E('p','caption','最近同步尝试 '+new Date(message.updated).toLocaleString('zh-CN',{timeZone:'Asia/Tokyo'})));
    panel.append(block);
  }
  const form=E('form','ask-form'), input=E('textarea','input'), submit=E('button','button',asking?'正在查询…':'发送');
  input.placeholder='例如：电子回路这周有哪些要求？'; input.setAttribute('aria-label','你的问题');
  input.value=questionInput; input.maxLength=1500; input.required=true;
  input.addEventListener('input',()=>{questionInput=input.value;});
  submit.type='submit';submit.disabled=asking;
  form.addEventListener('submit',event=>{event.preventDefault();sendQuestion(input.value);});
  form.append(input,submit);
  panel.append(form,E('p','caption','快捷日期查询在本机完成。自由问答会将问题和相关课程摘录发送给 OpenAI。'));
  main.append(panel);
}

async function sendQuestion(value) {
  const question=value.trim();
  if (!question || asking) return;
  if (demo) return toast('请登录自己的账号后查询。');
  const epoch=conversationEpoch;
  const history=conversation.slice(-6).map(m=>({role:m.role,text:m.text.slice(0,1600)}));
  conversation.push({role:'user',text:question}); questionInput=''; asking=true; render();
  try {
    const result=await api('/api/assistant/ask',{question,history});
    if (epoch===conversationEpoch) conversation.push({...result,role:'assistant',text:result.answer});
  } catch (error) {
    if (epoch===conversationEpoch) conversation.push({role:'assistant',text:error.message});
  } finally {
    if (epoch===conversationEpoch) {asking=false;if(route==='assistant')render();}
  }
}

function textDraftControls(body,item) {
  const area=E('section','draft-panel');
  area.append(E('h3','','文字作业草稿'), E('p','caption','可以自己写，也可以把这项作业的标题和要求发给 OpenAI 起草。'));
  const text=E('textarea','input');text.rows=6;text.maxLength=12000;text.setAttribute('aria-label','待提交的草稿');
  const generate=button('根据要求起草',async()=>{
    if(text.value.trim() && !confirm('用新草稿替换当前文字？'))return;
    generate.disabled=true;
    try{const reply=await api('/api/assistant/draft',{id:item.id});text.value=reply.text;feedback.textContent='请核对答案后继续。';}
    catch(error){feedback.textContent=error.message;}finally{generate.disabled=false;}
  },'button secondary');
  const feedback=E('p','caption');feedback.setAttribute('role','status');
  const next=button('保存并准备提交',async()=>{
    try{await api('/api/assistant/save-draft',{id:item.id,text:text.value});
      feedback.replaceChildren(document.createTextNode('草稿已暂存 30 分钟。在原页面选择文字提交，再点「填入学习空间草稿」。 '),
        link('打开这项作业 ↗',item.url));
    }catch(error){feedback.textContent=error.message;}
  });
  const actions=E('div','row wrap');actions.append(generate,next);area.append(text,actions,feedback);body.append(area);
}
