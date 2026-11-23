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

To install it manually, enable developer mode in Chrome or Edge, load `extension/` as an unpacked extension, and pair it with the one-time code from the dashboard. Sign in to school platforms on their official websites. The default Canvas integration targets `nu.instructure.com`.

### Test

```powershell
python -m unittest discover -s tests -v
node tests/test_extension_browser.mjs
```

Extension tests use Microsoft Edge with a temporary profile and simulated school pages. Set `EDGE_PATH` to override the browser executable. [Detailed configuration guide in Chinese](docs/guide.zh-CN.md)
