# 部署与运维复盘

## Startup

- **Entry command(s):** `/usr/bin/tini -- /usr/local/bin/dify-all-in-one-entrypoint`，随后 `entrypoint.sh` 在完成初始化后 `exec supervisord`。[Dockerfile:195] [docker/entrypoint.sh:644-658]
- **Required env vars:** `DB_PASSWORD`、`REDIS_PASSWORD`、`OPS_TOKEN`、`SECRET_KEY`、`PLUGIN_DAEMON_KEY`、`PLUGIN_DIFY_INNER_API_KEY`、`CODE_EXECUTION_API_KEY` 是最核心的 secret；`PERSIST_MODE`、`POSTGRES_BUCKET_FAILURE_MODE`、`ADMIN_*`、`WEBSSH_*` 控制运行模式。[docker/dify.env.runtime:20-33] [docker/dify.env.runtime:76-105] [docker/dify.env.runtime:219-250]
- **Required external services:** 本地运行只依赖 Docker daemon；HF 运行依赖 Space runtime、可选 `/persist` bucket；上游镜像与 apt 源仅在 build 阶段需要。[scripts/build.sh:1-4] [README.hf-space.md:3-10]
- **Build steps before run:** `scripts/build.sh` 或 `docker build -t ... .`。[scripts/build.sh:1-4] [docs/deployment.md:148-166]
- **Observed startup time:** `[UNKNOWN]` 本轮未实际运行容器。
- **Known startup failures:** `/persist/postgres` 不满足 live PGDATA 语义时会触发 fallback 或退出；plugin-daemon 缺 migration 会缺表；iframe header 错误会导致 HF 页面内嵌失败。[docker/entrypoint.sh:580-601] [docs/development.md:131-144] [docs/security.md:117-135]

## Dependency management

- **Package manifest(s):** 没有 `package.json` / `pyproject.toml` / lockfile；主要依赖声明在 `Dockerfile`、官方上游镜像和 `docker/dify.env.runtime` 中。
- **Lockfile present?:** no。
- **Version pinning policy:** Docker build args pin `DIFY_VERSION=1.14.1`、`PLUGIN_DAEMON_IMAGE=...:0.6.0-local`、`SANDBOX_IMAGE=...:0.2.15`、`UV_VERSION=0.8.9`；APT 安装的 Node 22 和 PostgreSQL 15 通过仓库源固定 major，但不是 lockfile 级封存。[Dockerfile:17-22] [Dockerfile:94-108]
- **Outdated or vulnerable deps observed:** `[UNKNOWN]` 本轮没有做 CVE 或 upstream drift 审计。

## Configuration

- **Config source(s):** Docker/HF 环境变量、`docker/dify.env.runtime`、`docker/dify.env.demo`、`/data/config/generated.env`、本地 `.env.local` 作为 HF 上传事实源。[docs/configuration.md:5-29] [docs/configuration.md:30-80]
- **`.env.example` present?:** no；仓库使用 `docker/dify.env.demo` 和文档表格代替。
- **Config validation at startup?:** yes，但只对部分关键变量：`PERSIST_MODE`、`POSTGRES_BUCKET_FAILURE_MODE`、`DB_USERNAME`、`DB_DATABASE`、`DB_PLUGIN_DATABASE` 等有显式校验。[docker/entrypoint.sh:112-141] [docker/entrypoint.sh:506-518] [docker/entrypoint.sh:561-566]
- **Secret handling:** 运行时优先使用外部 env，其次复用已有 `generated.env`，最后再生成随机值；`ops-service` 只返回 secret presence，不回显原文。[docker/entrypoint.sh:35-74] [docker/ops_service.py:95-104] [docs/security.md:51-58]

## Deployment

| Aspect | Status | Evidence |
|---|---|---|
| Container image build | implemented | `Dockerfile`, `scripts/build.sh:1-4` |
| Compose / orchestration | intentionally omitted | `AGENTS.md:47-64`, `docs/deployment.md:5-25` |
| CI/CD pipeline | `[UNKNOWN]/absent in repo` | `git ls-files`, `docs/deployment.md:41-119` |
| Health endpoint | implemented | `docker/nginx.conf:63-80`, `docker/ops_service.py:1241-1255` |
| Migration handling | implemented | `docker/entrypoint.sh:632-642`, `docker/supervisord.conf:47-55` |
| Rollback / restore path | partial | `docker/entrypoint.sh:521-555`, `docker/postgres-backup-loop:52-71` |

## Observability

- **Application logs:** Nginx access log 走 JSON stdout；大多数服务日志写 `/data/logs`；`dify-web`、`ops-service`、`admin-service`、`web-terminal` 主要走 stdout/stderr。[docker/nginx.conf:13-26] [docker/supervisord.conf:118-145]
- **Metrics / monitoring:** `/_ops/metrics` 输出 Prometheus text format，但仍需要 `OPS_TOKEN`。[docker/ops_service.py:608-693]
- **Tracing:** `[UNKNOWN]` 仓库内未见 tracing 实现。
- **Alerting:** `[UNKNOWN]` 仓库内未见告警集成。
- **Crash reporting:** 主要依赖 Supervisor restart 与容器平台 logs，没有专门 crash reporter。[docker/supervisord.conf:17-156]

## Operational readiness

| Capability | Status tag | Evidence | Gap |
|---|---|---|---|
| Can start with one command | implemented | `scripts/run-demo.sh:1-18` | 需要真实运行证据 |
| Config clearly documented | specified | `docs/configuration.md:1-410` | 存在 Marketplace/admin 合同漂移 |
| Logs are searchable | operable | `docker/ops_service.py:721-736`, `docs/ops-runbook.md:209-267` | 缺自动化验证 |
| Failure produces actionable error | specified | `docker/entrypoint.sh:434-459`, `docs/ops-runbook.md:331-359` | 缺 commit 绑定样本 |
| Rollback / restore possible | partial | `docker/entrypoint.sh:521-555`, `docker/postgres-backup-loop:52-71` | 只有 dump/fallback，没有演练记录 |
| Version upgrade path documented | partial | `docs/project-overview.md:64-76` | 没有固定 upgrade checklist |
| Handoff doc exists | implemented | `docs/README.md:1-44`, `docs/file-reference.md:1-325` | 需要收口高层合同漂移 |

## Open blockers

- `BLK-001` terminal 仍是 placeholder，不能算真实 break-glass 工具
- `BLK-002` 缺自动化测试与运行证据
- `BLK-003` 文档与 runtime 默认值漂移
- `BLK-004` 发布证据链依赖人工步骤
