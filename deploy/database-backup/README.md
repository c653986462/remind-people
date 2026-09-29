# 数据库自动备份

适用于当前 Ubuntu 部署 `/opt/certificate-manager`，读取 `.env` 中的
`DATABASE_URL`。仅接受项目 `data` 目录内已有的 SQLite 文件；不支持 PostgreSQL、
内存数据库、SQLite URI 参数，也不会因路径错误创建一个空数据库。

## 安装及运行

将本目录完整上传、解压后执行 `sudo bash setup.sh`。安装器会先检查 systemd
配置，安装文件，立即生成并校验第一份备份，成功后开启定时任务。
不会重启或停止后端、Nginx，也不改账号、密码或 `.env`。

- 每天北京时间凌晨 03:00 运行；服务器错过执行时间后，开机补执行。
- 使用 SQLite 在线备份 API，包含已提交的 WAL 数据，不直接复制正在使用的文件。
- 完整性检查 `PRAGMA integrity_check`，生成数据库和附件包 SHA-256 清单；校验成功才发布备份。
- 同步打包附件目录并核对数据库内每条附件记录的文件名、大小和 SHA-256；数据库、PDF/图片作为一个备份集保存。
- 保留最近 30 天；仅在新备份成功后删除本工具产生的过期备份对。
- 目录 `/var/backups/certificate-manager`：root 所有、权限 0700；文件权限 0600。
- 备份不在网站目录中，也没有公开下载接口；其中包含账号哈希和业务数据，仍属敏感文件。
- 使用文件锁防止重复并发执行；备份超时或磁盘不足会返回失败并记录日志。

```bash
# 手动备份
sudo systemctl start certificate-manager-backup.service

# 下次执行时间及日志
sudo systemctl list-timers certificate-manager-backup.timer --no-pager
sudo journalctl -u certificate-manager-backup.service -n 50 --no-pager

# 列出备份（每份 SQLite 数据库、.attachments.tar.gz 附件包和同名 .json 校验清单）
sudo ls -lh /var/backups/certificate-manager

# 检查指定备份，不覆盖线上数据库；把文件名换成实际文件名
sudo /opt/certificate-manager/.venv/bin/python \
  /opt/certificate-manager/deploy/database-backup/backup.py \
  --verify /var/backups/certificate-manager/实际备份文件名.sqlite3
```

`oneshot` 服务成功后显示 `inactive (dead)` 是正常的；定时器应该为 `active (waiting)`。
失败可用上述日志查看。尚未配置失败消息推送；systemd 失败记录不会自动发到手机。

## 异地副本（尚未配置）

本方案只在服务器本机备份，无法防止整台服务器或磁盘丢失，也不能替代异地备份。
定期通过受保护的 SCP/SFTP 下载 `.sqlite3`、同名前缀的 `.attachments.tar.gz` 和配套 `.json` 到另一台设备，并对
保存设备启用磁盘加密。不需要、也不要把备份目录权限改成所有人可读。
自动上传到云存储需另行确定目标账号、存储桶、加密及访问策略；当前没有上传到外部服务。

## 恢复说明

恢复会覆盖当前业务数据，不由定时任务自动执行。先确定具体备份文件与恢复时间点，
使用 `--verify` 同时校验 SHA-256、文件大小和 SQLite 完整性，再做恢复演练。

正式恢复顺序：

1. 先手动生成一份当前数据库备份，并确认成功。
2. 暂停备份定时器，停止 `certificate-manager` 服务，确认没有其他进程写入数据库。
3. 保留原数据库及可能存在的 `-wal`、`-shm` 文件，移到受保护的回退目录。
   不能把旧 WAL/SHM 留在新数据库旁，也不能直接覆盖正在使用的数据库。
4. 将已验证的备份安装为 `.env` 指定的 SQLite 文件，所有者恢复为 `www-data:www-data`、
   权限 0600；不要把备份清单当成数据库。
5. 使用受保护的临时目录解出已校验附件包中的 `database.sqlite3` 和 `attachments/`，
   恢复附件到 `data/attachments/`；确认目录归 `www-data:www-data` 所有且仅服务可读写。
6. 启动服务，验证登录、人员、证书、持证记录、附件预览和提醒，再恢复定时器。

备份包括登录会话表。若恢复点曾存在已撤销的会话，恢复后可能重新出现，应按项目
账号管理流程撤销所有旧会话。恢复当天之后新增的数据不会自动合并。

本地测试涵盖在线 WAL 快照、校验失败、路径保护、保留策略、锁和恢复到临时数据库。
真实服务器首次备份、systemd 定时器与磁盘权限由安装器现场验证。

参考：[SQLite 在线备份 API](https://www.sqlite.org/backup.html)。
