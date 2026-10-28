# Mihomo XHTTP 订阅

Clash Meta、Mihomo 和使用相同导出流程的 Shadowrocket YAML 订阅支持原生
`xhttp` / `splithttp` 入站。传统 Clash 订阅继续忽略这些入站。

在核心配置中设置 XHTTP 入站，并通过主机设置填写对外地址、端口、TLS、SNI 和
ALPN。由 NGINX 终止 TLS 时，核心入站可以只监听本地 HTTP；对外主机设置选择 TLS。
用户仍须拥有该入站的访问权限，导出使用各自的用户凭据。

当已导出的节点上行服务器或独立下行服务器使用 IPv6 地址时，面板自动将订阅顶层
`ipv6` 设为 `true`。Mihomo 的 `ipv6: false` 会在实际拨号前拒绝 IPv6 服务器地址，
即使地址已经直接写入节点也一样。`dns.ipv6` 的 AAAA 应答策略不随此修改；没有 IPv6
入口的订阅继续保留原模板设置。客户端的全局覆写仍可能覆盖订阅，手机需要允许 IPv6。

具有明确 IPv6 上行或独立下行地址的节点，导出名称统一以 `[ipv6] ` 开头。节点列表及
“节点选择”组按 IPv6 在前、其他节点在后稳定排序，同一类别内保留已有顺序，其他策略组
保留管理员设置的成员顺序。策略组、
规则及节点转接引用会同步更新；节点凭据、地址和监听配置不变，不增加文案占位节点。

`xhttpSettings` 中的 `path`、`mode`、POST 参数、`xmux` 和 `downloadSettings`
会转换为 Mihomo 的 `xhttp-opts`。除 `host`、`path`、`mode` 外，这些客户端选项
也可以放在 `extra` 中；设置 `extra` 时，与 Xray 一致，以其内容替换其他外层选项。
主机设置的路径和 Host 覆盖上行对应字段。下行路径需要指向同一个 XHTTP 服务。

例如，短 POST 上行、H2 连接复用、CDN 下行：

```json
{
  "path": "/images/example/",
  "mode": "packet-up",
  "extra": {
    "xmux": {"maxConcurrency": "16-32", "hMaxReusableSecs": "1800-3000"},
    "downloadSettings": {
      "address": "cdn.example.test",
      "port": 443,
      "network": "xhttp",
      "security": "tls",
      "tlsSettings": {"serverName": "cdn.example.test", "alpn": ["h2"], "fingerprint": "chrome"},
      "xhttpSettings": {
        "path": "/images/example/",
        "xmux": {"maxConcurrency": "16-32", "hMaxReusableSecs": "1800-3000"}
      }
    }
  }
}
```

XHTTP 的 HTTP 连接复用使用 `xmux`，导出不会叠加 `smux` 或 Vision flow。
反向代理应关闭请求和响应缓冲、禁用该路径缓存，并设置适当的读写超时。
CDN 仍可能关闭空闲下行流，HTTP 连接保活不能替代应用数据或应用层保活。

此改动针对 Mihomo YAML 导出；其他订阅格式的 XHTTP 导出行为保持现状。

## 在面板中管理方案

管理员打开“主机设置 → XHTTP 方案”，选择服务端入站后，可以逐项修改名称、上行与
独立下行的地址、端口、TLS/REALITY、SNI、Host、ALPN、客户端指纹及 HTTP 复用参数。
每行提供订阅启停、上移、下移和移除操作；保存后按列表顺序导出。IPv6 地址直接填写
地址本身，不带协议、端口或方括号。后端路径只读，避免客户端方案偏离已有服务端路径。

“沿用基础主机连接参数”对应只有 label 的方案，基础主机后续变化仍会同步继承。
取消继承后，该方案拥有独立的客户端连接参数；未显示的现有 POST、请求头和复用选项
会保留。每个入站最多八个方案。

启停只控制后续订阅是否包含该方案，不撤销用户对共享后端的权限，也不强制断开已建立
的连接。已有客户端需自行刷新订阅。停用所有方案时不导出派生节点；移除所有方案则
恢复导出基础主机。方案适用于该入站下的每个已启用主机，凭据和流量仍归当前用户。

管理 API 为仅 sudo 管理员可用的 `GET/PUT /api/core/xhttp-profiles`。PUT 携带 GET
返回的 revision 和按入站分组的 profiles，过期版本返回 409。此 API 原子保存元数据并
更新订阅导出配置，不重启核心或远端 Node，不修改监听、主机列表、套餐或用户权限。

