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
