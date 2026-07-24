# Runtime Lifecycle

本文档按时间顺序说明镜像构建、容器启动、初始化、迁移和长期运行阶段。

## Build 阶段

`Dockerfile` 使用多阶段构建，组装 self GHCR release 与固定的外部 runtime assets：

1. `web-builder`
   - 来源：`${DIFY_WEB_IMAGE_REF}`，使用已验证的 image-specific GHCR digest。
   - 验证 `/app/targets/next`、`/app/targets/vinext` 和 `/app/entrypoint.sh` 存在。
   - 最终复制 `/app/targets/` 和 `/app/entrypoint.sh` 到 runtime。

2. `api-image`
   - 来源：`${DIFY_API_IMAGE_REF}`，使用已验证的 image-specific GHCR digest。
   - 验证 `/app/api/.venv/bin/flask` 和 `/app/api/docker/entrypoint.sh` 存在。
   - 最终复制 `/app/api` 到 runtime。

3. `plugin-daemon-image`
   - 来源：`${PLUGIN_DAEMON_IMAGE_REF}`，默认固定为 `langgenius/dify-plugin-daemon@sha256:1c1f80c9814f896a31ef84c0551245fa1876d054bc51c53c3f075ae20ccc2566`。
   - 最终复制 `/app` 到 `/opt/dify/plugin-daemon`。
   - runtime 阶段会验证 `/opt/dify/plugin-daemon/commandline` 可执行。

4. `sandbox-image`
   - 来源：`${SANDBOX_IMAGE_REF}`，默认固定为 `langgenius/dify-sandbox@sha256:cb076f71cc84c14d4e4f7753ff95c4ba70a3b5816962b4f93bcf42f23a6e5cb8`。`sandbox_exec` 判定必须同时满足 sandbox HTTP 200、JSON envelope 成功、`exit_code=0`、`error=""` 和 stdout marker。
   - 最终复制 `/conf` 和 `/dependencies`。
   - runtime 阶段会用 `docker/sandbox-python-requirements.txt` 覆盖 `/dependencies/python-requirements.txt`，并在 build 时预装这些 Python 包，避免 demo 运行期依赖临时 PyPI 下载。

5. `sandbox-builder`
   - 来源：`${DIFY_SANDBOX_SOURCE_REF}`，默认固定为 `97c8097d51d0f46238bb720b1e9e9439ce68784d`。
   - 构建一个只包含 HFS UID/GID 兼容 patch 的 `/opt/dify/sandbox/main`，使 sandbox execution 默认使用 Hugging Face 映射的 UID/GID `1000`，而不是 upstream 默认 `10000..10999` UID pool。
   - 仍使用 upstream chroot/seccomp 代码路径；HFS 默认 `SANDBOX_UID_POOL_MIN=1000`、`SANDBOX_UID_POOL_MAX=1001`、`SANDBOX_RUN_GID=1000` 会让 code execution 串行化到单 UID。

6. `agent-image` 与 `agent-runtime-image`
   - `${DIFY_AGENT_IMAGE_REF}` 提供 `/app/api/.venv`，runtime 将其复制为独立 `/opt/dify-agent/.venv`；`${DIFY_AGENT_RUNTIME_IMAGE_REF}` 提供 Go `shellctl`、`shellctl-sanitize-pty`、`shellctl-runner-exit`、`shellctl-runner` 和 `dify-agent` CLI。
   - Go shellctl server 取代已从 upstream Python package 移除的 `shellctl-server` extra；`run-shellctl` 只使用 loopback `127.0.0.1:5004` 和 `${RUNTIME_ROOT}/shellctl` state directory。

7. `runtime`
   - 来源：`${BASE_IMAGE_REF}`；`${DIFY_UPSTREAM_BASE_REF}` 只记录已经合入 self fork 的 upstream commit，不参与 `FROM`。
   - 安装 Nginx、Supervisor、Redis、PostgreSQL 15、pgvector、Node.js 22、uv、tmux 等运行时依赖。
   - 保留 self API image 和 `/app/api/.venv` 原样；不再针对 API 文件做 source overlay。
   - 从 `agent-image` 复制 `/opt/dify-agent/.venv`，从 `agent-runtime-image` 复制 Go binaries；执行 API/Agent import、两个 venv 的 `sys.prefix` 隔离检查、Go CLI help，并分别执行 `uv pip check` 作为 build gate。API 当前只允许 `alibabacloud-tea-openapi`、`clickzetta-connector-python` 和 `msal` 三条已知上游冲突；出现其他冲突仍会失败。
   - 安装 Sandbox Python requirements 后执行 `python3 -m pip check`。
   - 创建 UID `1000` 的 `user`，适配 Hugging Face Space。
   - 将 Sandbox binary 设置为 setuid root，满足 sandbox runtime 需求。

