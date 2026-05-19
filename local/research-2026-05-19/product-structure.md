# 产品结构（PBS）

本视图描述仓库实际“交付了什么”，而不是理想化架构图。

## 顶层子系统

| Subsystem | Path / location | Role | Tech stack |
|---|---|---|---|
| PBS-001 镜像构建与上游资产接入 | `Dockerfile` | 从官方 Dify 镜像和系统包组装最终 runtime image | Docker multi-stage, Debian, Python |
| PBS-002 启动初始化与环境合同 | `docker/entrypoint.sh`, `docker/dify.env.*`, `docker/with-*` | 负责 env、secret、目录、数据库、wrapper 语义 | Bash |
| PBS-003 进程与网络平面 | `docker/supervisord.conf`, `docker/nginx.conf`, `docker/wait-for-core`, `docker/healthcheck.sh` | 管理长期进程、端口暴露、依赖等待与健康检查 | Supervisor, Nginx, Bash |
| PBS-004 Operator surface | `docker/ops_service.py`, `docker/admin_service.py`, `docker/webssh_entrypoint.sh` | 只读诊断面、默认关闭管理面、terminal placeholder | Python stdlib, Bash |
| PBS-005 本地/远端验证与文档 | `scripts/`, `README*.md`, `docs/` | build/run/smoke wrappers 与人类使用说明 | Bash, Markdown |

## Modules and components

### PBS-001 镜像构建与上游资产接入

| Module / component | Path | Responsibility | Notes |
|---|---|---|---|
| `web-builder` | `Dockerfile:27-32` | 校验并复制官方 Dify Web 构建产物 | 不在仓库内重新 build 前端 |
| `api-image` | `Dockerfile:37-42` | 校验并复制官方 Dify API 与 `.venv` | 保持 `/app/api` 路径不变 |
| `plugin-daemon-image` / `sandbox-image` | `Dockerfile:48-49` | 复制 plugin daemon 与 sandbox runtime | 上游资产直接消费 |
| runtime package install | `Dockerfile:80-108` | 安装 Node.js、PostgreSQL、Redis、Nginx、Supervisor、uv | 没有 lockfile |
| runtime filesystem layout | `Dockerfile:141-185` | 安装脚本、配置、创建 `/data` `/persist` `/tmp/dify-aio` 等目录 | 运行时 contract 的物理载体 |

### PBS-002 启动初始化与环境合同

| Module / component | Path | Responsibility | Notes |
|---|---|---|---|
| runtime defaults | `docker/dify.env.runtime` | 所有服务的默认 env source | 通过 `${VAR:-default}` 保持外部 env 优先 |
| local demo env | `docker/dify.env.demo` | 本地 `docker run --env-file` 示例 | Demo 专用，不是生产配置 |
| main entrypoint | `docker/entrypoint.sh` | 目录准备、generated secrets、PostgreSQL、Redis/Sandbox config、migration | 核心 bootstrap |
| plugin wrapper | `docker/with-plugin-env` | 把 repo 命名空间转换成 plugin-daemon 期望变量 | 包括 DB/Redis/plugin paths |
| sandbox wrapper | `docker/with-sandbox-env` | 生成 Sandbox 运行环境并清理 rootless 残留目录 | 默认无网络 |
| postgres backup loop | `docker/postgres-backup-loop` | bucket-lite 时定期产出 `latest.sql.gz` | `pg_dumpall` dump，不是 WAL 方案 |

### PBS-003 进程与网络平面

| Module / component | Path | Responsibility | Notes |
|---|---|---|---|
| supervisor process graph | `docker/supervisord.conf` | 定义 Postgres/Redis/Plugin/API/Worker/Beat/Web/Ops/Admin/Nginx/Web terminal | 日志大多写 `/data/logs` 或 stdout/stderr |
| dependency waiter | `docker/wait-for-core` | 在 service 启动前等待 `postgres` / `redis` / `api` | 纯本地探针 |
| public reverse proxy | `docker/nginx.conf` | 把 `7860` 路由到 Web/API/Plugin/Ops/Admin | 同时负责 HF iframe headers |
| healthcheck | `docker/healthcheck.sh` | Docker HEALTHCHECK 脚本 | 检查 API、`/healthz` 和 `/` |

### PBS-004 Operator surface

