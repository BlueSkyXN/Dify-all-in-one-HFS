# Operations Runbook

本文档说明当前 all-in-one Dify Docker Space 的 Nginx 前置、只读运维入口、健康检查、日志查看和常见故障处理流程。

相关文档：

- [Architecture](./architecture.md)
- [Configuration Reference](./configuration.md)
- [Deployment Guide](./deployment.md)
- [Development Guide](./development.md)

适用范围：

- Hugging Face Docker Space
- 单容器多进程运行方式
- Dify `1.14.1`
- Plugin Daemon `0.6.0-local`
- 对外端口 `7860`

## 架构概览

容器由 `supervisord` 管理多个进程，Nginx 作为唯一外部入口：

```text
browser / curl
  |
  v
nginx:7860
  |-- Dify Web:3000
  |-- Dify API:5001
  |-- ops-service:8081
  |-- admin-service:8082 (default 404)
  |
  +-- internal services
      |-- PostgreSQL 15 + pgvector
      |-- Redis
      |-- Plugin Daemon:5002
      |-- Sandbox:8194
      |-- Dify Worker
      +-- Dify Beat
```

`ops-service` 是一个只读 Python HTTP 服务，只监听 `127.0.0.1:8081`，由 Nginx 暴露到 `/_ops/`。它不提供重启、修改配置、执行 SQL 等写操作。

`admin-service` 是独立 Python HTTP 服务，只监听 `127.0.0.1:8082`，由 Nginx 暴露到 `/_admin/`。默认 `ADMIN_ENABLED=false`，因此 `/_admin/` 返回 404；开启后才提供受控 action catalog 和可选 file manager。

## Endpoint Reference

公开或半公开探针：

```text
/nginx-health
/healthz
```

需要 `OPS_TOKEN` 的只读诊断入口：

```text
/_ops/
/_ops/health
/_ops/status
/_ops/system
/_ops/config
/_ops/version
/_ops/errors
/_ops/logs?service=<service>&lines=<n>
/_ops/metrics
```

认证方式支持三种：

```bash
curl -H "X-Ops-Token: $OPS_TOKEN" https://your-space.hf.space/_ops/health
curl -H "Authorization: Bearer $OPS_TOKEN" https://your-space.hf.space/_ops/health
curl "https://your-space.hf.space/_ops/health?token=$OPS_TOKEN"
```

浏览器临时查看可以使用：

```text
https://your-space.hf.space/_ops/?token=<OPS_TOKEN>
```

`/_ops/` dashboard 支持 English / 中文切换，并会默认跟随浏览器语言；选择会保存在浏览器本地。

`?token=` 适合临时调试，不适合长期使用，因为 URL 可能进入浏览器历史或代理日志。CLI 和自动化脚本优先使用 `X-Ops-Token`。

需要 `ADMIN_TOKEN` 的管理入口，默认关闭：

```text
/_admin/
/_admin/api/login
/_admin/api/logout
/_admin/api/status
/_admin/api/actions
/_admin/api/audit
/_admin/api/actions/restart-service
/_admin/api/actions/reload-nginx
/_admin/api/actions/run-health-checks
/_admin/api/auth/terminal
/_admin/api/files/list
/_admin/api/files/text
/_admin/api/files/download
/_admin/api/files/mkdir
/_admin/api/files/upload
/_admin/api/files/rename
/_admin/api/files/delete
```

登录和登出是浏览器 dashboard 使用的 session 接口，`/_admin/api/audit` 只读返回最近的 admin 审计事件；日志不存在时返回 200、`exists=false` 和空 `events`，但它不是完整合规审计系统。`/_admin/api/auth/terminal` 只给 Nginx `auth_request` 和 Web terminal smoke 使用。`files/text` 同时支持读取和写入，写入需要 `ADMIN_FILES_WRITE_ENABLED=true`。

CLI 示例：

```bash
curl -H "X-Admin-Token: $ADMIN_TOKEN" \
  https://your-space.hf.space/_admin/api/status

curl -H "X-Admin-Token: $ADMIN_TOKEN" \
  "https://your-space.hf.space/_admin/api/audit?limit=50"

curl -X POST \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "X-Admin-CSRF: cli" \
  -H "Content-Type: application/json" \
  -d '{"service":"dify-api","confirm":true}' \
  https://your-space.hf.space/_admin/api/actions/restart-service

ADMIN_EXPECTED_ENABLED=true \
ADMIN_TOKEN=$ADMIN_TOKEN \
scripts/admin-smoke.sh https://your-space.hf.space
```

浏览器访问 `/_admin/` 会用 `ADMIN_TOKEN` 登录并换取 signed HttpOnly cookie。`/_admin/` 管理页面支持 English / 中文切换，并会默认跟随浏览器语言；选择会保存在浏览器本地。不要把 `ADMIN_TOKEN` 放进 URL query。

