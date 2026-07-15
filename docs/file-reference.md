# File Reference

本文档逐一说明仓库中受版本控制文件的职责、输入输出和修改注意事项。

## Root Files

### `AGENTS.md`

Codex 根级 router 和项目指令。

职责：

- 记录本仓库的 demo 定位、目录导航、真实命令面、全局不变量和验证标准。
- 提醒后续 Agent 在 push、merge 或对比前先看 `git remote -v`。
- 约束 `docker/` 修改前读取 `docker/AGENTS.md`。

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
- 安装系统依赖、PostgreSQL、pgvector、Nginx、Supervisor、Redis、Node.js和 uv。
- 注入 `DIFY_AIO_BUILD_*` 构建元数据，供 `/_ops/version` 只读展示。
- 创建 rootless runtime user。
- 复制 runtime scripts、Nginx、Supervisor、ops-service 和 admin-service。
- 声明 `HEALTHCHECK` 和最终 `ENTRYPOINT`。

关键 build args：

```text
BASE_IMAGE_REF
DIFY_API_IMAGE_REF
DIFY_WEB_IMAGE_REF
PLUGIN_DAEMON_IMAGE_REF
SANDBOX_IMAGE_REF
DIFY_SOURCE_REPO
DIFY_SOURCE_MAIN_REF
DIFY_AGENT_SOURCE_REF
DIFY_UPSTREAM_MAIN_REF
DIFY_SANDBOX_SOURCE_REF
UV_VERSION
DIFY_VERSION
```

`*_IMAGE_REF` 和 `BASE_IMAGE_REF` 是真实 `FROM` selector；`DIFY_SOURCE_MAIN_REF` 记录 maintained self fork main commit；`DIFY_AGENT_SOURCE_REF` 是独立 `/opt/dify-agent/.venv` 安装 `dify-agent` backend package 的 source pin；`DIFY_UPSTREAM_MAIN_REF` 记录 Web/API official main image 的源码 commit；`DIFY_SANDBOX_SOURCE_REF` 是 NEXT patched Sandbox server binary 的 source pin。NEXT branch 默认值已 pin 到 Docker Hub main digest、official upstream image ref 和 self fork source set；更新上游、更新 fork main 或回到稳定版时必须作为一组 co-pin 修改。`DIFY_VERSION` 只作为 metadata，不再决定 Dify Web/API 镜像来源或 Agent package 来源。

### `.dockerignore`

控制 Docker build context，避免把无关本地文件传入构建。

### `hfs-dev.toml`

HFS alignment manifest。

职责：

- 声明本仓库为 Pattern A / HFS Port Repository。
- 声明 runtime 获取模式为 image-assembly。
- 声明 repo root 是 Space root。
- 通过结构化 `[[release_pins]]` 列出发布态 pin contract 和 HFS required files，供标准 checker 与 `scripts/validate-hfs-contract.sh` 检查。

### `.gitattributes`

Git 属性配置。

### `.gitignore`

忽略本地 generated/cache 文件和 `.env.local`。

### `.github/workflows/static-check.yml`

GitHub Actions 轻量静态检查 workflow。

职责：

- 在 PR 和 `main` push 时运行 `scripts/static-check.sh`。
- 只使用 `contents: read` 权限。
- 不执行 Docker build、Hugging Face CLI 或 live smoke。

### `LICENSE`

项目许可证。

## `docker/`

### `docker/AGENTS.md`

`docker/` 子目录 navigation card。

职责：

- 记录 runtime 目录的高风险点、不变量和最小验证命令。
- 提醒修改 `docker/` 前重点核对 entrypoint、env、Supervisor、Nginx、ops/admin 服务和 wrappers。

### `docker/dify.env.runtime`

运行时默认环境变量。

职责：

- 保留已有 Docker/HF env。
- 为 Dify API/Web/Worker/Beat、OpenAPI、Agent backend、PostgreSQL、Redis、Storage、pgvector、Sandbox、Plugin Daemon、Nginx 和 Ops Service 设置默认值。
- 为 Admin Service 设置默认值。
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

