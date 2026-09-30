# 个人证书管理系统

实现人员、证书、人员证书关系管理，分别记录更新、延期、继续教育日期及对应办理网址；发证日期仅用于记录，不触发提醒。

## 已实现

- 人员、证书、持证记录的新增、查询、编辑接口与删除接口
- 持证记录详情及附件：每条记录最多上传 9 个 PDF 和 9 张图片，附件仅存储在服务器私有目录，并随记录级联删除；附件也随每日数据库备份打包与校验
- 按人员、证书或证书编号搜索
- 三类提醒事项：更新、延期、继续教育；发证日期不触发提醒
- 每天 `CHECK_HOUR` 检查提前提醒；企业微信另在事项日期当天 `WECHAT_DUE_REMINDER_HOUR`（北京时间，默认 08:00）发送一次
- 去重提醒日志，避免同一事项重复发送
- 用户可在程序内绑定并验证接收邮箱；邮件包含持证人、证书、事项日期和办理入口，验证码和测试邮件用于确认邮箱及发信配置
- 企业微信机器人 Webhook 推送；未配置时仍会生成提醒日志
- Vue 3 + Element Plus 前端：统一的扁平化界面，总览列表/日历切换、人员/证书/持证记录增删改、办理地址、浏览器桌面提醒
- Windows Electron 桌面客户端：本机安全代理连接服务端、系统托盘常驻；事项日期当天 09:00 起在屏幕右下角置顶提醒，每 30 分钟重复，支持稍后提醒和永久关闭该日期事项；另有开机启动选项、客户端版本检查与 NSIS 安装包自动更新
- 登录后通过 FastAPI Cookie 会话访问实际数据；无公开注册、密码修改、退出、CSRF 防护与登录失败限流
- Argon2id 密码哈希、HttpOnly + SameSite 会话 Cookie、Trusted Host 校验及安全响应头

## 本地启动

PowerShell：

```powershell
Copy-Item .env.example .env
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.admin initialize-superadmin
uvicorn app.main:app --reload --port 8000
```

另开一个终端：

```powershell
cd frontend
npm install
npm run dev
```

首次初始化时运行 `python -m app.admin initialize-superadmin`，按提示设置初始管理员密码；此命令只适用于空数据库或仅有默认 `admin` 账户的情形，并且仅这次初始化不执行常规密码长度检查。默认初始化账号为 `wangxueqin`。后续创建管理员仍通过 `python -m app.admin create-admin`，密码至少 14 位；修改密码也要求至少 14 位。然后打开 `http://localhost:5173` 登录。本地开发环境的接口文档在 `http://localhost:8000/docs`。`.env.example` 的 Cookie/Host 设置仅用于本地 HTTP 开发，生产环境不可照搬。

### Windows 桌面开发与打包

安装包使用 Electron + electron-builder 的 NSIS `.exe` 格式。桌面端自动连接 `https://124.221.168.72`，登录只需填写账号和密码。服务地址统一配置在 `frontend/electron/runtime-config.cjs`，旧客户端保存的地址不会覆盖官方地址。窗口保留系统标题栏，移除 Electron 默认菜单栏。点窗口关闭按钮会隐藏到系统托盘；右键托盘图标可打开、检查更新、控制开机启动或彻底退出。程序登录且运行时每 10 分钟刷新提醒；完全退出、电脑关机或网络不可用时不能提醒。桌面端事项弹窗按北京时间判断；用户点击“稍后提醒”后 30 分钟再提示，点击“关闭”则只关闭该记录、事项类型和日期对应的提醒。登录会话默认 12 小时过期；过期后会通知用户重新登录，提醒随之暂停。

在 `frontend` 目录安装依赖并运行桌面开发版：

```powershell
pnpm install
pnpm desktop:dev
```

### 发布桌面更新

Electron 自动更新使用自有 HTTPS 静态目录。先将 `deploy/desktop-updates.nginx.conf` 的 location 加入网站 HTTPS `server {}`，并创建 `/opt/certificate-manager/desktop-updates` 目录。发布机器在 Windows 上构建安装包，版本号必须先提高 `frontend/package.json` 的 `version`（语义化版本，例如 `0.1.3`）；默认更新地址为 `https://124.221.168.72/desktop-updates/`，直接构建即可：

```powershell
cd frontend
pnpm install
pnpm desktop:build
```

构建会在 `frontend/release` 生成 `.exe`、`latest.yml` 和可能的 `.blockmap` 文件。把它们上传到服务器 `desktop-updates` 目录，**最后上传 `latest.yml`**，避免客户端读到尚未上传完整的版本清单。客户端启动时以及每 6 小时检查一次，发现更新后自动下载并询问立即重启或稍后安装；托盘菜单也可手动检查。特殊构建可通过环境变量 `DESKTOP_UPDATE_URL` 覆盖更新地址；正常发布使用内置的官方地址。

