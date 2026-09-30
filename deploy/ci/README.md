# GitHub Actions 自动构建和部署

推送 `main` → 后端测试 → 构建网页小包 → 上传 → 数据库备份 → 更新非活动实例 → 健康检查 → Nginx 平滑切流。Electron 外壳变化时，另一条独立分支构建并发布 EXE；普通网页更新不会更新桌面版本。网页发布不等待桌面构建或上传成功。
Pull Request 只测试和构建，不读取部署密钥、不更新生产。
网页发布和桌面发布各自串行；长时间桌面上传不会占用网页发布队列。服务器实际切流/公告操作仍共享发布锁。蓝绿模式下两套 Web/API 实例轮流更新，旧实例在切换后保留作回退；单独的后台调度进程避免重复发送提醒。桌面发布只原子更新安装器和清单，不重新启动网页/API/调度服务。用户电脑自动下载新版本，但仍需确认重启/安装。

## 当前状态

工作流为 `.github/workflows/release.yml`，默认自动部署关闭。
本地已生成专用 SSH 密钥 `.ci-keys/github-actions` 及公钥 `.ci-keys/github-actions.pub`。
该目录已加入 Git 忽略规则，限制为当前 Windows 用户和 SYSTEM 可访问；私钥不打印、不上传 Git 仓库。
不要把私钥或 SMTP 授权码发到聊天、日志或仓库中。

## 1. 上传一次性接入包和公钥

在本机 Windows PowerShell 执行：

```powershell
scp "C:\github\remind-people\deploy\packages\certificate-manager-ci-setup-20260929.tar.gz" "C:\github\remind-people\.ci-keys\github-actions.pub" ubuntu@124.221.168.72:/tmp/
```

只传 `.pub` 公钥，绝不能把不带 `.pub` 的私钥传到服务器。

在服务器执行：

```bash
echo 'ADE53E49C2E9BB46DE6E91EA18E00C0A70F3726EA67DD320C095380F3766ABE9  /tmp/certificate-manager-ci-setup-20260929.tar.gz' | sha256sum -c - &&
ci_setup_stage=$(mktemp -d /tmp/certificate-manager-ci-setup.XXXXXX) &&
tar -xzf /tmp/certificate-manager-ci-setup-20260929.tar.gz -C "$ci_setup_stage" &&
sudo bash "$ci_setup_stage/deploy/ci/setup-server.sh" /tmp/github-actions.pub
```

会创建专用 `certmgr-deploy` 账号和受限 sudo 入口。该账号不能任意 sudo；只允许校验并安装指定目录中的发布包。
上传包内的 shell/Python 部署脚本不会以 root 执行：执行工具来自管理员预先安装的 root-owned 目录。
服务器输出一行 `124.221.168.72 ssh-ed25519 ...`，留给下一步的 `DEPLOY_KNOWN_HOSTS`。
这一步不重启业务服务、不修改 `.env`、数据库或附件。
仅当可信部署工具本身需升级时，管理员再安装新的接入包；日常业务更新不需要重复设置。蓝绿模式首次启用步骤见下文。

## 2. GitHub 一次性设置

打开仓库 Settings → Secrets and variables → Actions → Secrets，添加 Repository secrets：

| 名称 | 内容 |
| --- | --- |
| `DEPLOY_HOST` | `124.221.168.72` |
| `DEPLOY_USER` | `certmgr-deploy` |
| `DEPLOY_PORT` | `22`（也可不设置，默认 22） |
| `DEPLOY_SSH_KEY` | 本地 `.ci-keys/github-actions` 私钥的完整内容，含 BEGIN/END 行 |
| `DEPLOY_KNOWN_HOSTS` | 上一步服务器输出的完整 known-host 行 |

不要填服务器登录密码或邮箱授权码。流水线只需要部署密钥，SMTP 继续只保存在服务器 `.env`。
建议直接从本地文件复制私钥到 GitHub Secrets，不在终端打印或截图。
若使用非 22 端口，known-host 行的主机名要改为 `[124.221.168.72]:端口`。

再到同页面 Variables，添加 Repository variable：

