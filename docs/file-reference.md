# File Reference

本文档逐一说明仓库中受版本控制文件的职责、输入输出和修改注意事项。

## Root Files

### `README.md`

Hugging Face Space card 和项目首页。

职责：

- 提供 Space metadata：`sdk: docker`、`app_port: 7860`。
- 介绍项目目标、组件布局、部署方式、本地运行、数据目录和运维入口。
- 链接到完整 docs。

修改注意：

- 顶部 YAML 会被 Hugging Face 读取，改动前确认 Space metadata 语义。
- `app_port` 必须和 Nginx listen 端口保持一致。

### `README.hf-space.md`

Hugging Face Space 专用部署说明。

职责：

- 记录 Space Settings 建议。
- 给出 Variables / Secrets 建议。
- 提供基本运维诊断命令。

### `Dockerfile`

Docker Space 构建入口。

职责：

- 复用官方 Dify Web/API/Plugin/Sandbox 镜像。
- 安装系统依赖、PostgreSQL、pgvector、Nginx、Supervisor、Redis、Node.js、uv。
- 创建 rootless runtime user。
- 复制 runtime scripts、Nginx、Supervisor、ops-service。
- 声明 `HEALTHCHECK` 和最终 `ENTRYPOINT`。

关键 build args：

```text
DIFY_VERSION
UV_VERSION
DIFY_API_IMAGE
DIFY_WEB_IMAGE
PLUGIN_DAEMON_IMAGE
SANDBOX_IMAGE
```

### `.dockerignore`

控制 Docker build context，避免把无关本地文件传入构建。

### `.gitattributes`

Git 属性配置。

## `docker/`

### `docker/dify.env.runtime`

运行时默认环境变量。

职责：

- 保留已有 Docker/HF env。
- 为 Dify API/Web/Worker/Beat、PostgreSQL、Redis、Storage、pgvector、Sandbox、Plugin Daemon、Nginx 和 Ops Service 设置默认值。
- 被 `entrypoint.sh`、`with-*` wrapper 和 `wait-for-core` source。

修改注意：

- 只在变量确实被上游服务或本仓库脚本读取时添加。
- 新增变量需要同步文档和 demo env。

### `docker/dify.env.demo`

本地 `docker run --env-file` 示例。

职责：

- 提供本地演示默认值。
- 不用于生产。
- 密钥默认留空，由 entrypoint 生成。

### `docker/entrypoint.sh`

容器主入口。

职责：

- 准备 `/data`、`/conf`、`/dependencies`，并在 `/persist` 是挂载点且可写时启用 bucket-lite 映射。
- 生成或复用 `/data/config/generated.env`。
- 渲染 Redis 和 Sandbox 配置。
- 初始化 PostgreSQL、数据库、role 和 pgvector。
- 启动 temporary Redis 供 Dify migration 使用。
- 执行 Dify API migration。
- 启动 supervisord。

关键函数：

```text
prepare_dirs
configure_bucket_layout
write_generated_env
render_redis_config
render_sandbox_config
init_postgres
run_dify_migration
main
```

### `docker/supervisord.conf`

长期运行进程编排。

职责：

- 定义 postgres、redis、postgres-backup、plugin-daemon、sandbox、dify-api、dify-worker、dify-beat、dify-web、ops-service、nginx。
- 设置启动 priority、autorestart、日志路径。
- 暴露 supervisor unix socket：`/data/run/supervisor.sock`。

### `docker/nginx.conf`

Nginx 路由和日志配置。

职责：

- 监听 `7860`。
- 输出 JSON access log。
- 将路径代理到 Web/API/Plugin/Ops。
- 暴露 `/nginx-health`。

### `docker/ops_service.py`

只读运维诊断服务。

职责：

- 监听 `OPS_HOST:OPS_PORT`，默认 `127.0.0.1:8081`。
- 提供 `/healthz`、`/readyz`、`/health`、`/status`、`/system`、`/config`、`/version`、`/logs`、`/errors`、`/metrics`。
- 使用 `OPS_TOKEN` 鉴权保护非公开 endpoint。
- 首页是单文件 HTML/CSS/原生 JS dashboard，不需要前端构建。
- 支持通过 `OPS_EXTRA_*_CHECKS_JSON` 增加 HTTP、TCP 和只读 command 健康探针。
- 返回 CPU load、memory、disk、uptime 和 process count 的只读系统摘要。
- 返回 Prometheus-style text metrics。
- 通过 `OPS_LOG_DIR` 只读读取白名单日志，并允许用 `OPS_LOG_SERVICES_JSON` 扩展相对日志文件映射。
- 只返回 secret presence，不返回 secret 原文。
- 按 service 分组错误摘要，显示匹配 pattern，并限制扫描与返回行数。
- 过滤已知启动期 benign error pattern，避免把短暂 warmup 误报成当前异常。

