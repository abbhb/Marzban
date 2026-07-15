# MGMA 临时订阅访问

MGMA 把订阅分发从长期 URL 改为管理员按需签发的短期 bearer URL。默认有效期为 180 秒；同一用户每次重新签发都会立即废止上一个 token。公开 URL 形如：

```text
https://panel.example.com/sub/mgma?token=<43-character-token>
```

这项能力缩短了 URL 被转发或日志误收集后的重放窗口，但不能保证订阅内容“永远无法被抓取”。获准下载的客户端必然能看到节点配置，也可以保存或再次分享它。VLESS UUID 等节点凭据仍需通过撤销用户、重置订阅或轮换凭据来失效。

## 安全模型

- token 使用 `secrets.token_urlsafe(32)` 生成，约 256 bit 随机性。
- 数据库只保存 `HMAC-SHA256(pepper, token)`，不保存明文 token。
- `MGMA_TOKEN_PEPPER` 至少需要 32 个 UTF-8 字节，保存在部署环境而不是 SQLite 中。
- 新签发覆盖旧摘要，因此每个用户仅最新 token 有效。
- 默认 token 在有效期内可重复请求，兼容 Clash/Mihomo 的探测、重试和格式选择。
- 可选 `single_use` 会在首次验证时用条件更新原子消费 token；它可能导致部分客户端导入失败，仅作为高级选项。
- 未知、格式错误、过期、已消费、来源不允许和用户不可用的 token 对公网统一返回 `404 Not Found`。
- MGMA 响应不包含 `profile-web-page-url`，并带有 `no-store`、`no-referrer`、`noindex` 等响应头。
- 浏览器 `Accept: text/html` 访问 MGMA URL 返回 404，避免落入订阅 HTML 页或外部二维码脚本。
- 管理面板只在内存中保存明文 URL；关闭弹窗或倒计时结束后清除，不写入 local/session storage。
- MGMA 保护的是公网订阅分发，不是已经登录的管理员边界。用户管理 API 为了编辑账号仍会返回代理 UUID/密码；恶意浏览器扩展、XSS、被盗管理员 token 或受信 webhook/机器人仍可能取得节点凭据。
- Telegram 管理机器人在 `dual/ephemeral` 下不签发 MGMA URL，也不发送 raw config；请只从 Web dashboard 获取临时链接。

## 访问模式

| 模式 | MGMA | 已有长期 `/sub/{token}` | 用途 |
| --- | --- | --- | --- |
| `legacy` | 可用 | 可用 | 保守默认和回滚 |
| `dual` | 可用 | 可用 | 迁移现有客户端 |
| `ephemeral` | 可用 | 统一 404 | 强制临时订阅 |

升级数据库后的默认值是 `legacy`，避免升级过程直接中断现有客户端。生产迁移建议先使用 `dual` 验证 MGMA，再明确切换到 `ephemeral`。来源规则会同时约束 MGMA 与仍被接受的旧 URL；但旧 URL 没有 MGMA 的 TTL 和“仅最新 token”保护。

无论模式如何，用户列表 API 都不再自动生成或返回长期订阅 URL；面板的订阅操作统一通过 MGMA 按钮完成。

## 来源策略

- `any`：不限制来源；
- `china`：仅允许内置的 APNIC `cc=CN` IPv4/IPv6 CIDR；
- `custom`：仅允许管理员填写的 CIDR；
- `china_or_custom`：匹配 China 或任一自定义 CIDR。

内置数据是版本化离线快照：

```bash
python scripts/update_cn_cidrs.py
```

脚本输出 `app/data/cn.cidr` 和带 SHA256、序列号及数据日期的 metadata。RIR 的 `cc=CN` 表示资源接收机构所属经济体，并不等于 IP 当前物理位置；境外代理、漫游、云订阅更新器和部分 IPv6 网络可能被误判。

## 反向代理信任边界

生产推荐使用 Unix socket。应用仅在 `request.client is None`（UDS）时读取由可信 Nginx 覆盖的 `X-Real-IP`；使用 TCP 监听时只信任实际 TCP peer，并忽略所有转发头。

Nginx 必须覆盖而不是追加客户端转发头：

```nginx
proxy_set_header X-Real-IP       $remote_addr;
proxy_set_header X-Forwarded-For $remote_addr;
proxy_set_header Forwarded       "";
```

