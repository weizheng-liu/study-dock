# Study Dock · 学生学习空间

面向 `nu.instructure.com` 同学的学习门户。默认使用“本机网页 + Chrome / Edge 采集插件”：你在官方页面登录，插件读取本人可访问的课程，再同步到本站账号。也保留可选的官方 OAuth 接入。

已实现：

- 概览：今天截止、未来七天与已过截止时间的作业。
- 作业：统一月历，按平台、课程和关键词筛选，查看作业文字要求、附件、截止时间和提交状态；没有截止日期的作业单独列出。
- 课程与资料：选择学科，切换作业、公告和学习资料。Canvas 包含课程文件、页面入口和学习单元；Classroom 包含学习资料及 Drive / 链接等附件入口。
- 浏览器连接：一次性配对码、独立学校账号绑定、自动翻页采集、按用户导入、撤销插件配对。无需先取得学校 OAuth 开发者配置。
- 可选 API 连接：各用户独立 OAuth 授权、刷新授权、解除本机连接。
- 日历导出：`.ics` 文件可导入手机日历；事件包含作业要求、原文链接和提前一天提醒。是否触发提醒由日历客户端决定。
- 浏览器和本机程序运行期间，插件每十五分钟尝试更新；也可在网页或插件中手动更新。失败时保留已有内容，并提示需要登录、页面未识别或日期待确认。
- 多用户数据隔离、密码哈希、会话 Cookie、CSRF 校验、OAuth state 校验；Windows 下用当前服务账号的 DPAPI 加密平台授权令牌。

**当前是本机运行的网页和可安装的首版插件，尚未公开部署。可分发安装包给同学分别在自己的电脑上运行。自动化检查已验证真实插件与本机网页的完整链路，但学校页面使用的是测试 HTML；真实学校账号的页面布局、日期格式和账号识别需要本人登录后验证。演示模式仍使用示例数据。**

## 在这台电脑上运行

需要 Python 3.11 或更新版本，不需要安装第三方 Python 包。

已有采集助手时，双击仓库根目录的 **打开作业日历.cmd** 即可打开学习助手。这个入口会在后台启动本机服务，服务已运行时直接打开网页。重启电脑后再双击一次即可。

已经部署 Chrome 版时，双击仓库根目录的 **打开采集助手（Chrome）.cmd**；学习空间和助手会在独立 Chrome 窗口打开，配对在该配置中保存。Chrome 登录状态与之前的 Edge 配置互相独立，需要分别登录学校平台。

推荐双击仓库根目录的 **打开学习空间与采集助手.cmd**：它启动网页，并使用独立 Edge 配置打开网页和插件面板，不复制现有浏览器中的登录状态。首次使用按以下步骤操作：

1. 在学习空间注册或登录**本站账号**，进入“账号连接”。
2. 生成一次性配对码，在采集助手面板粘贴并连接；配对码十分钟内有效，只能使用一次。
3. 在采集助手中分别打开官方页面，手动登录学校 Canvas / Classroom 账号。
4. 确认学校网页显示时区（默认日本 UTC+9），点击对应的“绑定并同步当前账号”。
5. 回网页查看日历、作业要求和课程资料。

学校账号密码和验证码只在官方页面输入，不在本站或聊天中填写。启动器创建的独立 Edge 登录状态保存在 `data/collector-browser/`，不应打包、分享或上传。

如果 Edge 阻止自动加载，或想使用自己已有登录状态的浏览器，可以先双击 `打开作业日历.cmd`，再按 [插件安装说明](../extension/README.md) 手动加载 `extension` 文件夹。学校管理的浏览器如果禁止安装扩展，插件无法更改该策略。

只启动网页也可在本目录执行：

```powershell
python app.py --open
```

浏览器打开 `http://127.0.0.1:8840`。关闭命令窗口或按 Ctrl+C 会停止服务和自动同步。

首次可以点“先看看演示”，查看完整界面。演示不读取账号、不写入真实作业，也不包含真实附件。

插件安装后可以固定到浏览器工具栏。首次绑定会打开一个后台标签页，确认账号后遍历页面；采集结束前再次确认账号一致。浏览器关闭、登录过期或机器休眠时无法保证更新。

程序数据存放在 `data/portal.db`。该文件包含本站账号、课程缓存、插件配对令牌的哈希与可选 API 授权，不能作为普通附件分发给同学。源码压缩包排除整个 `data/`、真实配置文件和测试运行输出。

## 浏览器采集的具体行为

手动更新 Classroom 会打开可见的学生课程页，让 Google 加载课程卡片。课程清单会先进入学习空间，随后继续读取作业与资料。自动更新使用后台标签页，页面未能加载时保留已取得的数据。