## 配置项

默认值位于 `docker/dify.env.runtime`：

```env
OPS_HOST=127.0.0.1
OPS_PORT=8081
OPS_TOKEN=dify_ops_demo_token
OPS_DEFAULT_CHECKS_ENABLED=true
OPS_EXTRA_HTTP_CHECKS_JSON=
OPS_EXTRA_TCP_CHECKS_JSON=
OPS_EXTRA_COMMAND_CHECKS_JSON=
OPS_LOG_DIR=/data/logs
OPS_LOG_SERVICES_JSON=
OPS_LOG_LINES_MAX=1000
```

公开 Space 建议在 Space Settings -> Secrets 中覆盖：

```env
OPS_TOKEN=<fixed-random-token>
```

`OPS_TOKEN` 只适合演示和轻量诊断，不应当被当成生产级安全边界。公开场景建议同时将 Space 设置为 Private 或 Protected。

Admin 默认配置：

```env
ADMIN_ENABLED=false
ADMIN_HOST=127.0.0.1
ADMIN_PORT=8082
ADMIN_TOKEN=
ADMIN_SESSION_TTL_SECONDS=3600
ADMIN_AUDIT_LOG=/data/logs/admin-audit.jsonl
ADMIN_FILES_ENABLED=false
ADMIN_FILES_ROOT=/data
ADMIN_FILES_WRITE_ENABLED=false
ADMIN_FILES_MAX_UPLOAD_BYTES=10485760
WEBSSH_ENABLED=false
WEBSSH_HOST=127.0.0.1
WEBSSH_PORT=7681
WEBSSH_BASE_PATH=/_admin/terminal
WEBSSH_SHELL=/bin/bash
WEBSSH_MAX_CLIENTS=1
```

公开 Space 不建议开启 admin。确需开启时，至少使用 Private/Protected Space、强随机 `ADMIN_TOKEN`，并保持 file writes 关闭，除非正在做受控排障。
`/_admin/terminal/` 默认返回 404。确需启用 terminal 时，设置 `WEBSSH_ENABLED=true` 并通过 `ADMIN_TOKEN` 鉴权访问；当前镜像内置 `ttyd`，Nginx 只把鉴权通过的请求代理到 `127.0.0.1:7681`。

Web terminal smoke：

```bash
ADMIN_EXPECTED_ENABLED=true \
WEBSSH_EXPECTED_ENABLED=true \
ADMIN_TOKEN=<admin-token> \
scripts/webssh-smoke.sh https://your-space.hf.space
```

## 版本和构建元数据

`/_ops/version` 返回只读版本摘要：

```bash
curl -H "X-Ops-Token: $OPS_TOKEN" https://your-space.hf.space/_ops/version
```

重点字段：

```text
version.dify_version
version.build.dify_api_image
version.build.dify_web_image
version.build.plugin_daemon_image
version.build.sandbox_image
version.build.uv_version
version.build.ttyd_version
version.sandbox.python_path
version.sandbox.requirements.sha256
version.sandbox.requirements.package_count
```

这些字段用于判断 live 镜像使用的上游 image 来源和 Sandbox requirements 摘要。它们不替代 Docker build log，也不证明 Hugging Face runtime 已接管目标 commit；发布时仍需对照 `hf spaces info` 的 `runtime.raw.sha`。

## 健康检查语义

`/healthz` 是对外综合健康探针，内部实际由 `ops-service` 执行以下检查：

```text
postgres            pg_isready
redis               redis-cli ping
plugin-daemon-tcp   TCP 127.0.0.1:5002
sandbox-tcp         TCP 127.0.0.1:8194
dify-api-health     HTTP 127.0.0.1:5001/health
dify-web            HTTP 127.0.0.1:3000/apps
nginx               HTTP 127.0.0.1:7860/nginx-health
dify-setup          HTTP 127.0.0.1:5001/console/api/setup
dify-init           HTTP 127.0.0.1:5001/console/api/init
```

`/_ops/health` 会额外返回：

- supervisor 进程状态
- Dify / Space 版本摘要
- 每个探针的耗时、HTTP 状态和短样本

迁移到其他程序时，可以设置 `OPS_DEFAULT_CHECKS_ENABLED=false`，再用 `OPS_EXTRA_HTTP_CHECKS_JSON`、`OPS_EXTRA_TCP_CHECKS_JSON` 和 `OPS_EXTRA_COMMAND_CHECKS_JSON` 添加目标程序自己的只读探针。自定义探针最多执行 32 个；HTTP 探针可以用 `expected_status` 明确要求返回码。

刚发布后，Dify Web 和 API 可能需要几十秒到数分钟 warmup。`scripts/hf-space-smoke.sh` 默认会重试，避免把短暂 502 或 timeout 当作最终失败。

## 系统资源与 Metrics