### `docker/sandbox-python-requirements.txt`

Sandbox Python 依赖清单。

职责：

- 定义 Dify Workflow Code Node 常用 Python 包。
- 在 `Dockerfile` build 阶段复制为 `/dependencies/python-requirements.txt`。
- 配合 build-time `pip install` 和 `pip check`，让 demo runtime 不依赖现场下载这些包。

修改注意：

- 新增或升级包后，至少验证目标 Python 版本和 manylinux wheel 可下载。
- 依赖清单服务于 demo 便利性，不代表生产 Sandbox 依赖治理方案。

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

- 定义 postgres、redis、postgres-backup、plugin-daemon、sandbox、shellctl、dify-agent、dify-api、dify-worker、dify-beat、dify-web、ops-service、admin-service、nginx。
- 定义 admin-service，默认由 `ADMIN_ENABLED=false` 返回 404。
- 设置启动 priority、autorestart、日志路径。
- 暴露 supervisor unix socket：`/data/run/supervisor.sock`。

### `docker/nginx.conf`

Nginx 路由和日志配置。

职责：

- 监听 `7860`。
- 输出 JSON access log。
- 将路径代理到 Web/API/Plugin/Ops/Admin。
- 暴露 `/nginx-health`。
- 隐藏上游 `X-Frame-Options`，并设置允许 Hugging Face iframe 的 `Content-Security-Policy frame-ancestors`。

### `docker/ops_service.py`

只读运维诊断服务。

职责：

- 监听 `OPS_HOST:OPS_PORT`，默认 `127.0.0.1:8081`。
- 提供 `/healthz`、`/readyz`、`/health`、`/status`、`/system`、`/config`、`/version`、`/logs`、`/errors`、`/metrics`。
- 使用 `OPS_TOKEN` 鉴权保护非公开 endpoint。
- 默认 demo token 未显式允许时进入 locked mode；dashboard 使用 signed HttpOnly cookie，不在 HTML/JS 中内联完整 token。
- 首页是单文件 HTML/CSS/原生 JS dashboard，不需要前端构建。
- 支持通过 `OPS_EXTRA_*_CHECKS_JSON` 增加 HTTP、TCP 和只读 command 健康探针。
- 返回 CPU load、memory、disk、uptime 和 process count 的只读系统摘要。
- 通过 `/_ops/version` 返回 build image 来源和 Sandbox requirements 摘要。
- 返回 Prometheus-style text metrics。
- 通过 `OPS_LOG_DIR` 只读读取白名单日志，并允许用 `OPS_LOG_SERVICES_JSON` 扩展相对日志文件映射。
- 只返回 secret presence，不返回 secret 原文。
- 按 service 分组错误摘要，显示匹配 pattern，并限制扫描与返回行数。
- 过滤已知启动期 benign error pattern，避免把短暂 warmup 误报成当前异常。
- `/_ops/` dashboard 支持 English / 中文切换，默认跟随浏览器语言，并把选择保存在浏览器本地。

### `docker/admin_service.py`

默认关闭的受控管理服务。

职责：

- 监听 `ADMIN_HOST:ADMIN_PORT`，默认 `127.0.0.1:8082`。
- `ADMIN_ENABLED=false` 时所有入口返回 404。
- 使用 `ADMIN_TOKEN`、signed HttpOnly cookie、cookie session CSRF、登录失败 audit 和内存级限速保护管理入口。
- 提供 `/api/status`、`/api/actions` 和白名单 action：restart service、reload nginx、run health checks、force postgres backup。
- 可选提供 `/_admin/api/files/*` 文件管理；path 限制在 `ADMIN_FILES_ROOT` 内。
- rename/delete 由 `ADMIN_FILES_DESTRUCTIVE_ENABLED` 单独 gate。
- 写入 `ADMIN_AUDIT_LOG`，并通过 `/api/audit` 鉴权只读展示最近审计事件；不记录 token、secret 或文件内容。
- 登录页和管理 dashboard 支持 English / 中文切换，默认跟随浏览器语言，并把选择保存在浏览器本地。