- 只匹配 `https://nu.instructure.com/*`、`https://classroom.google.com/*` 和 `http://127.0.0.1:8840/*`。不申请读取 Cookie、历史记录或所有网站的权限；不读取密码输入框的值。
- 本机网页通过一次性配对码授权插件导入本站用户的数据。配对令牌有效期九十天，可在网页撤销；与学校登录凭据无关。新配对后需要重新确认学校平台绑定。
- Canvas 以账号设置页的用户标识确认账号；Classroom 读取当前账号按钮的标识。多个 Google 账号时，应先在目标 Classroom 标签页切到学校账号，再打开插件绑定。
- 按可访问入口读取课程列表、作业详情、学习资料、文件入口和公告；会尝试展开明确的“更多”按钮与折叠课程条目。页面改版、虚拟列表、登录策略或没有详情入口的内容可能无法完整识别。
- 默认一次最多读取一百五十页，可在插件中调整到二十至三百页；超过上限会提示还有页面未读。不会把部分采集当成平台的完整快照。
- 增量合并，详情优先于列表摘要，更新截止日期时使用新读取的详情。未出现在本次页面中的旧条目不会自动删除；如需重置，可以解除平台绑定后重新绑定。
- 仅把明确的完整日期及时间排入日历；不能可靠解析的文字放在“未排入日历”并提示“日期待确认”。发帖时间不会作为截止日期。
- 采集前后都校验账号；发现切换账号会停止导入并保留缓存。主动重新绑定另一个账号会清除该平台旧缓存。
- “停止当前采集”会关闭插件自己打开的标签页并关闭自动更新。手动启动同步或重新开启自动更新后才继续。
- 网页“同步课程”通过本机任务通知插件，通常最多约一分钟被检查到。自动更新和通知都需要浏览器与本机程序运行。

网页版的展示、浏览器采集器、本机导入接口已经分离，后续桌面封装可继续复用网页和数据格式；此版本尚未封装成独立安装的桌面应用。

## 可选的官方 API 模式

以下配置只用于“账号连接”底部的官方 OAuth 接入，**浏览器采集模式不需要填写它们**。

将 `app_config.example.json` 复制为 `app_config.json`。保持配置文件私有，勿将 Client Secret 发进聊天、截图或代码仓库。

本地配置文件的 `base_url` 默认为 `http://127.0.0.1:8840`。下列回调地址须与配置文件中的地址和端口完全一致。更改配置后重启程序。

### Canvas：需要学校管理员批准应用

在学校 Canvas 配置 OAuth Developer Key。学校可能限制学生创建此类配置；这种情况下必须由学校管理员创建或批准。

配置回调：

```text
http://127.0.0.1:8840/oauth/canvas/callback
```

把得到的应用 Client ID 和 Client Secret 写入配置文件的 `canvas` 对象。`base_url` 保持 `https://nu.instructure.com`。

若学校启用 scoped Developer Key，允许以下只读 scopes，需与 `app.py` 的 `CANVAS_SCOPES` 对应：

```text
url:GET|/api/v1/courses
url:GET|/api/v1/courses/:course_id/assignments
url:GET|/api/v1/courses/:course_id/discussion_topics
url:GET|/api/v1/courses/:course_id/files
url:GET|/api/v1/courses/:course_id/pages
url:GET|/api/v1/courses/:course_id/modules
url:GET|/api/v1/courses/:course_id/modules/:module_id/items
```

