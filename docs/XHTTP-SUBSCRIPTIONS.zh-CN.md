# Mihomo XHTTP 订阅

Clash Meta、Mihomo 和使用相同导出流程的 Shadowrocket YAML 订阅支持原生
`xhttp` / `splithttp` 入站。传统 Clash 订阅继续忽略这些入站。

在核心配置中设置 XHTTP 入站，并通过主机设置填写对外地址、端口、TLS、SNI 和
ALPN。由 NGINX 终止 TLS 时，核心入站可以只监听本地 HTTP；对外主机设置选择 TLS。
用户仍须拥有该入站的访问权限，导出使用各自的用户凭据。

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
