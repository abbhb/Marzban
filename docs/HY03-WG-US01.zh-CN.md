# HY 03 经 WireGuard 从美国 01 出口

面板主机 **🇺🇸 HY 03 → 🇺🇸 01** 是独立的 Hysteria 2 入站 `US03_HY2_WG_US01`。客户端连接 US03 的 `23.246.155.106:22445/udp`，US03 的专用 Xray 进程通过 WireGuard 把数据送到美国 01，目标网站看到美国 01 的 IPv4 `54.215.234.191`。它不使用客户端 `dialer-proxy`，也不依赖订阅里的其他节点。

独立 Xray 进程由面板节点 **美国 03 · WG 至美国 01** 管理，沿用现有用户的 Hysteria 凭据、流量统计与套餐授权。首次配置只向原来能使用 HY03 和美国 01 的套餐添加该入口；其他套餐不会自动获得权限。原 HY03 直连、HY03 IPv6 优先和 US02 不经过此 WireGuard 出口。

## 隧道与防泄漏

- US03 的 `wg-us01` 地址是 `10.66.66.5/32`；US01 使用现有 `wg0`，监听 `42371/udp`，只新增此 peer。US01 原有的 `10.66.66.0/24` 转发和公网 NAT 沿用。
- 美国 01 的云安全组及主机防火墙只对 `23.246.155.106/32` 放行新 peer 所需的 UDP 流量。US03 防火墙开放独立的 `22445/udp` Hysteria 入站。
- US03 的路由规则只匹配源地址 `10.66.66.5/32`，查询表 `14200`；原有主路由不变。该表保留不可达的备用默认路由，且 `ip hy03_us01` nftables 表阻止该源地址从非 `wg-us01` 接口发出。
- 专用 Xray 配置使用源地址 `10.66.66.5`，未匹配流量默认丢弃。其内置 DNS 查询也通过同一 WireGuard 出口；不修改宿主系统 DNS 或其他节点的 DNS。
- 美国 01 此路径只提供 IPv4。域名使用 A 记录；IPv6 字面目标无法使用，且不会改走 US03 的 IPv6 出口。

## 运维检查

US03：

```sh
systemctl is-active wg-quick@wg-us01.service hy03-us01-policy.service
wg show wg-us01
ip -4 route get 1.1.1.1 from 10.66.66.5
nft list table ip hy03_us01
curl -4 --interface 10.66.66.5 --noproxy '*' https://ipv4.icanhazip.com
```

US01：

```sh
wg show wg0
iptables -S INPUT
```

US03 独立节点容器配置在 `/opt/marzban-node-us03-wg-us01/`；面板控制隧道为 `marzban-us03-wg-us01-tunnel.service`。WireGuard 客户端密钥在 US03 的 `/etc/wireguard/`，美国 01 的 peer 和窄范围防火墙规则保存在 `/etc/wireguard/wg0.conf`。私钥不得放进仓库。

停用前先取消订阅发布并停止该独立节点；撤销隧道时只删除新 peer、专用入站和其源地址策略，不能重启或重置 US01 的其他 WireGuard peer。原配置备份在 US01 的 `/root/hy03-us01-wg-backup/`，面板数据库和核心配置备份在 `/root/marzban/backups/hy03-wg-us01/`。
