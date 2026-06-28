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
- Dify Web/API 来源由 `DIFY_WEB_IMAGE_REF` / `DIFY_API_IMAGE_REF` 记录
- Plugin Daemon 来源由 `PLUGIN_DAEMON_IMAGE_REF` 记录
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
      |-- Dify Agent backend:5005 (NEXT, disabled by default)
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
/_ops/persistence
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

`?token=` 适合临时调试，不适合长期使用，因为 URL 可能进入浏览器历史。Dashboard 会在 query token 验证成功后设置 signed HttpOnly cookie，并跳转到无 query 的 `/_ops/`；CLI 和自动化脚本优先使用 `X-Ops-Token`。

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
/_admin/api/actions/force-postgres-backup
/_admin/api/files/list
/_admin/api/files/text
/_admin/api/files/download
/_admin/api/files/mkdir
/_admin/api/files/upload
/_admin/api/files/rename
/_admin/api/files/delete
```

登录和登出是浏览器 dashboard 使用的 session 接口，`/_admin/api/audit` 只读返回最近的 admin 审计事件；日志不存在时返回 200、`exists=false` 和空 `events`，但它不是完整合规审计系统。`files/text` 同时支持读取和写入，写入需要 `ADMIN_FILES_WRITE_ENABLED=true`。

CLI 示例：

```bash
curl -H "X-Admin-Token: $ADMIN_TOKEN" \
  https://your-space.hf.space/_admin/api/status

curl -H "X-Admin-Token: $ADMIN_TOKEN" \
  "https://your-space.hf.space/_admin/api/audit?limit=50"

curl -X POST \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"service":"dify-api","confirm":true}' \
  https://your-space.hf.space/_admin/api/actions/restart-service

curl -X POST \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"confirm":true}' \
  https://your-space.hf.space/_admin/api/actions/force-postgres-backup

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
ALLOW_DEMO_OPS_TOKEN=false
OPS_CACHE_TTL_SECONDS=5
OPS_SESSION_TTL_SECONDS=3600
OPS_COOKIE_SECURE=auto
OPS_DEFAULT_CHECKS_ENABLED=true
OPS_EXTRA_HTTP_CHECKS_JSON=
OPS_EXTRA_TCP_CHECKS_JSON=
OPS_LOG_DIR=/data/logs
OPS_LOG_SERVICES_JSON=
OPS_LOG_LINES_MAX=1000
OPS_LOG_TAIL_MAX_BYTES=1048576
```

公开 Space 建议在 Space Settings -> Secrets 中覆盖：

```env
OPS_TOKEN=<fixed-random-token>
```

`OPS_TOKEN` 只适合演示和轻量诊断，不应当被当成生产级安全边界。默认 `dify_ops_demo_token` 在没有 `ALLOW_DEMO_OPS_TOKEN=true` 时会让 ops-service locked 并返回 503；公开场景必须设置强随机 `OPS_TOKEN`，并建议同时将 Space 设置为 Private 或 Protected。

Admin 默认配置：

```env
ADMIN_ENABLED=false
ADMIN_HOST=127.0.0.1
ADMIN_PORT=8082
ADMIN_TOKEN=
ADMIN_CSRF_KEY=
ADMIN_SESSION_TTL_SECONDS=3600
ADMIN_COOKIE_SECURE=auto
ADMIN_AUDIT_LOG=/data/logs/admin-audit.jsonl
ADMIN_FILES_ENABLED=false
ADMIN_FILES_ROOT=/data
ADMIN_FILES_WRITE_ENABLED=false
ADMIN_FILES_DESTRUCTIVE_ENABLED=false
ADMIN_FILES_MAX_UPLOAD_BYTES=10485760
```

公开 Space 不建议开启 admin。确需开启时，至少使用 Private/Protected Space、强随机 `ADMIN_TOKEN`，并保持 file writes 关闭，除非正在做受控排障。Web terminal / WebSSH 已从 runtime 中移除，不再提供 `/_admin/terminal/`、`WEBSSH_*` 或 `ttyd`。

## 版本和构建元数据

`/_ops/version` 返回只读版本摘要：

```bash
curl -H "X-Ops-Token: $OPS_TOKEN" https://your-space.hf.space/_ops/version
```

重点字段：

```text
version.dify_version
version.build.base_image_ref
version.build.dify_api_image_ref
version.build.dify_web_image_ref
version.build.plugin_daemon_image_ref
version.build.sandbox_image_ref
version.build.uv_version
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
shellctl-tcp        TCP 127.0.0.1:5004 when Agent shell layer is enabled
sandbox-tcp         TCP 127.0.0.1:8194
dify-api-health     HTTP 127.0.0.1:5001/health
dify-web            HTTP 127.0.0.1:3000/apps
nginx               HTTP 127.0.0.1:7860/nginx-health
dify-setup          HTTP 127.0.0.1:5001/console/api/setup
dify-init           HTTP 127.0.0.1:5001/console/api/init
```

`/_ops/health` 会额外返回：

- Supervisor XML-RPC 进程状态
- Dify / Space 版本摘要
- 每个探针的耗时、HTTP 状态和短样本
- NEXT Agent backend 与 shellctl 状态；shellctl 只在 `DIFY_AGENT_ENABLED=true` 且 `AGENT_SHELL_ENABLED=true` 时要求为 ok

迁移到其他程序时，可以设置 `OPS_DEFAULT_CHECKS_ENABLED=false`，再用 `OPS_EXTRA_HTTP_CHECKS_JSON` 和 `OPS_EXTRA_TCP_CHECKS_JSON` 添加目标程序自己的只读探针。自定义 HTTP/TCP 探针最多执行 32 个；HTTP 探针可以用 `expected_status` 明确要求返回码。`/_ops` 不支持自定义 command 探针；需要执行命令的受控操作必须放入 `/_admin` 白名单 action。

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

`/_ops/persistence` 返回只读持久化、插件包缓存、installed bucket、Redis cluster state 和 Plugin Daemon local runtime 日志证据摘要：

```bash
curl -H "X-Ops-Token: $OPS_TOKEN" \
  https://your-space.hf.space/_ops/persistence
