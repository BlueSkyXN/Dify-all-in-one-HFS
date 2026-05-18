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
/_ops/config
/_ops/version
/_ops/errors
/_ops/logs?service=<service>&lines=<n>
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

`?token=` 适合临时调试，不适合长期使用，因为 URL 可能进入浏览器历史或代理日志。CLI 和自动化脚本优先使用 `X-Ops-Token`。

## 配置项

默认值位于 `docker/dify.env.runtime`：

```env
OPS_HOST=127.0.0.1
OPS_PORT=8081
OPS_TOKEN=dify_ops_demo_token
OPS_LOG_LINES_MAX=1000
```

公开 Space 建议在 Space Settings -> Variables 中覆盖：

```env
OPS_TOKEN=<fixed-random-token>
```

`OPS_TOKEN` 只适合演示和轻量诊断，不应当被当成生产级安全边界。公开场景建议同时将 Space 设置为 Private 或 Protected。

## 健康检查语义

`/healthz` 是对外综合健康探针，内部实际由 `ops-service` 执行以下检查：

```text
postgres          pg_isready
redis             redis-cli ping
plugin-daemon     TCP 127.0.0.1:5002
sandbox           TCP 127.0.0.1:8194
dify-api-health   HTTP 127.0.0.1:5001/health
dify-web          HTTP 127.0.0.1:3000/apps
nginx             HTTP 127.0.0.1:7860/nginx-health
dify-setup        HTTP 127.0.0.1:5001/console/api/setup
dify-init         HTTP 127.0.0.1:5001/console/api/init
```

`/_ops/health` 会额外返回：

- supervisor 进程状态
- Dify / Space 版本摘要
- 每个探针的耗时、HTTP 状态和短样本

刚发布后，Dify Web 和 API 可能需要几十秒到数分钟 warmup。`scripts/hf-space-smoke.sh` 默认会重试，避免把短暂 502 或 timeout 当作最终失败。

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
plugin-daemon
plugin-daemon.err
dify-api
dify-api.err
dify-worker
dify-worker.err
dify-beat
dify-beat.err
nginx
ops-service
ops-service.err
```

`dify-web` 当前由 supervisor 直接写到容器 stdout/stderr，主要通过 Hugging Face App logs 查看；`/_ops/logs` 暂不暴露 `dify-web` 专用文件。

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
http_user_agent
```

这些字段用于判断 502 来自 Nginx 本身、Dify Web、Dify API，还是上游进程尚未 ready。

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
OPS_TOKEN=dify_ops_demo_token \
  scripts/hf-space-smoke.sh https://blueskyxn-dify-all-in-one.hf.space
```

3. 查看错误摘要。

```bash
curl -sS -H "X-Ops-Token: dify_ops_demo_token" \
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
OPS_TOKEN=dify_ops_demo_token \
SMOKE_RETRIES=60 \
SMOKE_DELAY=5 \
scripts/hf-space-smoke.sh https://blueskyxn-dify-all-in-one.hf.space
```

脚本当前检查：

```text
web-root
nginx-health
ops-healthz
setup-api
init-api
ops-health
ops-errors
```

`ops-errors` 当前只验证 endpoint 可访问，人工排障时仍建议查看 JSON 中的 `ok` 和 `matches`。

## 后续可扩展方向

当前运维能力是只读诊断层。后续如果要做管理面板，可以优先考虑：

- 将 `/_ops/` HTML 首页改成更完整的状态面板。
- 增加按 service / severity / keyword 过滤日志。
- 将 `/_ops/errors` 按最近时间窗口聚合，而不是只按 tail 行匹配。
- 增加 build/runtime SHA 展示和版本漂移提示。
- 增加只读数据库 schema 检查，例如 plugin-daemon 必需表是否存在。
- 增加显式 warmup 状态，区分启动中和真正失败。
- 增加只读 Prometheus-style metrics endpoint，供外部监控抓取。

涉及重启服务、修改配置、执行迁移、清理数据等写操作时，应单独设计鉴权、审计日志和操作确认，不要直接放进现有 `OPS_TOKEN` 诊断入口。