| Module / component | Path | Responsibility | Notes |
|---|---|---|---|
| read-only ops service | `docker/ops_service.py` | 健康、状态、资源、配置摘要、metrics、日志、错误摘要 | 仅标准库，无额外框架 |
| controlled admin service | `docker/admin_service.py` | 登录、CSRF、动作白名单、文件边界、审计日志 | 默认 `ADMIN_ENABLED=false` |
| web terminal placeholder | `docker/webssh_entrypoint.sh` | 在未启用或缺少 `ttyd` 时返回 404/503 placeholder | 不是实终端实现 |

### PBS-005 本地/远端验证与文档

| Module / component | Path | Responsibility | Notes |
|---|---|---|---|
| build wrapper | `scripts/build.sh` | 统一本地 build 命令 | 只有一行 `docker build` 封装 |
| local run wrapper | `scripts/run-demo.sh` | 启动本地 demo 容器 | 会删除同名容器 |
| smoke script | `scripts/hf-space-smoke.sh` | 检查 public/ops/admin-disabled/admin-enabled 路径 | 带重试与 header 校验 |
| docs index | `docs/README.md` | 文档阅读入口 | 串联全套 runbook |
| deployment/ops/dev/security docs | `docs/*.md` | 定义配置、排障、验证和安全边界 | 人类运维主入口 |

## 外部集成

| Integration | Where it is wired | Direction | Auth / contract |
|---|---|---|---|
| Hugging Face Docker Space runtime | `README.md:67-84`, `docker/dify.env.runtime:34-39` | inbound runtime env + outbound app hosting | `SPACE_HOST`, `sdk: docker`, `app_port: 7860` |
| Hugging Face persistent storage | `README.hf-space.md:43-64`, `docker/entrypoint.sh:171-211` | mounted filesystem | `/persist` contract |
| 官方 Dify images | `Dockerfile:17-22`, `Dockerfile:27-49` | build-time inbound | image tag / build arg |
| Plugin Marketplace | `docker/dify.env.runtime:137-139`, `docker/dify.env.runtime:209` | outbound HTTP | `MARKETPLACE_URL`, `MARKETPLACE_API_URL` |
| Docker daemon / local container runtime | `scripts/build.sh:1-4`, `scripts/run-demo.sh:8-16` | local execution | `docker build`, `docker run` |
| Hugging Face CLI | `docs/deployment.md:53-79`, `docs/ops-runbook.md:292-307` | operator CLI outbound | `hf spaces info/logs` |

## Runtime artifacts

| Artifact | Build origin | Where it runs | Distribution |
|---|---|---|---|
| `dify-all-in-one-hf-space:<tag>` image | `Dockerfile` | local Docker / HF Space | local daemon or HF build |
| `/data/config/generated.env` | `docker/entrypoint.sh` | container filesystem or `/persist/config` | runtime-generated |
| `/persist/postgres-backups/latest.sql.gz` | `docker/postgres-backup-loop` | bucket-lite persistence | runtime-generated |
| JSON Nginx access log | `docker/nginx.conf` | stdout | container platform log |
| `ADMIN_AUDIT_LOG` JSONL | `docker/admin_service.py` | `/data/logs` | runtime-generated |
| Single-file ops/admin dashboards | `docker/ops_service.py`, `docker/admin_service.py` | browser via `/_ops/` and `/_admin/` | runtime-served HTML |

## Shared infrastructure

| Component | Path | Used by |
|---|---|---|
| `docker/dify.env.runtime` + generated env | `docker/dify.env.runtime`, `docker/entrypoint.sh:35-74` | API, Web, Worker, Beat, Plugin, Sandbox, Ops, Admin |
| `/data` / `/persist` / `/tmp/dify-aio` layout | `docker/entrypoint.sh:171-211` | Postgres, Redis, Dify storage, plugin storage, logs |
| `supervisorctl` unix socket | `docker/supervisord.conf:7-15` | `ops-service`, `admin-service`, operator debug |
| `wait-for-core` readiness contract | `docker/wait-for-core:16-49` | Plugin, API, Worker, Beat, Web |

## 不属于 shipped product 的仓库内容

| Item | Path | Reason | Status tag |
|---|---|---|---|
| 本地计划材料 | `local/ops-admin-plan.md` | 研究/实现草稿，不是 runtime artifact | changed |
| 仓库 agent 指令 | `AGENTS.md`, `docker/AGENTS.md` | 开发协作规则，不进入容器产物 | documentation |
| 本地 secrets snapshot | `.env.local` | `.gitignore` 明确忽略，只作本地 HF 上传事实源 | local-only |