### `docker/with-dify-env`

Dify API/Web/Worker/Beat 的环境包装器。

职责：

- source runtime defaults 和 generated secrets。
- 确保 `/app/api/.venv/bin` 在 `PATH` 中。
- 执行传入命令。

### `docker/with-plugin-env`

Plugin Daemon 环境包装器。

职责：

- source runtime defaults 和 generated secrets。
- 把本项目变量映射成 Plugin Daemon 期望的变量，例如：
  - `DB_PLUGIN_DATABASE` -> `DB_DATABASE`
  - `PLUGIN_DAEMON_PORT` -> `SERVER_PORT`
  - `PLUGIN_DAEMON_KEY` -> `SERVER_KEY`
  - `PLUGIN_DIFY_INNER_API_URL` -> `DIFY_INNER_API_URL`
  - `PLUGIN_DIFY_INNER_API_KEY` -> `DIFY_INNER_API_KEY`

### `docker/with-sandbox-env`

Sandbox 环境包装器。

职责：

- source runtime defaults 和 generated secrets。
- 设置 Sandbox 期望的 `API_KEY`、`GIN_MODE`、`WORKER_TIMEOUT` 等变量。
- 清理并重建 `/var/sandbox/sandbox-python`，避免 rootless 重启时残留只读文件导致初始化失败。
- 默认把 `PYTHON_DEPS_UPDATE_INTERVAL` 设为长间隔，避免上游 Sandbox 周期刷新重复覆盖只读 rootfs 文件。

### `docker/wait-for-core`

依赖等待脚本。

支持依赖：

```text
postgres
redis
api
```

用法：

```bash
wait-for-core postgres redis -- <command>
wait-for-core api -- <command>
```

### `docker/healthcheck.sh`

Docker HEALTHCHECK 脚本。

检查：

```text
http://127.0.0.1:5001/health
http://127.0.0.1:8081/healthz
http://127.0.0.1:7860/
```

## `scripts/`

### `scripts/build.sh`

本地构建包装脚本。

默认镜像 tag：

```text
dify-all-in-one-hf-space:1.14.1
```

### `scripts/run-demo.sh`

本地运行包装脚本。

默认：

```text
CONTAINER_NAME=dify-aio-hf-demo
PUBLIC_URL=http://localhost:8080
volume=dify-hf-demo-persist:/persist
env-file=docker/dify.env.demo
```

### `scripts/hf-space-smoke.sh`

线上或本地 smoke 脚本。

输入：

- 第一个参数：base URL。
- 或 `HF_SPACE_URL`。
- `OPS_TOKEN` 可选，用于检查 `/_ops`。
- `SMOKE_RETRIES` 和 `SMOKE_DELAY` 控制重试。

检查：

```text
/
/nginx-health
/healthz
/_admin/
/console/api/setup
/console/api/init
/_ops/health
/_ops/system
/_ops/metrics
/_ops/errors
```

## `docs/`

### `docs/README.md`

完整文档索引。

### `docs/project-overview.md`

项目目标、非目标、设计取舍和目录结构。

### `docs/architecture.md`

组件拓扑、Nginx 路由、启动依赖、数据库布局和持久化目录。

### `docs/runtime-lifecycle.md`

Docker build、entrypoint 初始化、supervisord 生命周期和 migration 顺序。

### `docs/configuration.md`

环境变量、默认值、Secrets、Space Variables 和配置覆盖规则。

### `docs/deployment.md`

Hugging Face Space 部署、本地 Docker 运行、发布后 smoke 和 runtime 状态确认。

### `docs/ops-runbook.md`

运维诊断、日志、健康检查、502 排障和发布验收。

### `docs/development.md`

开发流程、修改点、验证命令和提交前检查。

### `docs/security.md`

演示环境安全边界、公开 Space 风险和生产化注意事项。