Sandbox Python 包预设链路：

1. `docker/sandbox-python-requirements.txt` 是本仓库维护的 Code Node Python 包预设清单。
2. Docker build 使用 `/usr/local/bin/python3 -m pip install -r /dependencies/python-requirements.txt` 把这些包安装进系统 Python site-packages。
3. Sandbox 默认 `SANDBOX_PYTHON_PATH=/usr/local/bin/python3`，与 build-time 安装目标一致。
4. 当前上游 Sandbox 会从 `python_path` 自动发现 stdlib 和 site-packages，并把这些路径复制或硬链进 `/var/sandbox/sandbox-python`，供 Code Node chroot 后 import。

`python_lib_path` / `PYTHON_LIB_PATH` 是旧配置口径；当前上游 Sandbox 会忽略它们并记录 deprecated warning。它们不应作为预设包是否可用的验收依据。验收应以真实 `/v1/sandbox/run` import smoke 为准。

默认 build args：

```text
BASE_IMAGE_REF=python:3.12-slim-bookworm
DIFY_SOURCE_REPO=https://github.com/BlueSkyXN/dify.git
DIFY_SOURCE_MAIN_REF=dabed43933402155df59465ece399d30f6d78d6e
DIFY_UPSTREAM_BASE_REF=1227f19c6a8f58b6f4549a2de37f0226e6e6c841
DIFY_WEB_IMAGE_REF=ghcr.io/blueskyxn/dify-web@sha256:e73faceacbb71dc44e6cc474b48845c6ba06b9e3f30c74e9dd56266625ff48c0
DIFY_API_IMAGE_REF=ghcr.io/blueskyxn/dify-api@sha256:43b4434e2371164caa6e26e09364ae6cb5714fbdcb7edf46c57000a4c632b581
DIFY_AGENT_IMAGE_REF=ghcr.io/blueskyxn/dify-agent-backend@sha256:d4c95fae81d081aa73bd77884fcdaf5c3d6bd38137f8d7872240bc8d859ae8dc
DIFY_AGENT_RUNTIME_IMAGE_REF=ghcr.io/blueskyxn/dify-agent-local-sandbox@sha256:9782338c5defd80c6f24e7609c8ce35f9d3b4fe72a62356068111390447760d4
PLUGIN_DAEMON_IMAGE_REF=langgenius/dify-plugin-daemon@sha256:1c1f80c9814f896a31ef84c0551245fa1876d054bc51c53c3f075ae20ccc2566
SANDBOX_IMAGE_REF=langgenius/dify-sandbox@sha256:cb076f71cc84c14d4e4f7753ff95c4ba70a3b5816962b4f93bcf42f23a6e5cb8
DIFY_SANDBOX_SOURCE_REF=97c8097d51d0f46238bb720b1e9e9439ce68784d
DIFY_VERSION=BlueSkyXN-dify-main-dabed43933402155df59465ece399d30f6d78d6e
UV_VERSION=0.11.21
```

self source SHA 与四个 GHCR digest 已按同一次 release 原子固定；后续升级必须继续保持共同 revision，并重新完成 artifact、build、smoke 和 runtime readback。`DIFY_VERSION` 只作为 build/runtime metadata，不参与 `FROM` 镜像选择。

## Container Entry Point

容器入口：

```text
/usr/bin/tini -- /usr/local/bin/dify-all-in-one-entrypoint
```

`tini` 作为 PID 1，负责信号转发和子进程回收。真正的初始化逻辑在 `docker/entrypoint.sh`。

## 初始化顺序

`entrypoint.sh` 的 `main()` 顺序：

```text
prepare_dirs
write_generated_env
source_runtime_env
render_redis_config
render_sandbox_config
init_postgres
start_temp_redis
run_dify_migration
stop_temp_redis
stop_temp_postgres
exec supervisord
```

### prepare_dirs

`prepare_dirs` 先读取 `PERSIST_MODE`。默认 `auto` 会检测 `/persist` 是否是挂载点且可写：