要启用自动安装更新，发布版本需要使用同一张 Windows Authenticode 代码签名证书签名；electron-updater 会拒绝签名不匹配或未签名的更新包。将证书路径及密码安全地设为构建机环境变量 `WIN_CSC_LINK`、`WIN_CSC_KEY_PASSWORD`，不要把证书或密码放入仓库、更新目录或提交记录。没有证书时可以生成用于内测的初始安装包，但更新校验不会允许安装未签名更新，Windows SmartScreen 也可能显示未知发布者。服务器实际文件部署与公网访问尚需在你的服务器上完成。

前端默认连接 FastAPI 实际数据：浏览器请求同源 `/api`，Vite 开发服务器将请求转发到 `http://127.0.0.1:8000`。生产部署也应由 Nginx 将 `/api/` 转发给后端，避免浏览器直接跨端口访问。若后端地址不同，可在 `frontend/.env.local` 配置 `VITE_API_PROXY_TARGET`（开发环境）或 `VITE_API_URL`（浏览器可访问的 API 地址）。如果只想离线看演示，设置 `VITE_USE_MOCK=true`；可参考 [frontend/.env.example](frontend/.env.example)。后端保存到 `data/certificates.db`，该目录应由运行服务的账户持有并可写。

生产部署时，首次用 `python -m app.admin initialize-superadmin` 初始化唯一管理员；确认能登录后再设置 `SESSION_COOKIE_SECURE=true`、`ALLOWED_HOSTS=你的域名`，并启用 HTTPS。不要将管理员密码放进源码或公开仓库。初始管理员命令仅是受控的一次性初始化例外，后续密码必须至少 14 位。当前系统所有管理员权限相同，尚未建立细分角色。会话 Cookie 为 `Secure`、`HttpOnly`、`SameSite=Strict`，12 小时过期；CSRF Token 按会话生成并在重新验证身份时轮换。无自助注册；忘记密码时可在服务器运行 `python -m app.admin reset-password 用户名`，已有会话会同时撤销。失败与限流登录事件会写入 systemd journal，不记录密码或会话 token。生产同源代理无需开启 CORS；如果单独暴露 API，只把自己的完整前端来源列入 `CORS_ORIGINS`。默认 SQLite 适合单机、单 worker；切换 PostgreSQL 等数据库时还需安装对应驱动。

## 微信提醒

在企业微信的群聊中添加“群机器人”，将机器人 Webhook URL 配置到服务器 `.env` 的 `WECHAT_WORK_WEBHOOK_URL`。后端保留按 `remind_days` 发送的一次提前提醒，并另在每个事项日期当天北京时间 `WECHAT_DUE_REMINDER_HOUR`（默认 08:00）推送一次；如果后端在 08:00 后才启动，会补发当天尚未成功发送的消息。修改 `.env` 后需重启后端。个人微信没有适用于任意消息推送的官方接口，企业微信机器人是稳定、合规的手机微信通知渠道。Webhook URL 是密钥，不要发到聊天、截图或仓库里。

## 邮箱提醒

在服务器 `.env` 配置 SMTP 发件邮箱后重启服务。常用邮箱需先在邮箱安全设置中开启 SMTP 并生成客户端授权码/应用专用密码；不要把邮箱登录密码放进客户端或发给其他人。SSL 常用端口为 `465`，STARTTLS 常用端口为 `587`，具体以邮箱服务商设置为准。用户登录后点顶部“邮箱提醒”，填写收件地址、输入收到的 6 位验证码即可绑定；验证码 10 分钟有效，每账号最多每天 5 次。绑定后发送一封测试邮件以确认设置。

邮件按每账号分别投递：首次进入记录设定的提前提醒天数时发送一封汇总邮件；事项当天另在 `WECHAT_DUE_REMINDER_HOUR`（默认北京时间 08:00）发送一次。发送失败会在下一个定时检查周期重试，成功后按账号、记录、事项、日期去重。当前持证记录是系统共享数据，因此所有已验证的绑定邮箱都会收到这些系统提醒。

SMTP 配置项：`EMAIL_SMTP_HOST`、`EMAIL_SMTP_PORT`、`EMAIL_SMTP_USERNAME`、`EMAIL_SMTP_PASSWORD`、`EMAIL_SMTP_FROM`、`EMAIL_SMTP_USE_SSL` 和 `EMAIL_SMTP_STARTTLS`。SMTP 密码只保存在服务器 `.env`，接口不会返回该值。

## 部署提醒

### 网页与桌面分离发布（默认流程）