```

重点看 `persist_active` 是否为 `bucket`、`paths.plugin_storage_root.path` 是否为真实 `/persist/plugin_daemon`、`paths.plugin_installed.is_symlink` 是否为 `false`、`paths.plugin_package_cache.real_path` 是否指向 `/persist/plugin_daemon/plugin_packages`、`plugin_identifiers[].package_exists` 和 `plugin_identifiers[].installed_exists` 是否都为 `true`。`missing_package_files`、`missing_installed_files`、`missing_runtime_states` 和 `plugin_storage_layout_issues` 都应为空。再看 `plugin_runtime_state.checked`、`plugin_runtime_state.identifiers[].state_count` 和 `plugin_runtime_state.identifiers[].log.ready`：Redis `plugin_state` 是 cluster routing 视图，单容器本机 runtime 已 ready 时，`state_count` 可能不是唯一证据。`plugin_database.api_plugin_references` 会同时列出 Dify 主库里仍引用插件式 provider name 的配置记录，用于解释为什么页面配置还可见。`postgres_backup.safe_to_restart` 是重启前的只读建议值；如果为 `false`，先看 `postgres_backup.safe_to_restart_reason`、`latest_age_seconds` 和 `latest_error`，必要时通过 `/_admin/api/actions/force-postgres-backup` 生成一次最新 dump 再重启。如果 package/installed 文件缺失，或日志没有 `local runtime ready`，再按下方 Plugin Runtime Not Found 的卸载重装路径修复。

`/_ops/metrics` 返回 Prometheus text format，包含 ops service、health check、load、memory、disk、uptime 和 process count 指标。它仍然需要 `OPS_TOKEN`，可以给 Prometheus、Uptime Kuma 或其他外部监控通过 header 抓取。

`/_ops/process-env?service=plugin-daemon` 用于排查 Supervisor 进程和 plugin runtime 子进程是否继承了关键安全配置。它只接受固定 service 白名单，只读取 `/proc/<pid>/environ` 中的固定 safe keys，并且只返回 secret presence boolean，不返回 secret 原文。排查插件请求超时时，重点看 `process.safe_values.MAX_REQUEST_TIMEOUT` 和 `children[].safe_values.MAX_REQUEST_TIMEOUT` 是否符合 `PLUGIN_MAX_REQUEST_TIMEOUT`。如果插件 runtime 已经脱离 Supervisor 子进程树，使用 `/_ops/process-env?service=plugin-daemon&runtime_scan=true` 额外扫描匹配 Dify 插件 runtime 形态的 Python 进程；该扫描不返回 raw cmdline、cwd 或 secret 原文，只返回 safe env keys、secret presence、`pid`、`ppid`、`comm` 和匹配原因。需要核对 live 插件 venv 时，加 `runtime_inspect=true`；返回内容仅包含 dist-info 版本、固定 timeout marker、文件 hash 和 `.env` safe keys，不返回源码、raw path 或 secret。`with-plugin-env` 会清理继承自宿主 API venv 的 `VIRTUAL_ENV`，正常情况下 plugin runtime 不应再显示 `/app/api/.venv`。

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

`sandbox`、`dify-web`、`ops-service` 和 `admin-service` 当前由 supervisor 直接写到容器 stdout/stderr，主要通过 Hugging Face App logs 查看；`/_ops/logs` 暂不暴露它们的专用文件。这样 `ops-service` 本体不需要写 `/data`，只通过 `OPS_LOG_DIR` 只读读取其他服务日志。

迁移到其他程序时，可以保留默认白名单，也可以用 `OPS_LOG_SERVICES_JSON` 增加服务到相对日志文件名的映射：

```env
OPS_LOG_DIR=/var/log/my-app
OPS_LOG_SERVICES_JSON={"api":"api.log","worker":"worker.log"}
```

`OPS_LOG_SERVICES_JSON` 里的文件名必须是相对路径，不能使用绝对路径、`..`，也不能通过符号链接逃出 `OPS_LOG_DIR`，避免把日志查看能力扩展成任意文件读取。`OPS_LOG_TAIL_MAX_BYTES` 会限制单个日志读取量。
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
hf spaces info <space-id>
```