## 在套餐中选择具体方案

“套餐管理 → 编辑套餐 → 允许的 VLESS 节点”可展开每个入站，选择“全部方案”、
“仅 IPv6”、“仅 IPv4”或逐项勾选。Vision 的不同主机入口和 XHTTP 派生方案均可选择，
IPv6 下行与 IPv6 上行都会归入 IPv6 方案。已有套餐默认保持全部方案，无需迁移选择。

自选结果存放在套餐的 `local_node_selections`，按入站关联不含凭据的路由标识。
已有订阅者在下次获取订阅时使用当前套餐选择；未勾选项在生成节点前即被过滤，
策略组仅能引用过滤后留下的节点。“全部方案”自动包含后续新增方案，自选不会。
取消最后一个方案会取消该入站授权，不会恢复成全部方案。

改名、排序和启停不改变路由标识。连接参数变更或删除后，失效选择不再下发，并会在
编辑保存或后台清理时移除。此时不会回退到基础主机，也不会自动授权其他方案。其他订阅格式无法
表达选定的 XHTTP 派生方案时会省略该入站，Vision 的主机过滤仍然有效。

这是订阅下发范围控制：多个入口仍使用同一入站与用户凭据，不会形成新的服务端身份。
若需要阻止用户手工复用 UUID 连接同一监听的其他地址，应另行拆分入站与监听权限。

仅 sudo 管理员可读取 `GET /api/commerce/admin/local-node-catalog` 并编辑套餐选择，
目录只包含路由标识、显示名称、IPv6 标记与启停状态。

### 失效引用自动清理

编辑器打开套餐时过滤目录中不存在的本机入站和方案；保存前重新获取目录，避免弹窗
打开期间删除节点后再次提交旧引用。后端更新套餐时同样清理失效的入站、方案和分组
引用，旧版本前端或仅修改套餐名称也不会再被已删除的 `HK_US` 等入站拦住。

后台 `cleanup_stale_plan_nodes` 任务启动 45 秒后执行首次扫描，此后每 5 分钟执行。
按 ID 分批扫描，每批最多 100 个套餐；每个套餐在锁内清理并独立提交，只同步受影响
订阅者的入站权限。运行时同步失败的用户下次重试。购买记录中的套餐事实保持不变。

自选方案全部失效时移除整个入站授权，避免空选择被解释为“全部方案”。编排组清空后
保留显式空列表，导出使用 `REJECT`。没有本机节点及外部来源的已有套餐自动隐藏，但
继续允许编辑，补充来源后可重新上架；空套餐不可购买或授予。目录中仍存在的停用方案
保留选择。新建套餐仍须至少选择一个本机入站或外部来源。

## 同一后端的多个备用入口

一个 XHTTP 入站可以增加 `x-marzban-xhttp-profiles` 数组，导出最多八个有独立名称的
Mihomo 节点。用户必须拥有该入站权限，每个候选使用当前用户的凭据。配置不会创建
新监听端口或自动切换策略；入口需要事先转发到同一 XHTTP 后端及相同路径。
候选数组存在时替换该主机原来的单个导出节点，名称为“主机名称 · label”。

```json
{
  "x-marzban-xhttp-profiles": [
    {
      "label": "P2 备用 XHTTP REALITY 直连",
      "address": "origin.example.test",
      "port": 443,
      "streamSettings": {
        "network": "xhttp",
        "security": "reality",
        "realitySettings": {"serverName": "front.example.test", "publicKey": "PUBLIC_KEY", "shortId": "abcd", "fingerprint": "chrome"},
        "xhttpSettings": {"path": "/images/example/", "mode": "packet-up", "xmux": {"maxConcurrency": "16-32"}}
      }
    },
    {"label": "实验 上行 TLS 直连 下行 CDN"}
  ]
}
```

省略候选的 `streamSettings` 时保留主机原来的传输配置；指定时完整替换客户端传输，
不会继承原来的下行入口。下行仍通过 `xhttpSettings.downloadSettings` 独立配置。
只导出公开连接参数，忽略服务端私钥和证书文件。REALITY 节点及独立 REALITY 下行
显式启用 Mihomo 的 `support-x25519mlkem768`，避免新版本服务端拒绝旧式握手。
