# 服务主机详情与实际连接路径

管理端原来的「节点设置」弹窗改为「服务主机」页面。列表包含面板本机和远程
Marzban-Node，点进主机后有「连接信息」和「服务设置」两个 tab。
原来的添加、编辑、重连、证书下载和删除功能在页面内保留。

「主机设置」中的订阅线路也有对应服务主机的连接入口，按入站筛选。
关联关系使用内核的入站下发范围，不根据订阅地址猜测服务器归属。
例如 `#/nodes/7?inbound=VLESS-REALITY` 可以直接打开节点 7 的连接页。

## 连接信息的含义

每条实际拨号记录携带同一 Xray 请求上下文中的用户、客户端地址、请求目标、
入站和出站，以及拨号成功后的 `LocalAddr` / `RemoteAddr`。
页面用实际远端地址判断出口协议，支持 IPv4 → IPv4、IPv4 → IPv6、
IPv6 → IPv4 和 IPv6 → IPv6。IPv4-mapped IPv6 按 IPv4 展示。
IPv6 优先但实际回退 IPv4 时，展示最终成功的 IPv4 套接字。

- 客户端入口：Xray 识别的客户端地址。存在入口代理时，其含义受该入站的
  客户端地址传递配置影响。
- 请求目标：请求上下文中的原始目标，可以是域名。
- 实际拨号目标：当前主机成功建立的套接字的远端地址。
- 本地源地址：本地套接字地址，在本机或上游 SNAT 之前。
- 入站 → 出站：这次请求和实际拨号所在的路由。

此页观察当前主机这一跳，不能据此确认级联另一端或 WireGuard、远程 NAT
之后的公网源 IP。共享或复用的传输连接、用户上下文未传入系统拨号器的路径，
没有完整的每请求实际套接字信息；这些请求保留为出口未知。
UDP 记录只证明创建了套接字，不证明目标已响应。

这是**最近拨号记录**，不是当前存活连接清单。页面最多保留 500 条，
复用现有有界日志通道，繁忙时可能丢弃较早的记录，不是完整审计账本。
打开页面前已建立的长连接不会重新拨号，因此不会自动补录。
关闭、离开连接 tab、暂停或隐藏浏览器页面时释放订阅；重新打开从现有日志
缓冲和后续新连接开始采集，不新增数据库历史表。

普通 Xray 的访问日志也能展示用户、入口、请求目标和出站，但**不证明实际出口**。
页面将这些记录标记为「请求记录，出口未知」。收到同一完整元组的实际拨号记录后，
对应的待采集请求升级为实际记录。尚未观测到的请求继续保留，不能通过 DNS 策略、
出站名称或请求中的 IP 字面量推断实际出口。

## 构建主机侧采集内核

仅更新面板不会给官方 Xray 增加实际套接字信息。每个需要此功能的服务主机
都需要对应版本的采集内核。

`scripts/connection_observer/build.py` 接受一个明确选定的 Xray 源码检出目录。
它只把系统拨号器原函数改名，并添加一个包装函数：先执行原拨号逻辑，
成功后输出一行 `MZCONN` JSON，然后原样返回连接。它不包装连接对象，
不改变 DNS、Happy Eyeballs、路由、源地址、套接字选项或流量统计。
只有带已认证用户上下文的拨号才输出记录，不输出密码、UUID、完整账号配置。
没有新增监听端口；通过原有的节点 TLS 日志通道传回面板。

已验证源码版本为 Xray `v26.10.21`，提交
`1b1647cd9ddf0abc34b981d4611fc03bcac1ca74`。部署时应使用与当前运行内核
相同、已经审核的版本，避免把观察功能和内核升级混在一起。
示例（只构建，不安装、不重启）：

```bash
git clone --depth 1 --branch v26.10.21 https://github.com/XTLS/Xray-core.git /tmp/marzban-xray-observer-source
git -C /tmp/marzban-xray-observer-source rev-parse HEAD
GOOS=linux GOARCH=amd64 python3 scripts/connection_observer/build.py \
  --source /tmp/marzban-xray-observer-source \
  --output /tmp/marzban-xray-observer-linux-amd64
```

Go 会按所选源码的 `go.mod` 获取工具链和依赖。其他架构需要相应的 `GOARCH`。
补丁遇到不认识的 `DialSystem` 签名时会停止，不会猜测修改位置。
如由调用环境传入 `MARZBAN_CONNECTION_OBSERVER=0`，采集内核关闭输出。

安装前确认主机真正执行的二进制路径、架构和现有启动包装器，保存原二进制及校验和，
用当前配置执行 `xray run -test` 并检查既有协议。已有 IPv6 出口、HY03/WireGuard
启动包装器应继续使用，替换它最终执行的内核即可。构建脚本不会远程安装、修改服务、
重启节点或发布面板；这些属于单独的发布操作。

发布后逐台验证：管理连接正常，原订阅可用，新连接在该主机详情页显示对应用户、
真实源/目标地址和出口协议。不能用面板 HTTP 200 或构建成功替代这一步。
回滚时恢复原内核并按原流程重启，面板仍可展示访问请求，实际出口恢复为未知。

## 验证

本地构建同架构测试内核后运行：

```bash
python3 scripts/connection_observer/build.py \
  --source /tmp/marzban-xray-observer-source --output /tmp/marzban-observer-xray
XRAY_OBSERVER_BINARY=/tmp/marzban-observer-xray \
  .venv/bin/python -m unittest tests.test_connection_observer_runtime -v
```

真实内核测试只使用回环监听器和临时账号，覆盖四种地址族组合、
同目标并发用户、IPv6 优先时的 IPv4 回退，以及 XHTTP / Hysteria 2 的用户归属。
`tests.test_node_connections` 覆盖解析、请求未知状态、保留上限、主机隔离、
管理员权限、断线和订阅释放。连接 WebSocket 的令牌通过首帧发送，不放入 URL。
