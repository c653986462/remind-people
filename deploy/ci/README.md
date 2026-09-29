# GitHub Actions 自动构建和部署

默认流程：推送 `main` → Ubuntu/Windows 后端测试 → Windows 构建网页和 EXE → 完整包校验 → SSH 上传 → 数据库及代码备份 → 重启并健康检查 → 发布桌面更新清单。
Pull Request 只测试和构建，不读取部署密钥、不更新生产。
同一生产环境串行部署，发布清单最后写入。用户电脑自动下载新版本，但仍需确认重启/安装。

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
仅当可信部署工具本身需升级时，管理员再安装新的接入包；日常业务更新不需要重复设置。

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

`DEPLOY_ENABLED` 必须是 Repository variable，不能只放在环境变量或 Secrets 中。
部署 job 使用 `production` 环境；若给该环境设置了人工审核，发布会等待审核。想完全自动则不要设置 required reviewers。
建议保护 `main`，仅可信维护者可推送；SSH 必须对 GitHub 托管 Runner 可达。

## 3. 首次触发及以后使用

配置完成后，打开仓库 Actions → Test, build and deploy all components → Run workflow，选择 main。
日后修改代码并推送 main 即自动更新所有端，无需本地打包或 scp EXE。

```powershell
git add .
git commit -m "描述这次修改"
git push origin main
```

桌面版本自动使用 `frontend/package.json` 中的基础版本，加上本工作流的 run number。
例如基础版本 `0.1.4`，run #1 → `0.1.5`，run #2 → `0.1.6`；PR、失败运行也会占用编号，版本允许跳号。
不自动提交版本号回 Git，以免再次触发流水线。本地 package.json 是基础版本，线上实际版本看 latest.yml/release.json。
不要降低基础版本，不要重建同一个已发布版本覆盖安装器。已有版本部署失败时优先使用 Re-run failed jobs 复用原构建包；若要全部重建，使用 Run workflow 取得新编号。

## 校验、失败和限制

- 本次无需新增服务器 Python 依赖；以后新依赖缺失或版本不满足时，会在修改线上代码前停止，管理员需先准备新依赖。不会把上传包中的任意构建钩子作为 root 执行。
- 后端启动失败会恢复旧代码；健康检查前不发布桌面新清单。数据库新增表属于加法变更，破坏性迁移需要单独规划。
- SSH 使用预先核实的 known_hosts，绝不关闭主机指纹校验；密钥不会发给 PR 构建。
- 全部产物通过 GitHub Actions Artifact 保存 14 天，历史安装器保留在服务器。构建消耗 Actions 配额，以 GitHub 账号实际额度为准。
- Windows 安装包约 120 MB，GitHub 托管 Runner 到国内服务器的上传可能很慢。部署使用 rsync 断点续传，最长等待 90 分钟；失败后在 Actions 中选 Re-run failed jobs，可续传同一包。不要每次都重新触发全新工作流，否则会生成不同版本的安装包。
- 当前 EXE 未配置代码签名证书，Windows 仍可能提示未知发布者。设置 CI/CD 不会自动获得代码签名。

查看日志：仓库 Actions 页面；服务器 `journalctl -t certificate-manager-ci --no-pager` 和 `journalctl -u certificate-manager --no-pager`。
流水线设置依据 [GitHub Actions 工作流规范](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)。
