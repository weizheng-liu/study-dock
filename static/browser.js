/* Browser collection transport stays separate from the reusable calendar UI. */
function renderBrowserConnections(main){
  main.append(heading('连接学习平台','优先用官方接口直接同步；学校不允许时，再用浏览器采集助手兜底。'));
  renderApiConnections(main);
  main.append(E('h2','fallback-title nodate','备用：浏览器采集助手'));
  const setup=E('section','panel browser-setup');
  setup.append(E('div','eyebrow','BROWSER COLLECTOR'),E('h2','','三步连接你的真实课程'));
  const steps=E('div','browser-steps');
  for(const [number,title,description]of [['01','安装采集助手','下载并解压插件，在 Chrome 或 Edge 的扩展管理页，开启开发者模式并“加载已解压的扩展程序”。'],['02','配对这个学习空间','在下方生成一次性配对码，点击浏览器工具栏的 Study Dock，粘贴配对码并连接。'],['03','登录并绑定平台账号','在插件中打开官方登录页，完成登录，再点“绑定并同步当前账号”。Classroom 多账号请先切到目标学校账号。']]){
    const step=E('div','browser-step');step.append(E('span','step-number',number),E('h3','',title),E('p','caption',description));steps.append(step);
  }
  setup.append(steps);const actions=E('div','row wrap');
  const download=E('a','button secondary','下载浏览器插件');download.href='/extension.zip';download.download='study-dock-extension.zip';actions.append(download);
  actions.append(button('生成一次性配对码',async()=>{
    if(demo)return toast('请退出演示，注册或登录自己的学习空间后配对。');
    try{const result=await api('/api/browser/pair-code',{});const body=document.querySelector('#detailBody');body.replaceChildren(E('h2','','连接到这个学习空间'),E('p','','在浏览器工具栏打开 Study Dock 采集助手，将下方配对码粘贴进去。配对码 10 分钟内有效，使用一次后失效。'));
      const code=E('input','input pair-code');code.readOnly=true;code.value=result.code;code.setAttribute('aria-label','一次性配对码');body.append(code,button('复制配对码',async()=>{try{await navigator.clipboard.writeText(result.code);toast('已复制。请粘贴到浏览器插件。');}catch{code.select();toast('请手动复制选中的配对码。');}}));dialog.showModal();
    }catch(error){toast(error.message);}
  }));setup.append(actions,E('p','caption nodate','插件仅匹配学校 Canvas、Google Classroom 和本机学习空间，不读取其他网站。无需填写学校密码。'));main.append(setup);
  const grid=E('div','connection-grid nodate');
  for(const source of ['canvas','classroom']){
    const binding=state.browser?.bindings?.[source],connection=state.connections?.[source]||{};
    const card=E('section','panel connection-card');card.append(E('div','platform-logo '+source,source==='canvas'?'C':'G'),E('h2','',sourceName(source)),E('p','',binding?.label||'在官方页面登录后，通过插件绑定当前学校账号。'),pill(binding?'浏览器已绑定':connection.connected?'已用官方接口连接':'等待插件绑定',binding?'submitted':'unknown'));
    const actions=E('div','row wrap');actions.append(link('打开官方页面 ↗',source==='canvas'?(state.canvas_url||'https://nu.instructure.com')+'/profile/settings':'https://classroom.google.com/','button secondary'));
    if(binding||connection.connected)actions.append(button('解除平台绑定',async()=>{try{await api('/api/disconnect',{source});await refresh(true);toast('该平台绑定和缓存已清除。');}catch(error){toast(error.message);}},'button quiet'));
    card.append(actions);
    if(binding?.last_import_at)card.append(E('p','sync-detail','上次收到页面数据：'+new Date(binding.last_import_at).toLocaleString('zh-CN',{timeZone:'Asia/Tokyo'})));
    if(state.browser?.requests?.[source])card.append(E('p','sync-detail','已请求更新，等待插件检查任务（通常最多约 1 分钟）。'));
    if(connection.status)card.append(E('div','sync-detail',connection.status.message));grid.append(card);
  }
  main.append(grid,E('p','caption nodate','自动更新需要本机程序和浏览器同时运行、学校登录仍有效。页面无法识别或截止日期缺少年份、时刻时，会保留原文提示确认。页面采集增量合并，未见到的旧记录不会自动删除。'));
  if(state.browser?.devices?.length){const devices=E('section','panel nodate');devices.append(E('h2','','已配对的采集助手'));for(const device of state.browser.devices){const row=E('div','row spread wrap');row.append(E('span','caption',device.label+' · 最近连接 '+new Date(device.last_seen*1000).toLocaleString('zh-CN',{timeZone:'Asia/Tokyo'})),button('撤销此插件配对',async()=>{try{await api('/api/browser/revoke',{device_id:device.id});await refresh(true);toast('此插件已无法向你的学习空间导入数据。');}catch(error){toast(error.message);}},'button quiet'));devices.append(row);}main.append(devices);}
  
}
async function syncAllSources(){
  if(demo)return toast('请退出演示并连接自己的平台账号。');
  const browserBound=Object.keys(state.browser?.bindings||{}).length>0;
  const result=await api('/api/sync',{});
  if(browserBound){await api('/api/browser/sync',{});toast('已通知采集助手更新。请保持浏览器和本机程序运行。');}
  else if(!result.started)toast('请先在“账号连接”安装插件并绑定平台。');
  await refresh(true);
}
