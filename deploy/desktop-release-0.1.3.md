# 证事 0.1.3 发布

本版去掉 File / Edit / View / Window 菜单栏，登录页只需账号和密码。
客户端和自动更新均直接连接 `https://124.221.168.72`。
旧版本保存的服务地址会被忽略，开机启动选择继续保留。
本次不需要更新或重启后端服务。

本机先从托盘退出旧客户端，再运行 `frontend/release/证事 Setup 0.1.3.exe` 安装新版。

## 上传官网及客户端更新

在 Windows PowerShell 运行：

```powershell
scp "C:\github\remind-people\deploy\packages\certificate-manager-desktop-release-0.1.3.tar.gz" "C:\github\remind-people\deploy\packages\certificate-manager-download-site-0.1.3.tar.gz" ubuntu@124.221.168.72:/tmp/
```

然后在服务器运行：

```bash
echo 'DD5FBB402774219A26E21DF5DEF7846BF08FC6808F76A8006A0F394B814D38C3  /tmp/certificate-manager-desktop-release-0.1.3.tar.gz' | sha256sum -c - &&
echo 'B9393F927F7F39460766A63612AA30A349FDCB26DEC6E888CEB7F3B6F0AF06E4  /tmp/certificate-manager-download-site-0.1.3.tar.gz' | sha256sum -c - &&
publish_stage=$(mktemp -d /tmp/certificate-manager-release-0.1.3.XXXXXX) &&
mkdir "$publish_stage/release" "$publish_stage/site" &&
tar -xzf /tmp/certificate-manager-desktop-release-0.1.3.tar.gz -C "$publish_stage/release" &&
tar -xzf /tmp/certificate-manager-download-site-0.1.3.tar.gz -C "$publish_stage/site" &&
publish_backup="/opt/certificate-manager-desktop-publish-backup-$(date +%Y%m%d-%H%M%S)" &&
sudo install -d -m 700 "$publish_backup" &&
if [[ -d /opt/certificate-manager/frontend/dist/download ]]; then sudo cp -a /opt/certificate-manager/frontend/dist/download "$publish_backup/"; fi &&
if [[ -f /opt/certificate-manager/desktop-updates/latest.yml ]]; then sudo cp -a /opt/certificate-manager/desktop-updates/latest.yml "$publish_backup/"; fi &&
sudo install -d -o root -g www-data -m 755 /opt/certificate-manager/desktop-updates /opt/certificate-manager/frontend/dist/download &&
sudo install -o root -g www-data -m 644 "$publish_stage/release/证事 Setup 0.1.3.exe" "$publish_stage/release/证事 Setup 0.1.3.exe.blockmap" /opt/certificate-manager/desktop-updates/ &&
sudo install -o root -g www-data -m 644 "$publish_stage/site/download/index.html" "$publish_stage/site/download/download.css" "$publish_stage/site/download/download.js" /opt/certificate-manager/frontend/dist/download/ &&
sudo install -o root -g www-data -m 644 "$publish_stage/release/latest.yml" /opt/certificate-manager/desktop-updates/.latest-0.1.3.yml.tmp &&
sudo mv -f /opt/certificate-manager/desktop-updates/.latest-0.1.3.yml.tmp /opt/certificate-manager/desktop-updates/latest.yml
```

安装器和差分文件先写入，版本清单最后替换，官网会读取新版本。
官网旧文件备份保存在上述 `/opt/certificate-manager-desktop-publish-backup-*` 目录。

检查服务器入口：

```bash
curl --noproxy '*' -sS -o /dev/null -w '官网 HTTPS %{http_code}\n' https://124.221.168.72/download/
curl --noproxy '*' -sS https://124.221.168.72/desktop-updates/latest.yml
```

官网应返回 200，清单中的 `version` 应为 `0.1.3`。
