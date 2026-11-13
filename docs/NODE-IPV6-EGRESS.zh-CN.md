# HY 03 IPv6 优先线路

US03 的 `US03_HY2_IPV6` 入站是一条独立的 HY2 订阅线路。用户通过 IPv4 或 IPv6 连到节点，节点优先用 IPv6 连接域名目标；TCP 的 IPv6 连接不可用时可回退 IPv4。仅有 IPv4 的目标使用 IPv4。UDP 使用解析结果选择地址，数据报发出后不保证故障重放。其他入站保持原有路由。

该入站沿用 Marzban 的用户账号、订阅授权和流量统计。节点内按用户 ID 保存固定 IPv6 分配；管理员有需要时可用宿主机命令重置。旧 US02 分配通过 SQLite 一致性备份迁移，已有用户继续使用原地址。只管理此入站，面板不再提供按节点开关或网站名单。

## 节点维护

节点必须具有可回程的公网 /64、主机网络、systemd、iproute2、nftables、curl、Python 3.9+，以及支持 RoutingService、SO_MARK 和 Happy Eyeballs 的 Xray。运行文件位于 `scripts/node_egress`：启动包装器在 Xray 重启时先阻断尚未完成地址同步的用户；宿主定时服务为已授权用户分配 /128、校验回程、同步路由及 SNAT。IPv6 地址设为 deprecated，避免其他进程自动选中。没有用户配置的 IPv4 字面地址映射，也不维护网站名单。

US03 宿主机的实例配置是 `/etc/marzban-egress/us03/node.json`，其中 `inbounds` 只包含 `US03_HY2_IPV6`。Xray 包装器和节点数据目录分别为 `/opt/marzban-node-us03-hy2/xray/egress` 和 `/opt/marzban-node-us03-hy2/data/egress`；`marzban-egress@us03.timer` 定时同步。节点的 Compose 文件和环境配置保存在 `/opt/marzban-node-us03-hy2/`，包含原直连和新入站。原 US02 的定时服务已关闭，US02 核心恢复直接调用原始 Xray。

查看状态：

```sh
/usr/local/lib/marzban-egress/manage.py --config /etc/marzban-egress/us03/node.json status
```

重置某个用户时，先查看状态中的当前地址，再执行 `reset <用户 ID> --expected-address <当前地址>`。重置不会立刻中断已经建立的连接。分配数据库应通过 SQLite backup 备份，不能直接复制正在写入的数据库。修改或停用前应验证节点、订阅、IPv6 回程及 IPv4 回退，并保留可回滚配置。