应用使用 OAuth 登录流程，不要求同学填写个人 Access Token。Canvas 官方要求多人应用通过 OAuth 获取每个用户的令牌，参见 [Canvas OAuth 文档](https://developerdocs.instructure.com/services/canvas/oauth2/file.oauth)。

### Google Classroom：应用管理员配置 Google OAuth

1. 在 Google Cloud 项目启用 **Google Classroom API**，配置 OAuth 同意页面及使用人群。
2. 创建 **Web application** 类型的 OAuth 客户端，登记重定向地址：

   ```text
   http://127.0.0.1:8840/oauth/classroom/callback
   ```

3. 把 Client ID 和 Client Secret 写入配置文件的 `classroom` 对象。
4. 配置以下只读 scopes；如果应用处于测试状态，将实际学校账号加入测试用户：

   ```text
   https://www.googleapis.com/auth/classroom.courses.readonly
   https://www.googleapis.com/auth/classroom.coursework.me.readonly
   https://www.googleapis.com/auth/classroom.courseworkmaterials.readonly
   https://www.googleapis.com/auth/classroom.announcements.readonly
   ```

5. 学校的 Google Workspace 管理策略可能还要求管理员允许这个 OAuth 应用。面向同学正式开放时，需要按 Google 的要求完成相应的发布或验证流程。

每个同学连接时都要同意课程、自己的作业、公告和学习资料权限。程序不请求写入课程、替你提交作业或修改成绩的权限。

Google 授权使用 state 和 PKCE 校验；第一次连接取得离线刷新令牌，之后在服务运行时刷新。测试应用的令牌仍可能过期，页面会提示重新连接。

## 给同学访问时

当前回环地址只在本机可用。共享网站需要固定域名、HTTPS 和持续运行的服务器。当前插件固定向本机地址导入；迁移为公共网站时，还需同时配置插件的目标地址和域名权限，不能仅部署网页就声称支持共享采集。若启用官方 API 模式，也要修改两个平台的回调地址。

例如把 `base_url` 配置成 `https://study.example.edu`，用 HTTPS 反向代理转发到本机服务。只有管理员明确配置 HTTPS `base_url` 后，程序才允许通过 `--host` 绑定非回环地址：

```powershell
python app.py --host 0.0.0.0 --port 8840
```

反向代理需保留正式域名的 `Host` 请求头，提供连接超时、请求限速和 HTTPS。不要直接把 Python 开发服务器端口暴露到公网。公开上线还需替换为生产服务方式，配置备份、账号找回、服务监控，以及根据学校要求确认使用人群。当前原型没有邮箱验证或自助密码找回。

Windows 的令牌加密绑定运行服务的 Windows 账号；迁移到不同账号后需重新授权。非 Windows 下当前仅依赖数据库文件权限限制，正式上线前需改接服务器密钥管理或加密存储。配置文件中的应用 Client Secret 也需要受操作系统权限或服务器密钥管理保护。

## 日期和资料边界

- 所有日期统一显示为日本时间 UTC+9。API 模式下 Classroom 的 `dueDate` 和 `dueTime` 是 UTC；页面模式下使用学校页面明确显示的时区或插件中确认的显示时区。
- API 模式下 Canvas 使用当前授权学生适用的 `due_at`；页面模式下读取当前学生页面显示的截止时间。关闭提交时间不会冒充截止时间。
- 课程只同步当前有效的学生课程，不读取其他同学或管理员数据。
- 仅按平台明确提供的截止字段安排日历。老师只写在公告、作业正文、PDF 或口头通知中的日期暂不自动识别，也不编造日期。
- 平台显示“已评分”或“已退回”不能直接证明无需后续操作，所以在作业列表中保留并提示确认。
- 页面和文件条目会给出原平台入口；查看受限资料、下载附件或访问外部教学工具时，浏览器可能还需要学校登录。当前不完整镜像 PDF、视频或外部工具，也不绕过学校权限。
- Canvas 作业正文中的相对附件链接按原作业地址补全，并保留链接文字作为附件名称。
- 同一文件可能同时作为课程文件和某个学习单元的项目出现。
- `.ics` 是导出当时的快照，不是持续订阅。之后作业变化要重新导出；不同日历客户端重新导入时的去重行为不同。没有日期的作业仍保留在网页列表中，不强行排进日历。
- 解除本机连接会清除该用户该平台的本机令牌与缓存；撤销平台端授权请到 Canvas 或 Google 的授权设置操作。

## 验证

```powershell
python -m unittest discover -s tests -v
node --check static/app.js
node --check extension/background.js
```

测试覆盖 UTC 跨日、零点、无截止日期、分页、分页来源校验、资料分类部分失败、缓存保留、日历 UTF-8 折行、账号数据隔离、导出权限、CSRF、OAuth state 和 Windows 加密往返。

`tests/test_connections.py` 还用模拟平台响应串联两个平台的授权成功、读取课程与作业要求、资料入库、日历导出、授权续期和解除单个平台连接；不完整授权会保留原连接。这些检查不等同于真实学校 OAuth 已获批准或真实课程同步已验证。

启动本地服务后，还可用已安装的 Chrome 运行真实浏览器冒烟检查：

```powershell
node tests/test_ui.mjs
node tests/test_extension_browser.mjs
```

界面检查使用临时 Chrome 配置，插件检查使用临时 Edge 配置，都不读取已有浏览器账号。截图和验证记录放在 `test-output/`。真实插件检查会在浏览器发出学校请求前拦截并返回测试 HTML，验证实际扩展加载、内容脚本、自动翻页、双平台绑定、作业要求、附件、资料、本机配对与导入，以及学校账号切换时停止导入。它不证明真实学校页面已适配或真实学校 OAuth 已获批准。

## 官方接口依据

「学习助手」可在本机查询今天、明天和未来七天的已同步作业。自由问答与生成文字草稿使用服务端 OpenAI Responses API，读取环境变量或项目根目录 `.env.local` 中的 `OPENAI_API_KEY`。在界面主动发送问题或要求起草时，服务端会发送问题与相关课程摘录。按账号隔离数据，密钥和运行数据不随压缩包分发。

在支持文字提交的作业详情中编辑草稿，点击「保存并准备提交」，然后在学校页面选择文字回答。采集助手会提供填入草稿与确认提交的按钮，平台回执决定最终状态。草稿仅在当前本机进程暂存 30 分钟。文件上传题仍需在学校页面上传。

- [Canvas 作业与个人适用的截止时间](https://developerdocs.instructure.com/services/canvas/resources/assignments)
- [Canvas 学习单元及分页](https://developerdocs.instructure.com/services/canvas/resources/modules)
- [Google Classroom 学生可见的作业与只读权限](https://developers.google.com/workspace/classroom/reference/rest/v1/courses.courseWork/list)
- [Classroom 截止日期及 UTC 定义](https://developers.google.com/workspace/classroom/reference/rest/v1/courses.courseWork)
- [Classroom 学习资料](https://developers.google.com/workspace/classroom/reference/rest/v1/courses.courseWorkMaterials/list)
