/* Official API connections: Canvas personal token and Google Classroom OAuth.
   These are the preferred path; the browser collector stays as a fallback. */
'use strict';

function formatJst(value) {
  return new Date(value).toLocaleString('zh-CN', {timeZone: 'Asia/Tokyo'});
}

function isoDateJst(offsetDays) {
  const day = new Date(Date.now() + 9 * 3600 * 1000 + offsetDays * 86400 * 1000);
  return day.toISOString().slice(0, 10);
}

function tokenExpiryText(connection) {
  if (!connection.token_expires_at) return '';
  const date = new Date(connection.token_expires_at * 1000).toLocaleDateString('zh-CN', {timeZone: 'Asia/Tokyo'});
  if (connection.token_days_left < 0) return '令牌已于 ' + date + ' 过期，请重新生成。';
  if (connection.token_days_left === 0) return '令牌今天（' + date + '）到期，请尽快重新生成。';
  return '令牌 ' + date + ' 到期，还剩 ' + connection.token_days_left + ' 天。';
}

/* Overview banner: shown when the Canvas token is about to expire or already has. */
function tokenExpiryAlert() {
  const connection = state?.connections?.canvas || {};
  if (connection.mode !== 'token' || !connection.token_expiring) return null;
  if (connection.status?.token_expired) return null;  // the sync error alert already says it
  const alert = E('div', 'alert');
  alert.append(E('strong', '', 'Canvas：'),
               E('span', '', tokenExpiryText(connection) + ' 在 Canvas 设置里生成新令牌后，到「账号连接」粘贴替换即可。'));
  return alert;
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
    E('p', '', connection.mode === 'oauth' ? '已通过学校 OAuth 连接。'
      : usingToken ? '已连接：' + (connection.label || 'Canvas 账号')
      : '服务端直接调用 Canvas 官方接口，不再打开网页。令牌只保存在这台电脑。'),
    pill(usingToken ? '令牌已连接' : '尚未连接', usingToken ? 'submitted' : 'unknown'));

  const steps = E('ol', 'caption api-steps');
  for (const text of ['点下方按钮打开 Canvas「设置」页（用学校账号登录）。',
                      '在「已批准的集成」处点「+ 新建访问许可证」，用途写 Study Dock，有效期限选最长（日大最多 30 天）。',
                      '复制生成的令牌（只显示一次），粘贴到下面，到期日填你刚才选的日期，然后保存。'])
    steps.append(E('li', '', text));
  card.append(steps);

  const form = E('form', 'row wrap api-token-form');
  const input = E('input', 'input');
  input.type = 'password';
  input.autocomplete = 'off';
  input.spellcheck = false;
  input.placeholder = usingToken ? '粘贴新令牌以替换' : '粘贴 Canvas 访问令牌';
  input.setAttribute('aria-label', 'Canvas 访问令牌');
  const expires = E('input', 'input api-token-expiry');
  expires.type = 'date';
  expires.value = isoDateJst(30);
  expires.min = isoDateJst(0);
  expires.title = 'Canvas 令牌的有效期限日（日本时间）';
  expires.setAttribute('aria-label', '令牌到期日');
  const save = E('button', 'button', '保存并同步');
  save.type = 'submit';
  form.append(input, expires, save);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (demo) return toast('请退出演示，登录自己的学习空间后再连接。');
    save.disabled = true;
    try {
      const result = await api('/api/canvas-token', {token: input.value, expires: expires.value});
      input.value = '';
      toast('已连接 ' + result.label + '，正在读取课程和作业。');
      await refresh(true);
    } catch (error) { toast(error.message); } finally { save.disabled = false; }
  });
  card.append(form);

  const actions = E('div', 'row wrap');
  actions.append(link('打开 Canvas 设置 ↗', canvasUrl + '/profile/settings', 'button secondary'));
  if (usingToken) actions.append(syncNowButton(), disconnectButton('canvas', '删除令牌'));
  if (connection.configured) {
    // A school-approved Canvas OAuth app (app_config.json) remains an alternative to the token.
    const oauth = button(connection.mode === 'oauth' ? '重新 OAuth 授权' : '用学校 OAuth 授权', async () => {
      if (demo) return toast('请退出演示，登录自己的学习空间后再连接。');
      try { location.assign((await api('/api/connect', {source: 'canvas'})).url); }
      catch (error) { toast(error.message); }
    }, 'button secondary');
    oauth.disabled = state.syncing;
    actions.append(oauth);
  }
  if (connection.mode === 'oauth') actions.append(syncNowButton(), disconnectButton('canvas', '解除 OAuth 连接'));
  card.append(actions);
  if (usingToken && connection.token_expires_at)
    card.append(E(connection.token_expiring ? 'div' : 'p', connection.token_expiring ? 'alert' : 'caption', tokenExpiryText(connection)));
  if (usingToken || connection.mode === 'oauth') apiStatusLine(card, connection);
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
