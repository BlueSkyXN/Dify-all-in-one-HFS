# Security Notes

本文档说明当前 Demo 工程的安全边界和生产化注意事项。

## 安全定位

当前工程面向：

- 企业内训
- 课程演示
- PoC
- 快速功能验证

当前工程不等同于生产部署。生产环境应使用官方 Docker Compose、Kubernetes 或企业内部分布式部署，并引入更完整的网络隔离、secret 管理、审计、备份、监控和访问控制。

## 默认公开风险

如果 Hugging Face Space 设置为 Public：

- 任何人都可以访问 Dify Web。
- 未初始化时，任何人可能看到管理员初始化页面。
- 如果 `OPS_TOKEN` 使用默认值，任何人可以访问 `/_ops` 只读诊断面。
- Query token 形式可能进入浏览器历史。
- App logs 可能被有 Space 权限的人看到。

建议：

```text
Visibility: Private 或 Protected
OPS_TOKEN: 覆盖为固定随机值
Secrets: 设置固定强随机值
Storage Bucket: mount 到 /persist
```

## Secrets

建议设置：

```env
SECRET_KEY=<fixed-random-secret>
PLUGIN_DAEMON_KEY=<fixed-random-secret>
PLUGIN_DIFY_INNER_API_KEY=<fixed-random-secret>
CODE_EXECUTION_API_KEY=<fixed-random-secret>
SANDBOX_API_KEY=<fixed-random-secret>
OPS_TOKEN=<fixed-random-token>
```

如果不设置，entrypoint 会生成并写入：

```text
/data/config/generated.env
```

bucket-lite 模式下 `/data/config` 会映射到 `/persist/config`，这些自动生成值才能跨重启保存。

## `/_ops` 边界

`ops-service` 是只读诊断面：

- 不返回 secret 原文。
- 只返回 secret 是否存在。
- 日志读取使用 service 白名单。
- 不提供文件任意读取。
- 不提供重启、删除、修改配置、执行 SQL 等写操作。

认证方式：

```text
X-Ops-Token
Authorization: Bearer
?token=
```

优先使用 header。`?token=` 只适合临时浏览器调试。

`OPS_TOKEN` 不是生产级访问控制：

- 没有用户体系。
- 没有权限分级。
- 没有审计日志。
- 没有 token rotation 机制。

如果要扩展成管理面板，写操作必须单独设计更强鉴权和审计。

## `/_admin` 设计边界

`/_admin/*` 不应复用 `OPS_TOKEN`，也不应默认开启。建议的最低门槛：

- `ADMIN_ENABLED=false` 作为默认值。
- `ADMIN_TOKEN` 独立于 `OPS_TOKEN`。
- 只允许白名单 action，例如 restart service、reload nginx、run migration、clear cache。
- 每个 action 要求显式确认参数，例如 `confirm=true`。
- 记录审计日志，返回 action id 和 result。
- 不从请求参数接收任意 shell command。

WebSSH 或 interactive shell 风险明显高于受控 action catalog，应作为最后阶段独立模块处理；只建议 Private/Protected 环境开启，并需要独立强 token、session timeout、审计日志和清晰的命令风险说明。

## Hugging Face iframe 嵌入

Hugging Face Space 的项目页会把运行时 app 嵌入到 `huggingface.co` 页面中。Dify Web 上游默认可能返回：

```text
X-Frame-Options: DENY
```

这会导致 Space 页面报错：

```text
Refused to display '<space>.hf.space' in a frame because it set 'X-Frame-Options' to 'deny'.
```

本工程在 Nginx 边界隐藏上游 `X-Frame-Options`，并统一返回：

```text
Content-Security-Policy: frame-ancestors 'self' https://huggingface.co https://*.huggingface.co
```

这只允许本站和 Hugging Face 页面嵌入 demo，避免为了 Space iframe 兼容而放开任意第三方嵌入。修改 `docker/nginx.conf` 后，使用 `scripts/hf-space-smoke.sh` 检查该 header 是否仍然生效。

## Sandbox

默认：

```env
SANDBOX_ENABLE_NETWORK=false
```

这意味着 Code Sandbox 默认不能出网，适合演示和训练。开启网络前需要评估：

- 用户代码可以访问哪些外部地址。
- 是否允许访问内网。
- 是否允许访问 metadata endpoint。
- 是否需要 HTTP/HTTPS proxy。
- 是否要限制 package install。

## Plugin

默认：

```env
MARKETPLACE_ENABLED=false
FORCE_VERIFYING_SIGNATURE=false
ENFORCE_LANGGENIUS_PLUGIN_SIGNATURES=true
```

演示时可以降低插件安装门槛，但企业环境应制定插件来源、签名和审核策略。

Plugin Daemon 依赖：

- `PLUGIN_DAEMON_KEY`
- `PLUGIN_DIFY_INNER_API_KEY`
- `INNER_API_KEY_FOR_PLUGIN`

这些值必须保持一致，否则 Dify API 和 Plugin Daemon 通信会失败。

## Database

默认 PostgreSQL 只监听：

```text
127.0.0.1:5432
```

`pg_hba.conf` 允许：

```text
local all all trust
host all all 127.0.0.1/32 md5
host all all ::1/128 md5
```

数据库不对 Space 外部暴露。生产环境应使用独立托管数据库、备份、恢复演练和最小权限账户。

## Redis

默认 Redis 只监听：

```text
127.0.0.1:6379
```

并配置 `requirepass`。Redis 不对 Space 外部暴露。

## Logs

日志可能包含：

- 错误堆栈。
- 请求路径。
- 上游状态。
- Dify runtime 行为。
- 部分用户输入触发的错误上下文。

`ops-service` 会对自己的 query token 日志做路径脱敏，但其他系统日志仍可能记录 URL。避免长期使用 `?token=`。

## 生产化建议

如果要从 Demo 走向生产，至少需要：

- 拆分 Web/API/Worker/Beat/PostgreSQL/Redis/Plugin/Sandbox。
- 使用独立数据库和 Redis。
- 使用正式 secret manager。
- 使用 HTTPS 入口和企业级反向代理。
- 加入鉴权、审计、日志脱敏和告警。
- 为 Sandbox 设置严格网络策略。
- 为 Plugin 安装设置签名和审批流程。
- 加入备份、恢复、升级和回滚策略。
- 用 Prometheus/Grafana/OpenTelemetry 等正式观测系统替代简单 `/_ops`。