重点看：

```text
runtime.stage = RUNNING
runtime.raw.sha = <expected commit sha>
```

2. 运行 smoke。

```bash
OPS_TOKEN=your-configured-ops-token \
  scripts/hf-space-smoke.sh https://your-space.hf.space
```

3. 查看错误摘要。

```bash
curl -sS -H "X-Ops-Token: $OPS_TOKEN" \
  https://your-space.hf.space/_ops/errors
```

期望：

```json
{"ok": true, "matches": []}
```

4. 用真实浏览器打开 Space。

```text
https://your-space.hf.space/
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
hf spaces info <space-id>
hf spaces logs <space-id> -n 220
hf spaces logs <space-id> --build -n 220
```

刚推送后，`sha` 可能先更新，但 `runtime.raw.sha` 仍是旧值；只有 `runtime.stage=RUNNING` 且 `runtime.raw.sha` 切到目标提交，才代表新镜像已接管流量。

## Plugin Daemon Migration

Plugin Daemon 需要在启动 server 前执行数据库迁移：

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

## Plugin Runtime Not Found

如果保存模型 provider、获取 parameter rules 或校验 credential 时出现下面日志：

```text
no plugin available nodes found plugin=<author/name:version@hash>
no available node, plugin runtime not found
no plugin states found in redis hashed_plugin_id=<hash>
```

在本 all-in-one 单容器里，`node` 优先理解为 Plugin Daemon 管理的插件 runtime 实例，而不是另一台 Plugin Daemon 服务器。这个错误表示 Dify API 能请求到 Plugin Daemon，但目标插件的 local runtime 没有注册为可调度实例。

排障时按三层状态分开看：

| 层 | 典型位置 | 含义 |
| --- | --- | --- |
| Dify 主库 | `provider_models`、`provider_model_credentials`、`provider_model_settings` | 模型配置和 credential；页面能读到已有模型通常说明这层仍在 |
| Plugin 安装元数据 | `dify_plugin` 数据库中的 plugin、installation、model installation 记录 | 决定插件是否被认为已安装 |
| Plugin local runtime | `/data/plugin_daemon/plugin`、`/data/plugin_daemon/plugin_packages`、`/data/plugin_daemon/cwd`、Plugin Daemon `local runtime ready` 日志、Redis runtime state | 决定插件进程是否已展开、启动并可被路由 |

