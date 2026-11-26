# 用官方接口同步（推荐）

浏览器采集助手要打开网页、逐页翻，慢且容易被页面改版搞坏。两个平台都有官方 REST 接口，连好以后由本机服务直接拉数据，每 15 分钟自动同步一次，不需要开任何网页。

| 平台 | 方式 | 需要你做的 | 学校可能拦截吗 |
|---|---|---|---|
| Canvas | 个人访问令牌（Access Token） | 在 Canvas 设置里点一次「新建访问许可证」 | 一般不会；如果设置页没有这个按钮，说明学校关了，只能用采集助手 |
| Classroom | Google OAuth | 建一个 Google Cloud 项目和 OAuth 客户端（约 10 分钟，一次性） | 有可能：学校 Google Workspace 管理员可以禁止未批准的第三方应用 |

两个平台互相独立：可以 Canvas 用令牌、Classroom 继续用采集助手。某个平台改用官方接口后，这个平台的插件绑定会自动解除。

---

## Canvas：个人访问令牌

1. 运行 `python app.py --open`，登录学习空间，进入「账号连接」。
2. 点「打开 Canvas 设置」，用学校账号登录（`https://nu.instructure.com/profile/settings`）。
3. 在「已批准的集成」(Approved Integrations) 下点 **+ 新建访问许可证**（New Access Token）。
   - 用途：`Study Dock`
   - 到期日：可以留空，建议设到学期末，到期后重新生成一个即可。
4. 复制生成的令牌。**它只显示一次**，关掉就看不到了。
5. 回到学习空间，粘贴进「Canvas · 访问令牌」卡片，点「保存并同步」。程序会先用它读取你的 Canvas 姓名确认有效，然后开始同步课程、作业、截止时间、提交状态、公告、文件和学习单元。

注意：

- **令牌等于你的 Canvas 账号权限**（Canvas 个人令牌不分权限范围）。本程序只发 GET 只读请求，但令牌本身能做的事更多：不要发到聊天、截图、提交到仓库，也不要给任何人。
- 令牌保存在 `data/portal.db`；Windows 下用当前 Windows 账号的 DPAPI 加密。
- 不想用了：在学习空间点「删除令牌」，同时在 Canvas 设置页把这个令牌删掉。
- 如果同步提示「授权已过期」，说明令牌过期或被删，重新生成一个粘贴即可。
- Canvas 地址不是 `nu.instructure.com` 时，在 `app_config.json` 的 `canvas.base_url` 改掉并重启。令牌模式**不需要**填 `client_id` / `client_secret`。

---

## Classroom：Google OAuth

Classroom 没有「个人令牌」，必须走 OAuth。也就是你自己当一回“应用开发者”：建一个只给自己用的 Google Cloud 应用，再用学校账号授权它只读你的课程。

### 1. 建 Google Cloud 项目

1. 打开 [Google Cloud Console](https://console.cloud.google.com/)。
   - 用**学校账号**登录能建项目的话，优先用学校账号（后面可以选「内部」，没有 7 天过期问题）。
   - 学校账号建不了项目，就用**个人 Gmail** 建，后面选「外部」。
2. 顶部项目选择器 → **新建项目**，名字随意，例如 `study-dock`。

### 2. 启用 Classroom API

左侧菜单 **API 和服务 → 库**，搜索 `Google Classroom API`，点 **启用**。

### 3. 配置 OAuth 同意屏幕

左侧菜单 **Google Auth Platform**（旧版界面叫「OAuth 同意屏幕」）：

1. **品牌塑造 / 应用信息**：应用名称 `Study Dock`，支持邮箱填你自己的。
2. **目标对象（受众）**：
   - 学校账号建的项目：选 **内部**（Internal）。
   - 个人 Gmail 建的项目：选 **外部**（External），发布状态保持 **测试**，然后在「测试用户」里**添加你的学校邮箱**。
3. **数据访问（范围）**：添加以下 4 个只读范围（前两个必需，后两个用于资料和公告，可选）：

   ```text
   https://www.googleapis.com/auth/classroom.courses.readonly
   https://www.googleapis.com/auth/classroom.coursework.me.readonly
   https://www.googleapis.com/auth/classroom.courseworkmaterials.readonly
   https://www.googleapis.com/auth/classroom.announcements.readonly
   ```

### 4. 创建 OAuth 客户端

**Google Auth Platform → 客户端 → 创建客户端**：

- 应用类型：**Web 应用**
- 已获授权的重定向 URI：

  ```text
  http://127.0.0.1:8840/oauth/classroom/callback
  ```

创建后复制 **客户端 ID** 和 **客户端密钥**。

### 5. 写入本机配置

把仓库里的 `app_config.example.json` 复制为 `app_config.json`（已在 `.gitignore`，不会被提交），填入：

```json
{
  "base_url": "http://127.0.0.1:8840",
  "canvas": { "base_url": "https://nu.instructure.com" },
  "classroom": {
    "client_id": "粘贴客户端 ID",
    "client_secret": "粘贴客户端密钥"
  }
}
```

重启 `python app.py --open`。

### 6. 授权

「账号连接」→「Classroom · Google 授权」→ **用 Google 账号授权**，选学校账号，同意只读权限。回到学习空间后会自动开始同步。

### 可能遇到的情况

| 看到什么 | 什么意思 | 怎么办 |
|---|---|---|
| 「Google 尚未验证此应用」 | 自己建的测试应用都会这样 | 点「继续」。这是你自己的应用 |
| `Error 400: admin_policy_enforced` / 「管理员已阻止此应用」 | 学校 Workspace 禁止未批准的第三方应用 | 代码解决不了。继续用浏览器采集助手，或请学校 IT 把你的客户端 ID 加入信任列表 |
| `Error 403: access_denied` | 外部应用但你的学校邮箱不在测试用户里 | 回第 3 步添加测试用户 |
| `redirect_uri_mismatch` | 重定向地址不一致 | 确认第 4 步的地址和 `base_url`、端口完全一致 |
| 同步提示「账号或学校未允许此接口访问」 | 403：项目没启用 Classroom API，或学校对学生关闭了 API | 检查第 2 步；还不行就是学校策略 |
| 大约一周后提示「授权已过期」 | 「外部 + 测试」状态的应用，Google 刷新令牌 7 天过期 | 点「重新授权」。用学校账号建「内部」项目可避免 |

授权后只请求只读权限：不能替你提交作业、改成绩或读取其他同学的数据。Classroom 接口返回的截止日期带完整年份并以 UTC 表示，学习空间统一按日本时间显示，不再需要猜年份。

撤销授权：学习空间点「解除授权」，并在 [Google 账号 → 第三方连接](https://myaccount.google.com/connections) 移除 Study Dock。