### `docker/postgres-backup-loop`

bucket-lite PostgreSQL dump 备份循环。

职责：

- 在 bucket-lite 或显式开启备份时等待 PostgreSQL ready。
- 周期执行 `pg_dumpall --no-role-passwords`，也支持 `--once` 做部署或重启前的一次性备份。
- 写入 timestamped dump，校验后更新 `${POSTGRES_BACKUP_DIR}/latest.sql.gz`、`latest.created_at` 和 `latest.sha256`，并按 `POSTGRES_BACKUP_RETENTION_POLICY` / `POSTGRES_BACKUP_RETAIN_COUNT` 清理旧备份。
- 用 `${POSTGRES_BACKUP_DIR}/.backup.lock` 串行化自动、手动和退出前备份；默认 `POSTGRES_BACKUP_COMPRESSION_LEVEL=1`，优先快速落盘。
- `EXTERNAL_POSTGRES_ENABLED=true` 时默认 disabled，外部数据库备份交给托管 PostgreSQL。

### `docker/run-postgres`

Supervisor 的 PostgreSQL 启动包装器。

职责：

- 默认启动本地 `/data/postgres` PostgreSQL。
- `EXTERNAL_POSTGRES_ENABLED=true` 时保持 idle，避免在同一容器内再启动本地 PostgreSQL。

### `docker/with-dify-env`

Dify API/Web/Worker/Beat 的环境包装器。

职责：

- source runtime defaults 和 generated secrets。
- 确保 `/app/api/.venv/bin` 在 `PATH` 中。
- `DIFY_AGENT_ENABLED=true` 时派生 `AGENT_BACKEND_BASE_URL`、URL-encoded `DIFY_AGENT_REDIS_URL`、`DIFY_AGENT_PLUGIN_DAEMON_API_KEY`、`DIFY_AGENT_INNER_API_URL`、`DIFY_AGENT_INNER_API_KEY` 和 `DIFY_AGENT_STUB_API_BASE_URL`；旧 `DIFY_AGENT_DIFY_API_*` / `DIFY_AGENT_STUB_URL` 只保留兼容映射。
- 执行传入命令。

### `docker/run-dify-agent`

NEXT Agent backend 启动脚本。

职责：

- `DIFY_AGENT_ENABLED=false` 时保持 supervisor program idle，不影响稳定 demo。
- `DIFY_AGENT_ENABLED=true` 时等待 Redis、Plugin Daemon、Dify API health，以及 `AGENT_SHELL_ENABLED=true` 时的 shellctl，按 `DIFY_AGENT_STARTUP_DELAY_SECONDS` 延迟，然后从独立 `/opt/dify-agent/.venv` 启动 `uvicorn dify_agent.server.app:app`。
- 只监听内部 `DIFY_AGENT_HOST:DIFY_AGENT_PORT`，默认 `127.0.0.1:5005`。

### `docker/run-shellctl`

NEXT Agent shell layer 启动脚本。

职责：

- `DIFY_AGENT_ENABLED=false` 或 `AGENT_SHELL_ENABLED=false` 时保持 supervisor program idle。
- 开启时从独立 `/opt/dify-agent/.venv` 执行 `shellctl serve --listen 127.0.0.1:5004`，并把 SQLite/tmux runtime 放到 `${RUNTIME_ROOT}/shellctl`。
- 只服务内部 loopback endpoint，不经 Nginx 暴露公网。

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
- `PLUGIN_MAX_REQUEST_TIMEOUT` -> `MAX_REQUEST_TIMEOUT`
- 固定 `UV_CACHE_DIR` 到 `PLUGIN_UV_CACHE_DIR`，并在启动前创建/校验可写目录，避免插件 Python venv 初始化回落到不可写的 `/home/user/.cache/uv`。
- `/opt/dify/plugin-runtime-patches` -> Plugin runtime `PYTHONPATH`