- 是挂载点且可写：启用 bucket-lite，把核心状态映射到 `/persist`，把日志、run、cache 映射到 `/tmp/dify-aio`。
- 未挂载或不可写：回退旧 `/data` 布局。

程序内部仍使用这些 `/data` 路径：

```text
/data/postgres
/data/redis
/data/dify/storage
/data/plugin_daemon/cwd
/data/plugin_daemon/plugin
/data/plugin_daemon/plugin_packages
/data/plugin_daemon/assets
/data/config
/data/logs
/data/run/postgresql
/data/run/nginx/*
/conf
/dependencies
HF_HOME/HF_HUB_CACHE
```

bucket-lite 模式下关键映射为：

```text
/data/postgres                 -> /persist/postgres
/data/dify/storage             -> /persist/dify/storage
/data/config                   -> /persist/config
/data/plugin_daemon/plugin     -> /persist/plugin_daemon/plugin
/data/plugin_daemon/assets     -> /persist/plugin_daemon/assets
/data/plugin_daemon/plugin_packages -> /persist/plugin_daemon/plugin_packages
/data/plugin_daemon/cwd        -> /tmp/dify-aio/plugin_cwd
/data/logs                     -> /tmp/dify-aio/logs
/data/run                      -> /tmp/dify-aio/run
/data/redis                    -> /tmp/dify-aio/redis
HF_HOME/HF_HUB_CACHE           -> /tmp/dify-aio/hf-cache(/hub)
```

PostgreSQL 默认会先尝试使用 `/persist/postgres`。由于 object-store backed mount 可能不保留空目录，entrypoint 会在启动已有 PGDATA 前补建 `pg_notify`、`pg_tblspc`、`pg_wal/archive_status` 等 PostgreSQL 必需目录。如果 bucket mount 仍不满足 live data directory 需要的权限、锁或同步语义，默认 `POSTGRES_BUCKET_FAILURE_MODE=fallback-to-runtime` 会先确认旧 PostgreSQL 已停止，只重建 `/tmp/dify-aio/postgres` scratch PGDATA，再把 `/data/postgres` 切过去并从最近有效 dump 恢复；`/persist/postgres` 不会被删除或复用。恢复点最多只新到最近一次成功 dump，可能落后于故障前最后提交的事务；后续 dump 仍写入 `/persist/postgres-backups`。

`EXTERNAL_POSTGRES_ENABLED=true` 时，entrypoint 不初始化 `/data/postgres`，而是等待 `DB_HOST` 指向的外部 PostgreSQL，检查 `DB_DATABASE` 和 `DB_PLUGIN_DATABASE` 可连接，并在 `EXTERNAL_POSTGRES_REQUIRE_VECTOR=true` 时确认两个 database 可用 `vector` extension。

如果设置 `PLUGIN_CWD_PERSISTENCE=true`，`/data/plugin_daemon/cwd` 会改为映射到 `/persist/plugin_daemon/cwd`。

并验证 `/data` 对 UID `1000` 可写。如果 `PERSIST_MODE=bucket` 但 `/persist` 不可写，容器会直接退出。

### write_generated_env

生成或更新：

```text
/data/config/generated.env
```

包含：

```env
SECRET_KEY
PLUGIN_DAEMON_KEY
PLUGIN_DIFY_INNER_API_KEY
INNER_API_KEY_FOR_PLUGIN
CODE_EXECUTION_API_KEY
SANDBOX_API_KEY
```

规则：

- 如果 Space / Docker 环境显式提供了非空值，优先使用显式值。
- 否则复用 `/data/config/generated.env` 中已有值。
- 如果仍为空，则生成随机 base64 值。
- `SANDBOX_API_KEY` 为空时复用 `CODE_EXECUTION_API_KEY`。

### render_redis_config

渲染：

```text
/data/run/redis.conf
```

关键配置：

```text
bind 127.0.0.1
appendonly yes
protected-mode yes
requirepass <REDIS_PASSWORD>
```

### render_sandbox_config

渲染：

```text
/conf/config.yaml
```

配置 Sandbox 端口、API key、worker timeout、网络开关、Python/Node 路径、依赖更新时间和 proxy。

### init_postgres

主要动作：

