# 宿主机 nftables 黑名单同步

`v0.8.4-mgma.5` 及后续版本在应用层黑名单之外提供一个独立的宿主机 systemd 服务。应用仍负责识别失败登录/注册、生成原因、期限和审计；宿主机进程只读 SQLite，把当前有效的 `portal_ip_blocks` 定时同步到 nftables。

## 1. 数据与执行边界

- SQLite 是唯一事实来源，nftables 是可重建的派生状态，不单独备份。
- 默认每 15 秒读取一次 `portal_ip_blocks`，仅选择 `is_active=1` 且未过期的条目。
- IPv4/IPv6 分别写入 `inet marzban_portal_guard` 的 `blocked_v4`、`blocked_v6` interval set；重叠/相邻 CIDR 在写入前折叠。
- nft set **不使用 timeout**。临时条目到期后，由下一次数据库同步从集合删除。
- 两个 set 在同一个 `nft -f` 事务中先 flush、再填充，不存在一半 IPv4 已更新而 IPv6 未更新的中间状态。
- 数据库不可读、包含非法网段/时间，或 nft 事务失败时，服务保留上一次成功策略并等待下次重试，绝不先清空集合。
- 应用容器不获得 `CAP_NET_ADMIN`、Docker socket 或宿主机 root 权限；只有受 systemd 限制的同步进程拥有 `CAP_NET_ADMIN`。

默认规则只丢弃黑名单来源到宿主机 TCP `443` 的数据包，并显式放行 loopback。它是真正的网络层丢弃，会覆盖该宿主机 `443` 上的所有 Nginx vhost，无法按域名区分。若同机还承载其他 HTTPS 站点，应先评估这一影响或给面板使用独立公网 IP/端口。

应用层封禁仍立即生效；网络层最多在一个同步周期后生效。网络层命中后，已有浏览器 sudo 会话也无法从该来源访问 `443`，误封恢复必须依赖 SSH 或其他不经过受保护端口的管理通道。

## 2. 安装与配置

仓库文件：

- `scripts/portal_ip_guard.py`
- `scripts/install_portal_ip_guard.sh`
- `scripts/uninstall_portal_ip_guard.sh`
- `systemd/marzban-portal-ip-guard.service`

默认配置写入 `/etc/default/marzban-portal-ip-guard`：

```text
DATABASE_PATH=/root/marzban/data/db.sqlite3
PANEL_PORT=443
SYNC_INTERVAL=15
```

安装并注册开机启动：

```bash
cd /root/marzban
sudo ./scripts/install_portal_ip_guard.sh
```

迁移到不同目录或端口时，可以在安装命令前传递 `DATABASE_PATH`、`PANEL_PORT`、`SYNC_INTERVAL`。安装器复制 root-only 可执行文件、安装 unit、写入配置并执行 `systemctl enable --now`。

## 3. 日常检查

```bash
systemctl status marzban-portal-ip-guard.service --no-pager
journalctl -u marzban-portal-ip-guard.service -n 50 --no-pager
nft list table inet marzban_portal_guard
```

服务只记录同步后的 IPv4/IPv6 条目数量，不打印具体 IP、原因或数据库内容。原因、来源、创建/解除人和期限仍在管理员页面与 SQLite 中查看。

安全验收可使用文档保留地址创建一条手工黑名单，等待一个同步周期，确认其出现在 nft set 后立即从页面解除，再确认下一周期将其删除。不要用当前 SSH/浏览器管理出口做生产封禁测试。

## 4. 停止、卸载与故障语义

单独执行 `systemctl stop marzban-portal-ip-guard` 只停止同步，保留最后一次 nft 策略，避免进程崩溃或临时维护自动解除所有封禁。

完整卸载：

```bash
cd /root/marzban
sudo ./scripts/uninstall_portal_ip_guard.sh
```

卸载器会依次停止并禁用 service、删除专用 nftables table、删除 unit/配置/可执行文件并 reload systemd。它不会修改 SQLite 黑名单；以后重新安装时，服务会从数据库重建网络策略。

不要使用 `nft flush ruleset`，也不要让卸载脚本删除专用表以外的防火墙对象。若回滚到不包含 `portal_ip_blocks` 的旧数据库，应先运行卸载脚本，再切换数据库和镜像。