同时对完整订阅路径关闭 URI 日志和缓存：

```nginx
location ^~ /sub/ {
    access_log off;
    error_log /dev/null crit;
    proxy_no_cache 1;
    proxy_cache_bypass 1;
    add_header Cache-Control "private, no-store, max-age=0" always;
    add_header Pragma "no-cache" always;
    add_header Expires "0" always;
    add_header Referrer-Policy "no-referrer" always;
    add_header X-Robots-Tag "noindex, nofollow, noarchive" always;
    proxy_pass http://marzban_panel;
}
```

应用已关闭 Uvicorn access log。不要在异常处理、审计日志或临时排障日志中打印 `request.url`、query string 或 token。

## 配置与 API

```dotenv
MGMA_TOKEN_PEPPER=<at-least-32-random-bytes>
XRAY_SUBSCRIPTION_URL_PREFIX=https://panel.example.com
```

```text
POST   /api/user/{username}/mgma       签发并返回一次临时 URL
DELETE /api/user/{username}/mgma       撤销该用户的最新临时 URL
GET    /api/subscription/settings      仅 sudo 管理员可读取
PUT    /api/subscription/settings      仅 sudo 管理员可修改
```

明文 token 会短暂出现在签发 API 响应、dashboard 内存/输入框/二维码/剪贴板（或 `marzban-cli subscription get-link` 的标准输出），以及客户端随后发起的 MGMA query 中。不要截图、录屏、把 CLI 输出重定向到文件，或把链接转发到第三方聊天服务。

## 数据库与迁移

Alembic revision `c8d9e0f1a2b3` 在 `users` 增加 token digest、签发、过期和消费时间，并新建单例 `mgma_settings` 表；它不修改现有代理、节点、流量或用户生命周期数据。

上线前必须备份 SQLite，并在备份副本运行 `alembic upgrade head` 和 `PRAGMA integrity_check`。一旦新 migration 已运行，回滚应成对恢复“旧镜像 + 升级前 SQLite”，不能只替换镜像。

## 固定基础镜像构建

先生成 dashboard，再用固定 v0.8.4 镜像进行无网络派生构建：

```bash
cd app/dashboard
npm ci
VITE_BASE_API=/api/ npm run build -- --outDir build --assetsDir statics
cp build/index.html build/404.html
cd ../..

docker buildx build \
  --platform linux/amd64 \
  --pull=false \
  --network=none \
  --provenance=false \
  --sbom=false \
  -f Dockerfile.runtime \
  --build-arg VCS_REF="$(git rev-parse HEAD)" \
  -t abbhb/marzban:v0.8.4-mgma.9 \
  --load .
```

`Dockerfile.runtime` 不运行 apt、curl、pip 或 npm，直接继承固定基础镜像的 Python 依赖和 Xray。若 `requirements.txt` 发生变化，必须改用离线 wheelhouse 重新构建。

默认基础引用使用公开的 `gozargah/marzban` 仓库，并固定到 v0.8.4 OCI index digest `sha256:8e422c…9623b8d`；其中 `linux/amd64` manifest 为 `sha256:953700…a27f1`，对应 image config `sha256:237da2…c4e419`。构建前应校验基础镜像摘要；不要把 `BASE_IMAGE` 改回可移动 tag。

## 验收清单

1. 签发响应有 URL 明文，SQLite 中只有 64 字符 digest；
2. 第二次签发后第一次 URL 立即 404；
3. 默认 180 秒内可重试，过期后 404；
4. single-use 开启后只有首个请求成功；
5. China/custom 的允许和拒绝分支均通过；
6. 伪造 `X-Forwarded-For` 不能绕过来源规则；
7. `ephemeral` 下旧订阅的基础、info、usage 和显式格式路径均为 404；
8. Nginx、Uvicorn、SQLite、响应头和 dashboard storage 中均找不到明文 token；
9. Clash/Mihomo 能在 TTL 内完成导入；
10. 不把临时订阅 smoke test 配成周期监控。

APNIC 数据源：<https://ftp.apnic.net/apnic/stats/apnic/delegated-apnic-latest>；字段语义：<https://www.apnic.net/about-apnic/corporate-documents/documents/resource-guidelines/rir-statistics-exchange-format/>。