`/_ops/system` 返回只读系统摘要：

```text
CPU load
memory total / available / used
disk usage for /, /data, PERSIST_ROOT, RUNTIME_ROOT
container uptime
ops-service uptime
process count
```

`/_ops/metrics` 返回 Prometheus text format，包含 ops service、health check、load、memory、disk、uptime 和 process count 指标。它仍然需要 `OPS_TOKEN`，可以给 Prometheus、Uptime Kuma 或其他外部监控通过 header 抓取。

## 日志入口

可查看的日志服务白名单由 `docker/ops_service.py` 中的 `SERVICE_LOGS` 控制。

常用示例：

```bash
curl -H "X-Ops-Token: $OPS_TOKEN" \
  "https://your-space.hf.space/_ops/logs?service=dify-api&lines=200"

curl -H "X-Ops-Token: $OPS_TOKEN" \
  "https://your-space.hf.space/_ops/logs?service=plugin-daemon&lines=200"

curl -H "X-Ops-Token: $OPS_TOKEN" \
  "https://your-space.hf.space/_ops/logs?service=postgres.err&lines=200"
```

当前允许的服务名：

```text
supervisord
postgres
postgres.err
redis
redis.err
postgres-backup
postgres-backup.err
plugin-daemon
plugin-daemon.err
dify-api
dify-api.err
dify-worker
dify-worker.err
dify-beat
dify-beat.err
nginx
```

`sandbox`、`dify-web`、`ops-service`、`admin-service` 和 `web-terminal` 当前由 supervisor 直接写到容器 stdout/stderr，主要通过 Hugging Face App logs 查看；`/_ops/logs` 暂不暴露它们的专用文件。这样 `ops-service` 本体不需要写 `/data`，只通过 `OPS_LOG_DIR` 只读读取其他服务日志。

迁移到其他程序时，可以保留默认白名单，也可以用 `OPS_LOG_SERVICES_JSON` 增加服务到相对日志文件名的映射：

```env
OPS_LOG_DIR=/var/log/my-app
OPS_LOG_SERVICES_JSON={"api":"api.log","worker":"worker.log"}
```

`OPS_LOG_SERVICES_JSON` 里的文件名必须是相对路径，不能使用绝对路径或 `..`，避免把日志查看能力扩展成任意文件读取。
`/_ops/config` 会展示日志 service 名和额外探针名称，但不会返回 `OPS_LOG_SERVICES_JSON` 或 `OPS_EXTRA_*_CHECKS_JSON` 的原始 JSON。

`/_ops/errors` 会从白名单日志 tail 中匹配常见错误模式，同时过滤已知启动期 benign 日志，例如 PostgreSQL 刚启动时的 `FATAL: the database system is starting up`。返回内容会按 service 分组，包含匹配到的 pattern、pattern count、总匹配数和受限的最近行。可用 query 参数：

```text
lines=300              每个日志最多扫描的 tail 行数，受 OPS_LOG_LINES_MAX 和 1000 双重限制
limit=200              全局返回 match 上限，最多 500
per_service_limit=50   每个 service 返回 match 上限，最多 200
```

因此它适合作为近期异常摘要，不是完整日志审计系统。

Nginx access log 使用 JSON 格式，包含：

```text
request_id
remote_addr
method
uri
status
request_time
upstream_addr
upstream_status
upstream_response_time
host
```

Nginx 配置把 access log 写到 stdout，当前 `supervisord` 会把 Nginx stdout 收进 `/data/logs/nginx.log`，因此可以通过 `/_ops/logs?service=nginx` 查看。这些字段用于判断 502 来自 Nginx 本身、Dify Web、Dify API，还是上游进程尚未 ready。

## 发布后验收

推荐顺序：

1. 确认 Space runtime。

```bash
hf spaces info BlueSkyXN/dify-all-in-one
```

重点看：

```text
runtime.stage = RUNNING
runtime.raw.sha = <expected commit sha>
```

2. 运行 smoke。

```bash
OPS_TOKEN=your-configured-ops-token \
  scripts/hf-space-smoke.sh https://blueskyxn-dify-all-in-one.hf.space
```

3. 查看错误摘要。

```bash
curl -sS -H "X-Ops-Token: $OPS_TOKEN" \
  https://blueskyxn-dify-all-in-one.hf.space/_ops/errors
```

期望：

```json
{"ok": true, "matches": []}
```

4. 用真实浏览器打开 Space。

```text
https://blueskyxn-dify-all-in-one.hf.space/
```

新实例未初始化时，页面会跳转到 `/install` 并显示管理员账户设置页。

## 502 排障流程

502 通常来自 Nginx 无法连接 Dify Web 或 Dify API。按下面顺序排查：

1. 检查 Nginx 是否存活。

```bash
curl https://your-space.hf.space/nginx-health
```

