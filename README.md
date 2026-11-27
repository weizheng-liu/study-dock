[English](#english)

# Study Dock · 学习空间

在一个本机网页中查看 Canvas 和 Google Classroom 的作业、截止日期、公告和学习资料。也可以先打开内置演示，体验日历和作业详情。配套的 Chrome/Edge 采集扩展位于 [extension/](extension/)。

## 运行

安装 Python 3.11+，在仓库目录执行：

```powershell
python app.py --open
```

打开 [学习空间](http://127.0.0.1:8840/)，可以先点「先看看演示」。

| Windows 入口 | 用途 |
|---|---|
| `打开作业日历.cmd` | 打开本机学习空间 |
| `打开学习空间与采集助手.cmd` | 使用独立 Edge 配置打开学习空间和采集助手 |
| `打开采集助手（Chrome）.cmd` | 使用独立 Chrome 配置打开学习空间和采集助手 |

**推荐先用官方接口同步**：Canvas 粘贴个人访问令牌即可，Classroom 需自建一次 Google OAuth 客户端；连好后由本机服务直接拉取，不用开网页。步骤见 [官方接口设置](docs/api-setup.zh-CN.md)。学校不允许时，再用下面的采集扩展兜底。

**课程大纲（シラバス）**：「课程大纲」页直接查日本大学理工学部官网公开的シラバス（科目名、老师名、时间割代码都能搜，全角半角不敏感），不用登录。在课程页的「课程大纲」标签把大纲关联到 Canvas / Classroom 课程后，学习助手回答评分方法、教材、每回内容时会引用它。学校数据缓存在 `data/syllabus/`，科目列表每天刷新一次。

手动安装时，在 Chrome 或 Edge 扩展管理页启用开发者模式并加载 `extension/`。在「账号连接」生成一次性配对码，然后在采集助手里配对。学校账号在官方网页登录。默认 Canvas 站点为 `nu.instructure.com`。 [采集助手安装说明](extension/README.md)

## 测试

```powershell
python -m unittest discover -s tests -v
node tests/test_extension_browser.mjs
```

扩展测试使用 Microsoft Edge、临时浏览器配置和模拟学校页面。用 `EDGE_PATH` 指定浏览器路径。 [完整配置及开发说明](docs/guide.zh-CN.md)

## English

Study Dock is a local dashboard for coursework, deadlines, announcements, and materials from Canvas and Google Classroom. The sign-in page includes a built-in demo. The companion Chrome/Edge collector lives under [extension/](extension/).

### Run locally

Install Python 3.11+ and run the following from the repository folder:

```powershell
python app.py --open
```

Open [the local dashboard](http://127.0.0.1:8840/). The three Windows launchers open the dashboard by itself, or open the dashboard and collector in a dedicated Edge or Chrome profile. Load the collector manually the first time you use the dedicated Chrome profile.

Preferred: sync through the official APIs. Paste a Canvas personal access token, and create a Google OAuth client once for Classroom; see [API setup (Chinese)](docs/api-setup.zh-CN.md). The browser collector remains as a fallback.

Syllabus lookup: the "课程大纲" page searches the public syllabus of Nihon University College of Science and Technology (no login). Link a syllabus to a synced course so the study assistant can cite it.

To install it manually, enable developer mode in Chrome or Edge, load `extension/` as an unpacked extension, and pair it with the one-time code from the dashboard. Sign in to school platforms on their official websites. The default Canvas integration targets `nu.instructure.com`.

### Test

```powershell
python -m unittest discover -s tests -v
node tests/test_extension_browser.mjs
```

Extension tests use Microsoft Edge with a temporary profile and simulated school pages. Set `EDGE_PATH` to override the browser executable. [Detailed configuration guide in Chinese](docs/guide.zh-CN.md)
