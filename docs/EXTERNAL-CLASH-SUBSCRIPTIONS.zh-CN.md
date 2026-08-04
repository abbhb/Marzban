# 外部 Clash 订阅与套餐引用

本文定义 MGMA fork 导入第三方 Clash/Mihomo 节点的通用契约。所有 URL、token、节点地址和密钥均使用占位符；真实值不得提交到 Git、镜像、Compose、日志、截图或工单。

## 1. 功能与信任边界

- sudo 管理员可以创建外部来源、写入式录入订阅 URL、上传 YAML 快照、手工刷新、停止定时刷新，并在套餐中选择整个来源或指定节点。
- 服务端只消费 YAML 顶层 `proxies`。上游的 `proxy-groups`、`rules`、DNS、TUN、控制端口和其他顶层设置不会进入用户配置。
- 每个来源生成一个 `select` 组；套餐选择 `all` 时自动包含未来新增节点，选择 `selected` 时只保留显式节点关系。
- 外部节点流量不经过 Marzban Xray，不能计入 Marzban 本地流量统计、套餐限额或节点用量。
- 下发给用户的第三方节点通常含共享凭据。禁用用户或让套餐到期只能阻止后续订阅下载，不能撤销用户已经保存的上游凭据；真正撤销需要上游轮换。

## 2. 只写凭据与最后成功快照

订阅 URL 是只写字段。管理员在创建来源或替换凭据时提交一次，后续来源列表、节点列表、错误响应和日志均不得返回 URL、host、path、查询参数或 token。管理端只显示 `credential_configured` 布尔值。

节点管理 API 只返回选择所需的 `id`、显示名称、协议类型、顺序和 active 状态，不返回 `server`、端口、UUID、密码、Reality 参数或其他连接字段。

刷新只有在完整下载、解析和校验成功后才能原子替换快照。认证失败、网络失败或 YAML 无效时保留 Last Known Good（LKG）节点，更新安全状态码但不保存响应正文。短效 URL 失效后可替换凭据；也可移除凭据并保留当前快照，从而停止无意义的周期请求。

单个用户配置中的外部节点投影最多为 5000 个节点、8 MiB 解密后规范化 payload。套餐保存以及来源刷新/快照导入都会在写入前检查所有受影响套餐；超限时拒绝本次变更或候选快照，并继续保留原有 LKG，避免把故障推迟到用户下载订阅时才暴露。套餐选择变更与候选快照发布先获取同一个全局预算互斥行，再按固定顺序锁来源/套餐并使用当前锁定读，避免 MySQL/PostgreSQL 多来源并发刷新分别按对方旧快照通过预算或形成交叉死锁。

## 3. 加密密钥

URL 和节点 payload 使用独立密钥加密，不得复用 `MGMA_TOKEN_PEPPER`：

```dotenv
EXTERNAL_SUBSCRIPTION_ENCRYPTION_KEY=<EXTERNAL_SUBSCRIPTION_ENCRYPTION_KEY>
```

该值至少包含 32 个 UTF-8 字节，只保存在权限为 `0600` 的环境文件和加密离机备份中。可以在受保护终端生成随机值，例如 `openssl rand -base64 48`，但不得把生成结果复制进文档或版本库。

密钥丢失或改变后，数据库里已有 URL 和节点 payload 密文不可恢复。在没有原子重加密工具前不要直接轮换；丢失后只能清理不可解密的外部数据，再重新录入 URL 或上传 YAML 快照。

## 4. 固定聚合组与模板引用

渲染器使用固定、与界面语言无关的聚合组名：

```yaml
proxy-groups:
  - name: MGMA · External
    type: select
    proxies:
      - <SOURCE_GROUP_NAME>
```

其他自定义组可以引用 `MGMA · External`。当模板存在名为 `🚀 节点选择`、类型为 `select` 且 `proxies` 是列表的主选择组时，渲染器会把实际生成的外部聚合组追加到该列表，不改写现有成员。没有外部授权的用户不能留下悬空引用；模板若始终引用该名称，应预置只含 `REJECT` 的 fallback，渲染器在有授权时再追加来源组：

```yaml
proxy-groups:
  - name: MGMA · External
    type: select
    proxies:
      - REJECT
  - name: <CUSTOM_POLICY_GROUP>
    type: select
    proxies:
      - MGMA · External
      - <LOCAL_FALLBACK_GROUP>
```

来源组名称创建后不可变，避免模板引用和 Clash `store-selected` 失效。来源或节点名称发生冲突时，渲染器必须使用稳定后缀去重。

## 5. 备份、恢复与回滚

上线前至少成套备份：

```text
<MARZBAN_ROOT>/data/db.sqlite3
<MARZBAN_ROOT>/.env
<MARZBAN_ROOT>/templates/
<MARZBAN_ROOT>/docker-compose.yml
固定镜像归档及 SHA-256
```

SQLite 保存来源、节点密文、LKG 快照和套餐引用；`.env` 保存独立加密密钥。两者必须一起恢复，secret 文件权限保持 `0600`，校验过程不得输出密钥值。

推荐迁移顺序：冻结变更和刷新任务，生成一致数据库备份，记录 migration head 与镜像摘要，恢复数据库和原密钥，在副本上执行 migration 与启动演练，再用一个测试来源验证列表 API 不回显 URL、快照可解密、套餐 `all/selected` 渲染正确。

回滚时恢复升级前数据库、原环境文件、模板和对应固定镜像；不能只回退代码而继续使用已迁移 schema。回滚数据库也不能撤销客户端已保存的第三方共享凭据。

## 6. 管理 API

接口统一位于 sudo-only 前缀 `/api/commerce/admin/external-subscriptions`：

- `GET/POST /api/commerce/admin/external-subscriptions`
- `PUT/DELETE /api/commerce/admin/external-subscriptions/{id}`
- `POST/DELETE /api/commerce/admin/external-subscriptions/{id}/credential`
- `POST /api/commerce/admin/external-subscriptions/{id}/snapshot`
- `POST /api/commerce/admin/external-subscriptions/{id}/refresh`
- `GET /api/commerce/admin/external-subscriptions/{id}/nodes`

套餐 sudo 管理响应包含 `external_selections`；公开门户套餐响应不暴露来源和节点内部 ID。
