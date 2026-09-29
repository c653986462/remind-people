# 统一完整发布

每次更新统一发布后端、网页、下载官网、桌面 EXE 和更新清单。服务器发布成功不代表用户电脑已安装新版：客户端仍需接受更新或下载安装器。
包内不包含 `.env`、数据库、上传附件和本地账号；发件邮箱配置保留在服务器。

## 后续版本打包

先提升 `frontend/package.json` 版本号，然后在项目根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File deploy/build-full-release.ps1
```

默认构建网页和 EXE，再生成单一完整包及 SHA256。缺少任何端的产物、校验不通过、版本包已存在时停止。
`-SkipBuild` 只用于复用已验证与源码一致的构建，不适用于常规新版本。
后端 Python 依赖必须满足新包的 requirements.txt；本次 0.1.4 不新增依赖。

## 当前 0.1.4：上传

在本机 Windows PowerShell 执行：

```powershell
scp "C:\github\remind-people\deploy\packages\certificate-manager-full-0.1.4.tar.gz" ubuntu@124.221.168.72:/tmp/
```

## 当前 0.1.4：服务器安装

```bash
echo 'EB58FBAF65B13943A5AA3E1FABAFD7F794DD358A6DBF88887D21710CE0934E86  /tmp/certificate-manager-full-0.1.4.tar.gz' | sha256sum -c - &&
full_release_stage=$(mktemp -d /tmp/certificate-manager-full-release.XXXXXX) &&
tar -xzf /tmp/certificate-manager-full-0.1.4.tar.gz -C "$full_release_stage" &&
sudo bash "$full_release_stage/deploy/setup-full-update.sh" "$full_release_stage"
```

脚本先验证逐文件 SHA256 和安装器 SHA512、大小及版本；禁止桌面版本降级，同版本不同安装器也停止发布。
保留旧版本 EXE、数据库和附件，复用在线 SQLite 备份及代码回滚机制。
安装器先放到更新目录，后端健康检查成功后才原子替换 latest.yml，官网同步读取新版清单。
后端启动失败会恢复旧代码；旧桌面更新清单在成功前保持不变。
代码备份位置由脚本输出，旧版本清单保存在 `/opt/certificate-manager-full-release-backup-*`。

## 验证

```bash
curl --noproxy '*' -sS -o /dev/null -w '网页 HTTPS %{http_code}\n' https://124.221.168.72/
curl --noproxy '*' -sS https://124.221.168.72/desktop-updates/latest.yml
curl --noproxy '*' -sS -I 'https://124.221.168.72/desktop-updates/%E8%AF%81%E4%BA%8B%20Setup%200.1.4.exe'
```

网页和安装器应返回 200，版本清单应显示 0.1.4。
打开 `/download/` 官网下载安装器；或在已支持更新检查的客户端内检查更新并确认安装。
