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
- 如果 `OPS_TOKEN` 使用默认值且没有显式设置 `ALLOW_DEMO_OPS_TOKEN=true`，`ops-service` 会进入 locked mode 并让 `/healthz` 与 `/_ops/*` 返回 503。公开长期运行必须覆盖为强随机值。
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
OPS_TOKEN=<fixed-demo-or-random-token>
DB_PASSWORD=<fixed-demo-or-random-password>
REDIS_PASSWORD=<fixed-demo-or-random-password>
SECRET_KEY=<fixed-random-secret>
PLUGIN_DAEMON_KEY=<fixed-random-secret>
PLUGIN_DIFY_INNER_API_KEY=<fixed-random-secret>
CODE_EXECUTION_API_KEY=<fixed-random-secret>
```

不要单独上传 `SANDBOX_API_KEY` 和 `INNER_API_KEY_FOR_PLUGIN`，除非你明确要拆分内部 key。默认情况下，`SANDBOX_API_KEY` 继承 `CODE_EXECUTION_API_KEY`，`INNER_API_KEY_FOR_PLUGIN` 继承 `PLUGIN_DIFY_INNER_API_KEY`。

如果不设置 Dify 内部 secret，entrypoint 会生成并写入：

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

优先使用 header。`?token=` 只适合临时浏览器调试；成功后 dashboard 会设置 signed HttpOnly cookie 并跳转到无 query 的 `/_ops/`。URL 仍可能进入浏览器历史，因此不要把 query token 当成推荐入口。

`/_ops/` dashboard 支持 English / 中文切换，默认跟随浏览器语言，并把选择保存在浏览器本地。新增诊断状态、错误说明或按钮文案时，应同步两种语言，避免不同语言下的运维含义不一致。

`OPS_TOKEN` 不是生产级访问控制：

- 没有用户体系。
- 没有权限分级。
- 没有审计日志。
- 没有 token rotation 机制。

写操作不进入 `/_ops`；管理能力由独立的 `/_admin` 边界承接。

## `/_admin` 设计边界

`/_admin/*` 是独立于 `/_ops` 的受控管理面，不复用 `OPS_TOKEN`，也不默认开启。当前默认值：

```env
ADMIN_ENABLED=false
ADMIN_TOKEN=
ADMIN_FILES_ENABLED=false
ADMIN_FILES_WRITE_ENABLED=false
```

最低门槛：

- `ADMIN_ENABLED=false` 作为默认值。
- `ADMIN_TOKEN` 独立于 `OPS_TOKEN`。
- 只允许白名单 action，例如 restart service、reload nginx、run health checks。
- 写 action 要求显式确认参数，例如 `confirm=true`。
- Browser cookie session 写请求要求 CSRF header；CLI header token auth 显式跳过 CSRF，因为 header token 不会被浏览器自动携带。
- 登录失败会写入 admin audit，并按 remote IP 与全局窗口做内存级限速。
- 记录审计日志，返回 action id 和 result；`/_admin/api/audit` 只读展示最近审计事件，不能读取任意文件，也不是完整合规审计系统。
- 不从请求参数接收任意 shell command。

当前没有提供 run migration、clear cache、SQL、任意 command 或配置修改。Dify migration 命令涉及上游 runtime 语义，不能在未确认真实命令前加入 action catalog。

`/_admin/api/files/*` 是 admin file manager，不属于 ops-service。它默认以 `/data` 为 root，并把请求 path 当成相对 root 的路径处理；解析后的路径必须仍在 `ADMIN_FILES_ROOT` 内。默认拒绝读取或写入 `generated.env`、`*.pem`、`*.key`、`*secret*`、`*token*`。写入能力需要额外开启 `ADMIN_FILES_WRITE_ENABLED=true`；rename/delete 还要开启 `ADMIN_FILES_DESTRUCTIVE_ENABLED=true`。

`/_admin/` 登录页和管理 dashboard 支持 English / 中文切换，默认跟随浏览器语言，并把选择保存在浏览器本地。管理 action、confirm 提示、file manager 状态和错误信息必须同步两种语言，避免管理员在不同语言界面下误判操作影响。

WebSSH、Web terminal、SSH daemon 和其他 interactive shell server 风险明显高于受控 action catalog，且容易触发 Hugging Face 平台风控。本仓库已从 HF Space runtime 中移除该能力：镜像不再安装 `ttyd`，Nginx 不再暴露 `/_admin/terminal/`，`WEBSSH_*` 不再是受支持配置。需要排障时使用 Hugging Face logs、`/_ops` 只读诊断和 `/_admin` 白名单 action。

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
MARKETPLACE_ENABLED=true
FORCE_VERIFYING_SIGNATURE=false
ENFORCE_LANGGENIUS_PLUGIN_SIGNATURES=false
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

`ops-service` 会对自己的 query token 日志做路径脱敏，Nginx access log 当前记录 `$uri` 而不是 `$args`，但浏览器历史和其他系统仍可能保留完整 URL。避免长期使用 `?token=`。

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