- 校验 `DB_USERNAME`、`DB_DATABASE`、`DB_PLUGIN_DATABASE` 是 PostgreSQL-safe identifier。
- 如果 `/data/postgres/PG_VERSION` 不存在，则执行 `initdb`。
- 补写 `postgresql.conf` 和 `pg_hba.conf`。
- 启动 temporary PostgreSQL。
- 创建或更新 `DB_USERNAME` 登录角色。
- 创建 `DB_DATABASE` 和 `DB_PLUGIN_DATABASE`。
- 在两个数据库中创建 `vector` extension。

### run_dify_migration

如果 `MIGRATION_ENABLED=true`，执行 Dify API migration：

```bash
/usr/local/bin/with-dify-env bash -c \
  'cd /app/api && MODE=migration MIGRATION_ENABLED=true ./docker/entrypoint.sh'
```

这个迁移在长期运行进程启动前完成。

## supervisord 运行阶段

初始化完成后，`entrypoint.sh` 用 `exec` 启动：

```bash
/usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
```

`supervisord.conf` 按 priority 启动服务：

```text
10 postgres
20 redis
25 postgres-backup
30 plugin-daemon
35 sandbox
40 dify-api
50 dify-worker
60 dify-beat
70 dify-web
75 ops-service
76 admin-service
80 nginx
85 shellctl
90 dify-agent
```

priority 控制启动顺序，但真正的依赖等待由 `wait-for-core` 执行。`postgres` program 通过 `run-postgres` 启动本地 PostgreSQL；如果 `EXTERNAL_POSTGRES_ENABLED=true`，该 program 保持 idle，`wait-for-core postgres` 改为等待外部 `DB_HOST`。`shellctl` 只监听 `127.0.0.1:5004`，由 `run-shellctl` 按 `DIFY_AGENT_ENABLED` 和 `AGENT_SHELL_ENABLED` 控制；`run-dify-agent` 在 shell layer 开启时会等待 shellctl TCP 可达后再启动 Agent backend。

## Plugin Daemon Migration

Plugin Daemon supervisor command：

```bash
/usr/local/bin/wait-for-core postgres redis -- \
  /usr/local/bin/with-plugin-env bash -c \
  '/opt/dify/plugin-daemon/commandline migrate && exec /opt/dify/plugin-daemon/main'
```

必须先执行 `commandline migrate`，否则 `install_tasks` 等 Plugin Daemon 表不会创建。典型错误：

```text
ERROR: relation "install_tasks" does not exist
failed to get all tasks
```

迁移成功日志：

```text
database migration completed successfully
```

## Docker HEALTHCHECK

`Dockerfile` 声明：

```text
interval=30s
timeout=10s
start-period=120s
retries=5
```

执行脚本：

```bash
/usr/local/bin/dify-demo-healthcheck
```

脚本检查：

```bash
curl -fsS http://127.0.0.1:5001/health
curl -fsS http://127.0.0.1:8081/healthz
curl -fsS http://127.0.0.1:7860/
```

## 重启行为

没有持久化 Storage 时：

- 数据库会重新初始化。
- `generated.env` 会重新生成。
- Web 初始化状态、账号、文件和插件会丢失。

有持久化 Storage 时：

- bucket-lite 下 `/data/postgres`、`/data/config/generated.env`、`/data/dify/storage`、`/data/plugin_daemon/plugin`、`/data/plugin_daemon/assets`、`/data/plugin_daemon/plugin_packages` 会通过 `/persist` 保留。
- `/data/redis`、`/data/logs`、`/data/run`、`/data/plugin_daemon/cwd` 和 Hugging Face cache 默认在 `/tmp/dify-aio`，重启后会重新生成。
- `postgres-backup` 会定期写 `/persist/postgres-backups/YYYYmmddTHHMMSSZ.sql.gz`，校验 gzip 和非空后更新 `latest.sql.gz`、`latest.created_at` 和 `latest.sha256`，作为 live PostgreSQL data directory 的普通文件兜底备份；备份脚本使用锁避免自动、手动和退出前备份并发运行，默认 `gzip -1` 快速压缩，并在成功备份后按 tiered retention 清理旧 dump。`/_admin/api/actions/force-postgres-backup` 可触发同一脚本的一次性备份。
- `postgres-backup` 收到 `TERM` / `INT` 时会 best-effort 尝试最后一次备份，Supervisor 会等待最多 120 秒；这不能替代正常 60 秒周期备份，也不能保证异常崩溃时一定完成。
- `entrypoint.sh` 会跳过 `initdb`，继续更新 role 密码和确保数据库存在。
- Dify API migration 和 Plugin Daemon migration 仍会执行，应当保持幂等。