| 名称 | 内容 |
| --- | --- |
| `DEPLOY_ENABLED` | `true`，设置此项才允许自动更新线上 |
| `DEPLOY_PUBLIC_URL` | `https://124.221.168.72`，可不设置，默认此地址 |
| `DEPLOY_SERVER_ONLY` | `true`（新工作流默认值），普通网页/后端提交只部署小包；明确设成 `false` 才强制每次构建 EXE。先升级服务器可信发布工具 |

`DEPLOY_ENABLED` 必须是 Repository variable，不能只放在环境变量或 Secrets 中。
部署 job 使用 `production` 环境；若给该环境设置了人工审核，发布会等待审核。想完全自动则不要设置 required reviewers。
建议保护 `main`，仅可信维护者可推送；SSH 必须对 GitHub 托管 Runner 可达。

## 3. 首次触发及以后使用

配置完成并升级服务器可信工具后，打开仓库 Actions → Test, build and deploy all components → Run workflow，选择 main。默认只更新网页/后端；勾选 `Also build and publish a new Windows installer` 才强制重打包桌面端。
推送包含桌面壳改动时会构建新版 EXE，安装后客户端即加载服务器上的网页。改网页或后端并推送 `main` 只部署小包；修改 `frontend/electron/`、Electron 配置、桌面依赖时才重打包 EXE。不要重新运行旧版第 6 次工作流，旧工作流不具备新分离流程，而且包版本可能低于当前线上。

```powershell
git add .
git commit -m "描述这次修改"
git push origin main
```

桌面版本自动使用 `frontend/package.json` 中的基础版本，加上本工作流的 run number；仅构建桌面 EXE 时递增发布版本。
例如基础版本 `0.1.4`，run #1 → `0.1.5`，run #2 → `0.1.6`；PR、失败运行也会占用编号，版本允许跳号。
不自动提交版本号回 Git，以免再次触发流水线。本地 package.json 是基础版本，线上实际版本看 latest.yml/release.json。
不要降低基础版本，不要重建同一个已发布版本覆盖安装器。已有版本部署失败时优先使用 Re-run failed jobs 复用原构建包；若要全部重建，使用 Run workflow 取得新编号。

## 校验、失败和限制

- 本次无需新增服务器 Python 依赖；以后新依赖缺失或版本不满足时，会在修改线上代码前停止，管理员需先准备新依赖。不会把上传包中的任意构建钩子作为 root 执行。
- 候选后端启动或健康检查失败时不会切流；切流失败会恢复旧流量。旧实例留作快速回退；健康检查前不发布桌面新清单。数据库新增表属于加法变更，破坏性迁移需要单独规划。
- SSH 使用预先核实的 known_hosts，绝不关闭主机指纹校验；密钥不会发给 PR 构建。
- 全部产物通过 GitHub Actions Artifact 保存 14 天，历史安装器保留在服务器。构建消耗 Actions 配额，以 GitHub 账号实际额度为准。
- Windows 安装包约 120 MB，GitHub 托管 Runner 到国内服务器的上传可能很慢。网页 job 上限 30 分钟，单次上传 3 分钟最多重试 3 次；桌面 job 上限 270 分钟，备用 SSH 单次上传 70 分钟最多重试 3 次。两者均检查 SSH 身份/固定指纹，使用 rsync 校验式断点续传和 120 秒无数据超时。失败后 Re-run failed jobs 复用相同 artifact 和远端路径续传；不完整上传绝不调用服务器发布入口。网页使用 `release-运行ID-1.tar.gz`，桌面使用 `release-运行ID-2.tar.gz`，互不覆盖。
- 桌面包优先由服务器通过 HTTPS 并行拉取 GitHub Artifact（16 个校验范围、每次最多 10 分钟，最多 3 次续传），同时核验 GitHub ZIP 摘要和 Runner 发布包摘要，再原子放入暂存路径。超时保留分段字节，新的临时链接只补齐缺失范围；完整成功后清理缓存，失败缓存不包含链接或凭据。跨境网络仍可能不稳定；失败自动退回上述 SSH 续传。下载以 `certmgr-deploy` 身份运行，不增加 sudo 权限；临时下载链接通过 SSH 标准输入传递，不进入日志/命令参数，GitHub API token 只留在 Runner。桌面发布 job 仅增加 `actions: read` 读取构建产物的权限。此优化不需要再次升级服务器 root 工具。
- 桌面发布必须对应当前活动的服务器 `source_commit` 和 `run_id`；若较新网页版本已上线，旧任务不可发布过时桌面清单。服务器拒绝较旧 CI run number；桌面禁止版本降级、同版本不同安装器。公网 `/deployment.json` 用来验证实际部署的提交和运行 ID，不包含任何凭据。
- 当前 EXE 未配置代码签名证书，Windows 仍可能提示未知发布者。设置 CI/CD 不会自动获得代码签名。