如果返回 `ok`，说明外部端口和 Nginx 本身可用。

2. 检查综合健康。

```bash
curl https://your-space.hf.space/healthz
```

如果 `/healthz` 返回 503，再访问鉴权入口看细节：

```bash
curl -H "X-Ops-Token: $OPS_TOKEN" https://your-space.hf.space/_ops/health
```

3. 看 supervisor 状态。

```bash
curl -H "X-Ops-Token: $OPS_TOKEN" https://your-space.hf.space/_ops/status
```

如果某个程序不是 `RUNNING`，继续看对应日志。

4. 定位上游日志。

```bash
curl -H "X-Ops-Token: $OPS_TOKEN" \
  "https://your-space.hf.space/_ops/logs?service=nginx&lines=200"

curl -H "X-Ops-Token: $OPS_TOKEN" \
  "https://your-space.hf.space/_ops/logs?service=dify-api&lines=200"

curl -H "X-Ops-Token: $OPS_TOKEN" \
  "https://your-space.hf.space/_ops/logs?service=plugin-daemon&lines=200"
```

5. 对照 Hugging Face runtime 状态。

```bash
hf spaces info BlueSkyXN/dify-all-in-one
hf spaces logs BlueSkyXN/dify-all-in-one -n 220
hf spaces logs BlueSkyXN/dify-all-in-one --build -n 220
```

刚推送后，`sha` 可能先更新，但 `runtime.raw.sha` 仍是旧值；只有 `runtime.stage=RUNNING` 且 `runtime.raw.sha` 切到目标提交，才代表新镜像已接管流量。

## Plugin Daemon Migration

Plugin Daemon `0.6.0-local` 需要在启动 server 前执行数据库迁移：

```bash
/opt/dify/plugin-daemon/commandline migrate
```

本工程在 `docker/supervisord.conf` 中按上游镜像启动顺序运行：

```bash
/opt/dify/plugin-daemon/commandline migrate && exec /opt/dify/plugin-daemon/main
```

如果跳过这一步，典型错误是：

```text
ERROR: relation "install_tasks" does not exist
failed to get all tasks
```

修复后，`plugin-daemon.log` 中应出现：

```text
database migration completed successfully
```

且 `/_ops/errors` 不再出现 `install_tasks` 缺表错误。

## Smoke 脚本参数

默认：

```env
SMOKE_RETRIES=30
SMOKE_DELAY=5
```

示例：

```bash
OPS_TOKEN=your-configured-ops-token \
SMOKE_RETRIES=60 \
SMOKE_DELAY=5 \
scripts/hf-space-smoke.sh https://blueskyxn-dify-all-in-one.hf.space
```

如果目标实例已经开启 `/_admin`，使用：

```bash
SMOKE_ADMIN_ENABLED=true \
ADMIN_TOKEN=<admin-token> \
OPS_TOKEN=your-configured-ops-token \
scripts/hf-space-smoke.sh https://blueskyxn-dify-all-in-one.hf.space
```

默认不会触发 admin action。需要额外验证 `run-health-checks` action 时再加：

```bash
SMOKE_ADMIN_ACTIONS=true
```

脚本当前检查：

```text
web-root
space-frame-headers
nginx-health
ops-healthz
admin-disabled
webssh-disabled
admin-status        # 仅 SMOKE_ADMIN_ENABLED=true 时
admin-actions       # 仅 SMOKE_ADMIN_ENABLED=true 时
admin-audit         # 仅 SMOKE_ADMIN_ENABLED=true 时
admin-run-health-checks # 仅 SMOKE_ADMIN_ENABLED=true 且 SMOKE_ADMIN_ACTIONS=true 时
webssh-terminal     # 仅 SMOKE_ADMIN_ENABLED=true 且 SMOKE_WEBSSH_ENABLED=true 时
setup-api
init-api
ops-health
ops-system
ops-metrics
ops-errors
```

`ops-errors` 当前只验证 endpoint 可访问，人工排障时仍建议查看 JSON 中的 `ok` 和 `matches`。

## 后续可扩展方向

当前 `/_ops` 保持只读，`/_admin` 已承接受控写操作。后续可以考虑：

- 增加按 service / severity / keyword 过滤日志。
- 增加 build/runtime SHA 展示和版本漂移提示。
- 增加只读数据库 schema 检查，例如 plugin-daemon 必需表是否存在。
- 增加显式 warmup 状态，区分启动中和真正失败。

涉及执行迁移、清理缓存、SQL、配置修改等新写操作时，仍应放在 `/_admin/*`，并继续使用独立 `ADMIN_TOKEN`、白名单 action、`confirm=true`、CSRF header、审计日志和 action id / result。不要把任意 shell command 放进请求参数。WebSSH 或 interactive shell 只能作为最后阶段能力，默认关闭并与 OPS 权限隔离。