本工程的 bucket-lite 布局会持久化 `/data/plugin_daemon/plugin_packages` 到 `/persist/plugin_daemon/plugin_packages`，并持久化 `/data/plugin_daemon/plugin` 到 `/persist/plugin_daemon/plugin`。前者是 package cache，后者是 local runtime watchdog 启动时枚举的 installed bucket。bucket-lite 下 Plugin Daemon 的 `PLUGIN_STORAGE_LOCAL_ROOT` 默认会指向真实目录 `/persist/plugin_daemon`，而不是 `/data/plugin_daemon`；这是为了避免 Go `filepath.WalkDir` 在扫描 `/data/plugin_daemon/plugin` 这个 symlink root 时不下钻，导致重建后 installed 文件明明存在但 runtime 不会 relaunch。local package upload 会先写 package bucket，后续安装流程再把包复制到 installed bucket、写安装元数据并启动 runtime。仅重新上传同一个 `.difypkg` 不一定修复已损坏的安装状态，因为数据库可能仍认为插件已安装，从而跳过完整 runtime install / launch 流程。

插件 Python 环境初始化还依赖 uv cache。`with-plugin-env` 会把 `UV_CACHE_DIR` 固定到 `PLUGIN_UV_CACHE_DIR`，默认 `${RUNTIME_ROOT}/plugin-uv-cache`，并在 Plugin Daemon 启动前确认目录可写。如果日志出现 `failed to initialize cache at /home/user/.cache/uv`、`sdists-v9/.git` 或 `Permission denied`，说明进程仍在回落到不可控的 home cache，优先检查当前镜像是否包含 `PLUGIN_UV_CACHE_DIR` 修复，而不是只重试安装插件。

推荐恢复路径：

1. 确认使用同一个插件包，例如 `langgenius/openai_api_compatible:<version>@<checksum>` 对应的 `.difypkg`。
2. 如果刚部署了 storage-root 修复，先用 `/_admin/api/actions/restart-service` 重启 `plugin-daemon`，等待日志出现 `local runtime starting` / `local runtime ready`。
3. 如果 `missing_installed_files` 非空，或重启后仍没有 `local runtime ready` 证据，再在 Dify 插件页面卸载损坏的插件。
4. 重新从本地 `.difypkg` 安装插件。
5. 等待安装任务完成，并让 Plugin Daemon 重新拉起 runtime。
6. 回到模型 provider 页面保存 credential 或模型参数。
7. 再看 `/_ops/persistence`、`/_ops/errors` 和 `plugin-daemon` 日志确认没有新的 runtime 初始化错误。

如果卸载再安装后模型配置和 key 仍可见，这是正常现象：OpenAI API compatible 这类自定义模型的模型配置可能保留在 Dify 主库中，插件卸载主要修复的是插件安装元数据、local package、installed bucket 和 runtime 注册状态。不要优先手动修改模型表。

不要通过后台简单复制 package bucket 到 installed bucket 来修复。那会绕开 Plugin Daemon 的安装任务、数据库状态更新、依赖初始化和 `LaunchLocalPlugin` 等流程，只能制造“文件看起来在，但 runtime 仍没注册”的假恢复。

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
scripts/hf-space-smoke.sh https://your-space.hf.space
```

如果目标实例已经开启 `/_admin`，使用：

```bash
SMOKE_ADMIN_ENABLED=true \
ADMIN_TOKEN=<admin-token> \
OPS_TOKEN=your-configured-ops-token \
scripts/hf-space-smoke.sh https://your-space.hf.space
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
admin-status        # 仅 SMOKE_ADMIN_ENABLED=true 时
admin-actions       # 仅 SMOKE_ADMIN_ENABLED=true 时
admin-audit         # 仅 SMOKE_ADMIN_ENABLED=true 时
admin-run-health-checks # 仅 SMOKE_ADMIN_ENABLED=true 且 SMOKE_ADMIN_ACTIONS=true 时
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

涉及执行迁移、清理缓存、SQL、配置修改等新写操作时，仍应放在 `/_admin/*`，并继续使用独立 `ADMIN_TOKEN`、白名单 action、`confirm=true`、cookie session CSRF、审计日志和 action id / result。不要把任意 shell command 放进请求参数；`/_ops` 不再提供 command 探针。WebSSH 或 interactive shell 已从 runtime 中移除，不应恢复为默认能力。
