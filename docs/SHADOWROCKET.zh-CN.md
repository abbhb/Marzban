# Shadowrocket 完整订阅

从 `v0.8.4-mgma.23` 起，小火箭使用与 Clash Meta 相同的套餐授权、外部节点快照和面板规则模板。节点参数原样保留，包括 Reality、XHTTP、ECH、Hysteria2 端口范围等；具体协议是否可连接取决于客户端版本与上游服务。

## 导入

在用户门户「接入」页或管理员的临时订阅弹窗中重新授权，选择「小火箭完整配置 → 导入节点与规则」。下载后在小火箭启用该配置，将「全局路由」设为「配置」。

如果系统没有唤起小火箭，复制同一区域的专用链接，在小火箭「配置 → ＋」中下载并启用。「仅导入节点」只在首页添加订阅，不会自动启用分流规则。

客户端需要使用支持 Clash YAML 配置导入的新版 Shadowrocket。参考：[配置导入说明](https://github.com/LOWERTOP/Shadowrocket/wiki#配置文件)、[App Store 更新记录](https://apps.apple.com/us/app/shadowrocket/id932747118)。

## 服务端行为

- 自动识别 `Shadowrocket` User-Agent，也支持显式 `/{subscription_token}/shadowrocket?token=...` 与兼容的 `/mgma/shadowrocket?token=...`。
- 返回 `text/yaml`，文件名为 `shadowrocket.yaml`，同时包含 `proxies`、`proxy-groups`、`rules` 和现有模板设置。
- 服务端展开 `include-all-proxies` / `include-all` 及其节点筛选，保留显式 fallback 成员和顺序；第三方节点继续隔离在既有来源组和 `MGMA · External` 内。
- 空组使用 `REJECT`；拒绝悬空或循环组引用；需要客户端另行拉取的 `proxy-providers` 暂不支持，不会静默漏掉节点。
- 现有 Clash / Clash Meta 导出不变；不访问第三方订阅 URL，不增加数据库迁移，不修改节点、套餐或代理凭据。
- 短效授权、IP 限制、到期、一次性消费保持原有契约。链接失效后先回面板重新授权；一次性授权每次导入前都需重新授权，不要点击「重新生成订阅」来替代常规授权。

## 验证

运行现有 unittest 套件以及 `tests.test_shadowrocket`。测试使用临时 SQLite 和合成节点；协议字典、规则、DNS 在 YAML 往返后保持一致，动态组展开、外部节点隔离、空组、循环引用、各订阅入口均有覆盖。

上线前应对实际套餐逐个只读渲染，核对节点/第三方节点/组/规则数量及组引用，保存 SQLite 在线备份、配置和旧镜像 ID；上线后再次检查容器、节点连接、鉴权与公网资源。服务器验证不能代替 iPhone 上实际点击导入和连接测试。