### `docker/plugin_runtime_patches/sitecustomize.py`

Plugin runtime 的 image-controlled timeout compatibility shim。

职责：

- 只改写 OpenAI-compatible SDK 精确的 `(10, MAX_REQUEST_TIMEOUT)` Requests timeout tuple。
- 使用 `PLUGIN_CONNECT_TIMEOUT_SECONDS` 提高 connect/TLS 上限，不读取或记录 provider credential。
- 官方 SDK 不再使用该固定 tuple 时自动不生效，不修改签名 `.difypkg` 或临时 venv。

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
plugin-daemon
```

用法：

```bash
wait-for-core postgres redis -- <command>
wait-for-core api -- <command>
wait-for-core redis plugin-daemon -- <command>
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
dify-all-in-one-hf-space:latest
```

脚本会白名单透传当前 shell 中已设置的 build args：

```text
BASE_IMAGE_REF
DIFY_API_IMAGE_REF
DIFY_WEB_IMAGE_REF
PLUGIN_DAEMON_IMAGE_REF
SANDBOX_IMAGE_REF
DIFY_SOURCE_REPO
DIFY_SOURCE_MAIN_REF
DIFY_AGENT_SOURCE_REF
DIFY_UPSTREAM_MAIN_REF
DIFY_SANDBOX_SOURCE_REF
DIFY_VERSION
UV_VERSION
```

### `scripts/run-demo.sh`

本地运行包装脚本。

默认：

```text
IMAGE_TAG=dify-all-in-one-hf-space:latest
CONTAINER_NAME=dify-aio-hf-demo
PUBLIC_URL=http://localhost:8080
volume=dify-hf-demo-persist:/persist
env-file=docker/dify.env.demo
```

脚本会额外透传当前 shell 中已设置的 `EXTERNAL_POSTGRES_*`、`DB_*`、`POSTGRES_BACKUP_*`、`OPS_TOKEN`、`ALLOW_DEMO_OPS_TOKEN`、`OPS_*` session/cache/cookie/timeout 变量和常用 `ADMIN_*` 开关，便于本地启动开启 admin 或外部 PostgreSQL 的临时 demo。

### `scripts/hf-space-smoke.sh`

线上或本地 smoke 脚本。

输入：

- 第一个参数：base URL。
- 或 `HF_SPACE_URL`。
- `OPS_TOKEN` 可选，用于检查 `/_ops`。
- 设置 `OPS_TOKEN` 时会额外验证 query token 迁移到 cookie-backed dashboard，且 HTML 不再包含完整 token。
- `ADMIN_TOKEN` + `SMOKE_ADMIN_ENABLED=true` 可选，用于检查已开启的 `/_admin`。
- `SMOKE_OPENAPI_ENABLED=true` 可选，用于检查 NEXT OpenAPI `/_health` 和 `/_version`。
- `SMOKE_RETRIES` 和 `SMOKE_DELAY` 控制重试。

检查：

```text
/
/apps header check: no X-Frame-Options, CSP frame-ancestors allows Hugging Face
/nginx-health
/healthz
/_admin/
/console/api/setup
/console/api/init
/openapi/v1/_health    # 仅 SMOKE_OPENAPI_ENABLED=true 时
/openapi/v1/_version   # 仅 SMOKE_OPENAPI_ENABLED=true 时
/_ops/health
/_ops/system
/_ops/metrics
/_ops/errors
```

### `scripts/admin-smoke.sh`

`/_admin` 专用 smoke 脚本。

职责：

- 默认验证 `ADMIN_ENABLED=false` 时 `/_admin/` 和 `/_admin/api/status` 返回 404。
- `ADMIN_EXPECTED_ENABLED=true` 时验证 root、token 鉴权、cookie session CSRF、action catalog、audit endpoint、`confirm=true` 和 file manager 边界。
- 默认不执行真实 admin action；只有 `ADMIN_SMOKE_ACTIONS=true` 时才调用 `run-health-checks`。

### `scripts/validate-hfs-contract.sh`

HFS 范式结构契约检查脚本。

职责：

- 验证 `hfs-dev.toml` 声明 Pattern A / image-assembly / repo-root。
- 检查 `README.md app_port`、`Dockerfile EXPOSE` 和 `docker/nginx.conf listen` 端口一致。
- 检查 Dockerfile 暴露 digest-capable `*_IMAGE_REF` / `BASE_IMAGE_REF`、默认 Web/API digest pair 与 `DIFY_VERSION` metadata，并拒绝旧的 `DIFY_API_IMAGE` / `DIFY_WEB_IMAGE` 加 `DIFY_VERSION` 拼接 selector。
- 检查 `SERVER_CONSOLE_API_URL` 的同容器 SSR 默认值、demo env 和显式覆盖语义。
- 检查多服务 runtime glue 位于 `docker/`，而不是把 Space root 藏进 `cloud/hfs/`。
- 检查 `.dockerignore` 排除 `local/`、`.env.local` 和常见 secret 文件。
- 检查 smoke 脚本覆盖 `/`、`/nginx-health`、`/healthz`、`/_ops/health` 和 shellctl 状态。

### `scripts/static-check.sh`

无额外依赖的本地静态检查入口。

职责：

- 对 `docker/` 和 `scripts/` 下所有 shell helper 运行 `bash -n`。
- 运行 `scripts/validate-hfs-contract.sh`。
- 对 `docker/ops_service.py` 和 `docker/admin_service.py` 运行 `python3 -m py_compile`。
- 使用 Python stdlib `unittest` 运行 `docker/tests/` 纯函数回归。
- 检查直接调用的 `scripts/*.sh` helper 保持 executable bit。
- 运行 `git diff --check`。
- 对 changed/untracked 文件额外检查 trailing whitespace，覆盖新文件未 staged 时 `git diff --check` 看不到的情况。

该脚本不替代 Docker build、local smoke 或 Hugging Face live smoke；它只是小改动和 PR 前的最小轻量 gate。

## `docs/`

### `docs/README.md`

完整文档索引。

### `docs/project-overview.md`

项目目标、非目标、设计取舍和目录结构。

### `docs/project-status-and-roadmap.md`

当前实现状态、未完成事项、下一步计划和本次审查循环记录。

### `docs/architecture.md`

组件拓扑、Nginx 路由、启动依赖、数据库布局和持久化目录。

### `docs/hfs-alignment.md`

记录本仓库对 `hfs-dev` 范式的分类、目录主权、runtime 获取模式、已满足 contract 和发布态 gap。

### `docs/runtime-lifecycle.md`

Docker build、entrypoint 初始化、supervisord 生命周期和 migration 顺序。

### `docs/configuration.md`

环境变量、默认值、Secrets、Space Variables 和配置覆盖规则。

### `docs/deployment.md`

Hugging Face Space 部署、本地 Docker 运行、发布后 smoke 和 runtime 状态确认。

### `docs/release-checklist.md`

GitHub PR、`main`、Hugging Face Space runtime 和 smoke 的发布证据记录模板。

### `docs/bucket-lite-drill.md`

`/persist` bucket-lite 持久化演练模板。

职责：

- 记录本地 Docker 和 Hugging Face Space 两类演练入口。
- 覆盖 `/data/config/generated.env` 重启保留、PostgreSQL fallback 和 dump backup 检查。
- 提供 evidence template，避免把未执行的持久化场景写成已验证。

### `docs/ops-runbook.md`

运维诊断、日志、健康检查、502 排障和发布验收。

### `docs/development.md`

开发流程、修改点、验证命令和提交前检查。

### `docs/security.md`

演示环境安全边界、公开 Space 风险和生产化注意事项。
