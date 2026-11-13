# 按节点管理 IPv6 出口

管理员在「节点设置 → 目标节点 → IPv6 出口」开关策略、刷新名单或选择用户并重置地址。点击「查看名单」可查看节点最近一次成功应用的域名后缀、IPv4 双栈映射和 IPv6 网段。只有配置了控制通道的节点才可管理。客户端可以仅有 IPv4。它通过原订阅连到节点，节点用新的连接访问目标，响应沿已有代理连接返回客户端。

## 地址和 DNS

- 每个节点按 Marzban 数字用户 ID 在自己的公网 /64 分配随机 /128，SQLite 保存地址和 socket mark。切换入口、轮换代理凭据、重启、更新名单和关闭再开启都沿用同一分配。并发重置以管理员看到的原地址为条件，旧页面重复提交返回 409。已建立的连接保留内核已有的连接状态。
- 节点每天根据本机解析器返回的公网 AAAA 生成域名后缀名单。管理员可在该节点的 `targets.json` 指定探测域名、手动纳入的后缀、IPv6 前缀及 IPv4 别名。临时解析异常会保留上次成功的名单并重试。实际连接通过 Xray 的 DNS 配置解析目的域名。客户端需要透传域名或使用能保留域名的代理模式。
- 名单内的 TCP 使用 Happy Eyeballs 优先建立 IPv6，300 毫秒后可并行尝试另一个地址族。名单外的域名优先 A，IPv6-only 目标也使用用户分配的地址。UDP 在域名没有 AAAA 时可选 A，已有 AAAA 的 UDP 路径无响应时无法安全重放任意数据报。
- 普通 IPv4 字面地址沿用 IPv4。需要双栈转换时，在 `ipv4_aliases` 中声明 IPv4 和等价服务域名。每天验证域名同时拥有该 A 记录和公网 AAAA 后，仅对该精确 IPv4 的 TCP 启用重定向，保留目标端口。默认示例为 `1.1.1.1`。域名应由服务方明确作为等价入口。
- Xray 根据用户标记出站 socket。宿主仅对本节点 mark 和指定网卡的 IPv6 应用 SNAT。地址以 `preferred_lft 0` 添加，避免其他进程自动选用。地址就绪后用独立 HTTPS 回显验证回程，才发布用户路由。新用户或核心刚启动时，已开启的受管入口等待同步成功后再放行普通直出。控制 API、原有优先阻断或转发规则保留原顺序。

## 节点部署

以独立 Linux 节点实例为单位安装。需要实际可回程的公网 /64、主机网络、iproute2、nftables、curl、Python 3.9+、systemd，以及支持 RoutingService 动态路由、SO_MARK 和 Happy Eyeballs 的 Xray。内核 5.17+ 可用 CAP_NET_RAW 设置 mark。灰度验证使用 Xray 26.10.21。使用其他版本前先验证 API 和代理入口。现有数据库和容器配置应保留备份。

1. 将 `scripts/node_egress/{manage,policy,remote}.py` 安装到宿主的 `/usr/local/lib/marzban-egress/`，设置 root 所有且仅 root 可写。将 `launch.py` 和 `policy.py` 放在容器 Xray 二进制旁边的 `egress/` 子目录，确认 launcher 的 Python 解释器路径可用。只在目标节点 compose 中将 `XRAY_EXECUTABLE_PATH` 指向该 launcher，并给 Xray 设置 mark 所需的能力。宿主运行 nft，节点进程无需操纵宿主防火墙。
2. 建立权限 0700 的 `/etc/marzban-egress/<实例>/` 和容器数据卷中对应的 `/var/lib/marzban-node/egress/`。复制 `targets.json`。在前一个目录写入 `node.json`，使用该实例的实际值。

```json
{
  "namespace": "example",
  "prefix": "<运营商分配的公网 /64>",
  "interface": "eth0",
  "mark_prefix": 25701,
  "binary": "/opt/example/xray/xray",
  "state": "/opt/example/data/egress",
  "inbounds": ["EXAMPLE_VLESS", "EXAMPLE_XHTTP"]
}
```

3. 在同一宿主为每个实例保留唯一的 mark 高 16 位和 nft 表名 `mz6_<namespace>`，与已有策略路由和防火墙规则错开。仅选择带用户身份的直出入口。重建这一个节点并确认面板重新连接。安装 `marzban-egress@.service` 和 `marzban-egress@.timer` 到 systemd，执行 `systemctl daemon-reload` 和 `systemctl enable --now marzban-egress@<实例>.timer`。默认关闭，timer 每 30 秒核对分配、核心和路由。
4. 可用 `manage.py --config /etc/marzban-egress/<实例>/node.json status` 查看状态。动作支持 `on`、`off`、`refresh`、`sync` 和 `reset <用户 ID> --expected-address <当前 IPv6>`。`off` 恢复此节点原来的路由并清理该实例拥有的内核地址和 nft 表。保留 `allocations.sqlite3` 以维持地址连续性。彻底卸载时先确认关闭已生效，再停用 timer、恢复原核心启动路径。备份分配时使用 SQLite 的 backup 功能。

## 面板接入

在已有 Marzban Unix socket 的 Linux 控制面安装 `panel.py`、`marzban-egress-panel.socket` 和同名 service。创建无登录服务账户 `marzban-egress-panel`，提供访问 `/run/marzban/marzban.sock` 的组权限。该扩展对每次请求通过现有面板验证管理员 bearer，并要求 sudo 角色。

- `/etc/marzban-egress-panel/nodes.json` 按面板节点 ID 映射到 SSH 别名，例如 `{"3":"example"}`。未列入的节点没有可执行的开关。
- 在同目录的 `ssh_config` 写明该别名的 HostName、User、专用 IdentityFile 和 UserKnownHostsFile，启用 StrictHostKeyChecking 和 IdentitiesOnly。在节点为对应公钥设置 `restrict,command="/usr/local/lib/marzban-egress/remote.py example"`。服务用户应能读取自己的私钥，密钥、主机映射和 SSH 配置仅由受信任管理员管理。
- 启用面板 socket。在现有 HTTPS 面板 server 内把 `/api/node-egress/` 转发到 `/run/marzban/egress.sock`，代理超时至少 120 秒。发布配套 dashboard 静态文件。GET 返回节点状态和用户分配，POST 支持开关、刷新和带旧地址校验的重置。面板扩展和代理节点可独立更新。