## 启用服务器专用更新

包含 Electron 远程网页加载的首次全量更新完成后，在本地 PowerShell 运行 `deploy/ci/build-tools-update.ps1`，把生成的工具更新包和 `.sha256` 通过 SCP 上传到服务器 `/tmp`。在服务器校验哈希、解压后，先执行包内的 `deploy/ci/update-server-tools.sh` 安装 root-owned 发布工具，再执行 `deploy/ci/setup-blue-green.sh` 一次性迁移 Nginx。它会备份站点配置、启动 8001/8002 两个候选实例、检查健康状态，然后平滑切到 8001；旧的 8000 调度服务仍只负责提醒，不承接网页流量。验证网页、登录/API 和邮件调度正常后，才在 GitHub 设置 `DEPLOY_SERVER_ONLY=true` 并继续推送代码。

工具升级包只需生成一次。PowerShell 示例：
已有蓝绿服务器升级到分离发布时，仅运行工具包内 `update-server-tools.sh`，不再运行初始化或旧包修复脚本。升级只安装 root-owned 校验器/发布器和受限入口，不更改 sudo 范围、不重启服务、不触碰 `.env` 或数据。需管理员执行一次后，才推送新工作流。新增 `publish-desktop.sh` 专门负责无重启的桌面公告；旧两参数全量入口仍兼容管理员手动发布。

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\ci\build-tools-update.ps1
```

上传后在服务器示例（把文件名和 SHA256 替换成实际输出）：

```bash
echo '实际SHA256  /tmp/certificate-manager-ci-tools-update-时间.tar.gz' | sha256sum -c - &&
stage=$(mktemp -d /tmp/certificate-manager-tools.XXXXXX) &&
tar -xzf /tmp/certificate-manager-ci-tools-update-时间.tar.gz -C "$stage" &&
sudo bash "$stage/deploy/ci/update-server-tools.sh" "$stage" &&
sudo bash "$stage/deploy/ci/setup-blue-green.sh"
```

一次性初始化会短暂执行 Nginx graceful reload；正常更新不重启 Nginx，也不重启正在服务用户的 API 实例。数据库保持 SQLite 单机写入模型；所有槽位共享同一份数据库和附件。应用发布应继续采用向后兼容的加法式数据库变更。

API 和调度服务都显式通过 Uvicorn `--app-dir` 选择槽位/当前版本，避免固定工作目录中的旧 `app` 覆盖版本目录。初始化还会检查旧版生命周期并仅对旧版启动调度代码补上 `SCHEDULER_ENABLED` 判断；检查不认识的布局时直接停止。这样首次复制旧程序也不会启动多份调度器。

如果已经安装过 `20260930-140020` 初始化包，需上传最新工具包，执行 `update-server-tools.sh` 后再执行同包的 `repair-blue-green.sh`；不要再次运行初始迁移。修复先重启备用槽位，检查后切流，再等原槽位请求结束并修复它，8000 调度进程继续运行。
如果发布后发现业务问题，可在服务器执行 `sudo /usr/local/lib/certificate-manager-ci/blue-green-rollback.sh`，切回保留的上一槽位；成功/失败日志查看 `journalctl -u nginx -u 'certificate-manager@*' -u certificate-manager --since today`。

查看日志：仓库 Actions 页面；服务器 `journalctl -t certificate-manager-ci --no-pager` 和 `journalctl -u certificate-manager --no-pager`。
流水线设置依据 [GitHub Actions 工作流规范](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)。