已提供 GitHub Actions CI/CD：推送 `main` 后自动测试并构建网页/后端小包，
配置一次部署密钥、升级可信工具并启用 `DEPLOY_ENABLED=true` 后自动蓝绿更新线上。
只有 Electron 外壳/依赖变动时，独立构建并上传 EXE，桌面版本随 workflow run number 自动递增。
网页发布不等待桌面上传，桌面公告不重启服务；PR 不部署，更新清单在校验匹配网页版本后原子发布。
首次服务器接入和 GitHub Secrets 设置见 [CI/CD 接入说明](deploy/ci/README.md)。
未完成接入时，自动测试和构建照常运行，部署 job 跳过；以下手工打包作为备用流程。

普通网页和后端更新自动只发布小包，已安装的新桌面端直接展示最新线上网页。
只有 Electron 外壳变更或 Run workflow 勾选桌面选项时才构建新 EXE。需要手动全量打包时，
先提升 `frontend/package.json` 的版本号，再在项目根目录执行
`powershell -ExecutionPolicy Bypass -File deploy/build-full-release.ps1`。
脚本默认重新构建网页和 EXE，生成单一 `deploy/packages/certificate-manager-full-版本.tar.gz`；
缺少任何组件会停止打包，不包含 `.env`、数据库或证书附件。
`-SkipBuild` 仅用于复用已验证、与源码一致的安装器，不用于常规新版本发布。

首次使用需先按 CI/CD 说明安装蓝绿工具并做一次 Nginx 平滑迁移。此后每次发布会先更新非活动 Web/API 槽位并健康检查，再让 Nginx graceful reload 到新槽位；旧槽位保留作回退。唯一的提醒调度进程单独重启，不承接网页流量。安装器和校验文件先准备，
蓝绿切换及健康检查成功后才发布最新桌面版本清单；官网同步读取该清单。
服务器原有 SMTP 配置和业务数据保留。客户端用户需要接受/安装更新，发布并不等于所有电脑已升级。
具体操作见 [完整发布说明](deploy/full-release.md)。

### 数据库自动备份

Ubuntu 部署可使用 `deploy/database-backup/setup.sh` 安装数据库备份服务：每天
北京时间凌晨 03:00 在线备份 SQLite，保留最近 30 天。每份备份均做完整性和
SHA-256 校验，存放在 root 私有的 `/var/backups/certificate-manager`；首次安装
会立即备份并验证，不停止后端或 Nginx。安装、日志和恢复说明见
[数据库备份说明](deploy/database-backup/README.md)。这是本机备份，尚未配置异地
自动上传或失败推送，仍需额外保留受保护的异地副本。

### 公网服务

公网部署使用 Nginx 终止 HTTPS，Uvicorn 仅绑定回环地址；蓝绿启用后两个 Web/API 槽位分别监听 `127.0.0.1:8001` 和 `:8002`，单独的提醒调度服务监听 `:8000`。防火墙仍只开放 80/443。服务以单 worker 运行，并启用 systemd 文件系统隔离。首次建库前先把数据目录设为仅服务账户可访问，并以该服务账户创建管理员，避免 SQLite 数据库以宽松权限创建：

```bash
sudo install -d -o www-data -g www-data -m 0700 /opt/certificate-manager/data
sudo chown root:www-data /opt/certificate-manager/.env
sudo chmod 0640 /opt/certificate-manager/.env
sudo -u www-data -H /opt/certificate-manager/.venv/bin/python -m app.admin create-admin
```

`.env` 中配置真实 `ALLOWED_HOSTS`、`SESSION_COOKIE_SECURE=true`、提醒时间和 Webhook；不要将 `.env` 放入版本库。仓库已附带 `deploy/certificate-manager.service`，适用于工作目录为 `/opt/certificate-manager` 的 Ubuntu 部署：

SQLite 文件本身不加密；确保服务器磁盘/云盘加密，并设置异地加密备份与恢复演练。证书、联系方式和备注属于敏感业务数据，备份也应限制访问。

```bash
sudo cp deploy/certificate-manager.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now certificate-manager
sudo systemctl status certificate-manager
```

在 Nginx 的 `http {}` 中添加登录限速区：

```nginx
limit_req_zone $binary_remote_addr zone=certificate_login:10m rate=5r/m;
```

为域名配置有效 TLS 证书，并让 80 端口重定向至 HTTPS。站点的 HTTPS `server {}` 中将 `frontend/dist` 设为根目录，安全响应头与 `/api` 转发配置如下：

```nginx
root /opt/certificate-manager/frontend/dist;
index index.html;

add_header Strict-Transport-Security "max-age=31536000" always;
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "DENY" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'" always;

location / {
    try_files $uri $uri/ /index.html;
}

location = /api/auth/login {
    limit_req zone=certificate_login burst=5 nodelay;
    limit_req_status 429;
    proxy_pass http://127.0.0.1:8000/auth/login;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location /api/ {
    proxy_pass http://127.0.0.1:8000/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```
