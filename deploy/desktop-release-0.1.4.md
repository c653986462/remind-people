# 证事 0.1.4 发布

修复“立即检查”后提示不可见、页面底部短暂出现空白的问题，并补齐确认弹窗样式。
检查时显示加载状态，连续点击只提交一次请求；没有新增提醒或接口出错时正常显示消息。
本地开发页面已热更新；桌面端需从托盘退出旧版，再安装 `frontend/release/证事 Setup 0.1.4.exe`。

本次服务器更新只包含静态前端，不需要重启后端服务。

## 上传

在本机 PowerShell 运行：

```powershell
scp "C:\github\remind-people\deploy\packages\certificate-manager-desktop-release-0.1.4.tar.gz" "C:\github\remind-people\deploy\packages\certificate-manager-web-ui-0.1.4.tar.gz" ubuntu@124.221.168.72:/tmp/
```

## 发布

在服务器运行：

```bash
echo '140E63DD313CBF928F86A5DF97CF67EA52C17DA0C9EDDAF91684F9D4FC55B655  /tmp/certificate-manager-desktop-release-0.1.4.tar.gz' | sha256sum -c - &&
echo 'CCB45F42B96BD08BE09E8DD0DDC443A2E0D31074EB0E1CFED01D30C9F2FCE1CC  /tmp/certificate-manager-web-ui-0.1.4.tar.gz' | sha256sum -c - &&
publish_stage=$(mktemp -d /tmp/certificate-manager-release-0.1.4.XXXXXX) &&
mkdir "$publish_stage/release" "$publish_stage/web" &&
tar -xzf /tmp/certificate-manager-desktop-release-0.1.4.tar.gz -C "$publish_stage/release" &&
tar -xzf /tmp/certificate-manager-web-ui-0.1.4.tar.gz -C "$publish_stage/web" &&
publish_backup="/opt/certificate-manager-ui-backup-$(date +%Y%m%d-%H%M%S)" &&
sudo install -d -m 700 "$publish_backup" &&
sudo cp -a /opt/certificate-manager/frontend/dist "$publish_backup/" &&
if [[ -f /opt/certificate-manager/desktop-updates/latest.yml ]]; then sudo cp -a /opt/certificate-manager/desktop-updates/latest.yml "$publish_backup/"; fi &&
sudo install -d -o root -g www-data -m 755 /opt/certificate-manager/desktop-updates &&
sudo cp -a "$publish_stage/web/frontend/dist/." /opt/certificate-manager/frontend/dist/ &&
sudo chown -R root:www-data /opt/certificate-manager/frontend/dist &&
sudo chmod -R u=rwX,g=rX,o=rX /opt/certificate-manager/frontend/dist &&
sudo install -o root -g www-data -m 644 "$publish_stage/release/证事 Setup 0.1.4.exe" "$publish_stage/release/证事 Setup 0.1.4.exe.blockmap" /opt/certificate-manager/desktop-updates/ &&
sudo install -o root -g www-data -m 644 "$publish_stage/release/latest.yml" /opt/certificate-manager/desktop-updates/.latest-0.1.4.yml.tmp &&
sudo mv -f /opt/certificate-manager/desktop-updates/.latest-0.1.4.yml.tmp /opt/certificate-manager/desktop-updates/latest.yml
```

旧前端及版本清单保存在上述 `/opt/certificate-manager-ui-backup-*` 目录。
官网会从新版本清单读取 0.1.4 的安装器。

检查入口：

```bash
curl --noproxy '*' -sS -o /dev/null -w '网页 HTTPS %{http_code}\n' https://124.221.168.72/
curl --noproxy '*' -sS https://124.221.168.72/desktop-updates/latest.yml
```

网页应返回 200，版本清单应为 `0.1.4`。刷新网页后再点“立即检查”，可看到正常的检查反馈。
