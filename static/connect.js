/* Official API connections: Canvas personal token and Google Classroom OAuth.
   These are the preferred path; the browser collector stays as a fallback. */
'use strict';

function formatJst(value) {
  return new Date(value).toLocaleString('zh-CN', {timeZone: 'Asia/Tokyo'});
}

function apiStatusLine(card, connection) {
  const status = connection.status;
  if (!status) return;
  let text = status.message;
  if (status.last_success_at) text += '\n上次成功同步：' + formatJst(status.last_success_at);
  card.append(E('div', 'sync-detail', text));
  for (const warning of status.warnings || []) card.append(E('p', 'caption', '· ' + warning));
}

function disconnectButton(source, label) {
  return button(label, async () => {
    try {
      await api('/api/disconnect', {source});
      await refresh(true);
      toast('本机保存的授权和该平台缓存已删除。');
    } catch (error) { toast(error.message); }
  }, 'button quiet');
}

function syncNowButton() {
  const b = button('立即同步', async () => {
    try {
      const result = await api('/api/sync', {});
      toast(result.started ? '已开始同步，通常几秒到一分钟完成。' : '同步已在进行中。');
      await refresh(true);
    } catch (error) { toast(error.message); }
  }, 'button secondary');
  b.disabled = state.syncing;
  return b;
}

function canvasTokenCard() {
  const connection = state.connections?.canvas || {};
  const usingToken = connection.mode === 'token';
  const canvasUrl = state.canvas_url || 'https://nu.instructure.com';
  const card = E('section', 'panel connection-card');
  card.append(
    E('div', 'platform-logo canvas', 'C'),
    E('h2', '', 'Canvas · 访问令牌'),
    E('p', '', usingToken ? '已连接：' + (connection.label || 'Canvas 账号')
      : '服务端直接调用 Canvas 官方接口，不再打开网页。令牌只保存在这台电脑。'),
    pill(usingToken ? '令牌已连接' : '尚未连接', usingToken ? 'submitted' : 'unknown'));

  const steps = E('ol', 'caption api-steps');
  for (const text of ['点下方按钮打开 Canvas「设置」页（用学校账号登录）。',
                      '在「已批准的集成」处点「+ 新建访问许可证」，用途写 Study Dock，到期日可以留空或设到学期末。',
                      '复制生成的令牌（只显示一次），粘贴到下面并保存。'])
    steps.append(E('li', '', text));
  card.append(steps);

  const form = E('form', 'row wrap api-token-form');
  const input = E('input', 'input');
  input.type = 'password';
  input.autocomplete = 'off';
  input.spellcheck = false;
  input.placeholder = usingToken ? '粘贴新令牌以替换' : '粘贴 Canvas 访问令牌';
  input.setAttribute('aria-label', 'Canvas 访问令牌');
  const save = E('button', 'button', '保存并同步');
  save.type = 'submit';
  form.append(input, save);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (demo) return toast('请退出演示，登录自己的学习空间后再连接。');
    save.disabled = true;
    try {
      const result = await api('/api/canvas-token', {token: input.value});
      input.value = '';
      toast('已连接 ' + result.label + '，正在读取课程和作业。');
      await refresh(true);
    } catch (error) { toast(error.message); } finally { save.disabled = false; }
  });
  card.append(form);

  const actions = E('div', 'row wrap');
  actions.append(link('打开 Canvas 设置 ↗', canvasUrl + '/profile/settings', 'button secondary'));
  if (usingToken) actions.append(syncNowButton(), disconnectButton('canvas', '删除令牌'));
  card.append(actions);
  if (usingToken) apiStatusLine(card, connection);
  return card;
}

function classroomOauthCard() {
  const connection = state.connections?.classroom || {};
  const authorized = connection.mode === 'oauth';
  const card = E('section', 'panel connection-card');
  card.append(
    E('div', 'platform-logo classroom', 'G'),
    E('h2', '', 'Classroom · Google 授权'),
    E('p', '', authorized ? '已通过 Google 官方接口授权，日期带完整年份，不需要猜。'
      : connection.configured ? '已配置 Google OAuth 客户端。点授权，用学校 Google 账号登录并同意只读权限。'
      : '需要先在 Google Cloud 建一个 OAuth 客户端（约 10 分钟，只做一次），步骤见 docs/api-setup.zh-CN.md。'),
    pill(authorized ? '已授权' : connection.configured ? '等待授权' : '尚未配置', authorized ? 'submitted' : 'unknown'));

  const actions = E('div', 'row wrap');
  if (connection.configured) {
    const connect = button(authorized ? '重新授权' : '用 Google 账号授权', async () => {
      if (demo) return toast('请退出演示，登录自己的学习空间后再连接。');
      try { location.assign((await api('/api/connect', {source: 'classroom'})).url); }
      catch (error) { toast(error.message); }
    });
    connect.disabled = state.syncing;
    actions.append(connect);
  }
  if (authorized) actions.append(syncNowButton(), disconnectButton('classroom', '解除授权'));
  card.append(actions);
  card.append(E('p', 'caption', '如果 Google 提示“管理员已阻止此应用”(admin_policy_enforced)，说明学校不允许第三方应用，请继续使用下方的浏览器采集助手。'));
  if (authorized) apiStatusLine(card, connection);
  return card;
}

function renderApiConnections(main) {
  const intro = E('section', 'panel nodate');
  intro.append(E('div', 'eyebrow', 'OFFICIAL API · 推荐'),
               E('h2', '', '用官方接口同步：不开网页、不翻页'),
               E('p', 'caption', '本机服务每 15 分钟自动拉取一次。连好以后，对应平台就不再需要浏览器采集助手。'));
  main.append(intro);
  const grid = E('div', 'connection-grid nodate');
  grid.append(canvasTokenCard(), classroomOauthCard());
  main.append(grid);
}
