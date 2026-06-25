# Runtime Lifecycle

本文档按时间顺序说明镜像构建、容器启动、初始化、迁移和长期运行阶段。

## Build 阶段

`Dockerfile` 使用多阶段构建，复用官方镜像资产：

1. `web-builder`
   - 来源：`${DIFY_WEB_IMAGE_REF}`，NEXT 默认 pin 到上游 main commit image `langgenius/dify-web@sha256:ece76df426066b31d7a5200ca2a9e236f94b1e5c4c27f78d03103e97e8be7375`。
   - 验证 `/app/targets/next`、`/app/targets/vinext` 和 `/app/entrypoint.sh` 存在。
   - 最终复制 `/app/targets/` 和 `/app/entrypoint.sh` 到 runtime。

2. `api-image`
   - 来源：`${DIFY_API_IMAGE_REF}`，NEXT 默认 pin 到上游 main commit image `langgenius/dify-api@sha256:8907f84d776e8b59c6cc57ffa06da6cc6e34b52c0c4de614dcada0a2ce799c69`。
   - 验证 `/app/api/.venv/bin/flask` 和 `/app/api/docker/entrypoint.sh` 存在。
   - 最终复制 `/app/api` 到 runtime。

3. `plugin-daemon-image`
   - 来源：`${PLUGIN_DAEMON_IMAGE_REF}`，NEXT 默认 pin 到 `langgenius/dify-plugin-daemon@sha256:3c694329357bc580b28bdec59321a981acd3279f8f69d1a3fb59a47cf7f770c3`。
   - 最终复制 `/app` 到 `/opt/dify/plugin-daemon`。
   - runtime 阶段会验证 `/opt/dify/plugin-daemon/commandline` 可执行。

4. `sandbox-image`
   - 来源：`${SANDBOX_IMAGE_REF}`，NEXT 默认 pin 到 HFS `sandbox_exec` 启动自检已通过的 config/dependencies digest `langgenius/dify-sandbox@sha256:41632ad63bddd8bcea83453270f3284d287c9e7cb463dac96644268770270788`。`sandbox_exec` 判定必须同时满足 sandbox HTTP 200、JSON envelope 成功、`exit_code=0`、`error=""` 和 stdout marker。
   - 最终复制 `/conf` 和 `/dependencies`。
   - runtime 阶段会用 `docker/sandbox-python-requirements.txt` 覆盖 `/dependencies/python-requirements.txt`，并在 build 时预装这些 Python 包，避免 demo 运行期依赖临时 PyPI 下载。

5. `sandbox-builder`
   - 来源：`${DIFY_SANDBOX_SOURCE_REF}`，NEXT 默认 pin 到 `44cdbd5d1991b97e40cb113c669800f4628920bb`。
   - 构建一个只包含 HFS UID/GID 兼容 patch 的 `/opt/dify/sandbox/main`，使 sandbox execution 默认使用 Hugging Face 映射的 UID/GID `1000`，而不是 upstream 默认 `10000..10999` UID pool。
   - 仍使用 upstream chroot/seccomp 代码路径；HFS 默认 `SANDBOX_UID_POOL_MIN=1000`、`SANDBOX_UID_POOL_MAX=1001`、`SANDBOX_RUN_GID=1000` 会让 code execution 串行化到单 UID。

6. `runtime`
   - 来源：`${BASE_IMAGE_REF}`，开发默认 `python:3.12-slim-bookworm`。
   - 安装 Nginx、Supervisor、Redis、PostgreSQL 15、pgvector、Node.js 22、uv、tmux 等运行时依赖。
   - 通过 `uv pip install --python /app/api/.venv/bin/python` 在官方 API venv 中补齐并 pin `dify-agent` server 和 `shellctl` 运行所需依赖，执行 `import dify_agent.server.app`、`shellctl --help` 和 `uv pip check` 作为 build gate；只放行官方 API image 已存在的 `clickzetta-connector-python` / `pyarrow`、`alibabacloud-tea-openapi` / `cryptography` 和 `msal` / `cryptography` 版本不兼容，其余依赖冲突仍会 fail。
   - 安装 Sandbox Python requirements 后执行 `python3 -m pip check`。
   - 创建 UID `1000` 的 `user`，适配 Hugging Face Space。
   - 将 Sandbox binary 设置为 setuid root，满足 sandbox runtime 需求。

默认 build args：

```text
BASE_IMAGE_REF=python:3.12-slim-bookworm
DIFY_WEB_IMAGE_REF=langgenius/dify-web@sha256:ece76df426066b31d7a5200ca2a9e236f94b1e5c4c27f78d03103e97e8be7375
DIFY_API_IMAGE_REF=langgenius/dify-api@sha256:8907f84d776e8b59c6cc57ffa06da6cc6e34b52c0c4de614dcada0a2ce799c69
PLUGIN_DAEMON_IMAGE_REF=langgenius/dify-plugin-daemon@sha256:3c694329357bc580b28bdec59321a981acd3279f8f69d1a3fb59a47cf7f770c3
SANDBOX_IMAGE_REF=langgenius/dify-sandbox@sha256:41632ad63bddd8bcea83453270f3284d287c9e7cb463dac96644268770270788
DIFY_SANDBOX_SOURCE_REF=44cdbd5d1991b97e40cb113c669800f4628920bb
DIFY_VERSION=main-b33e8f0ddb1189427548b0e1206cedcdc17d9bb6
UV_VERSION=0.11.21
```

NEXT branch 默认值已使用 digest ref 和 sandbox source ref，便于复现当前 main 代际。需要切换回稳定版或更新到新的 main commit 时，必须把 Web/API/Plugin Daemon/Sandbox image 与 `DIFY_SANDBOX_SOURCE_REF` 作为一组 co-pin 更新并重新 smoke。不要用上游 `docker/docker-compose.yaml` 里的 `1.14.2` image tag 判断 main 代码是否已经运行；NEXT 走的是官方 main commit-tag image digest，不是 compose release tag。若最新 main 源码已经前进但对应 Web/API commit-tag 镜像还不存在，保持上一个可验证 digest set 比只改 `DIFY_VERSION` 更准确。

`DIFY_VERSION` 只作为 build/runtime metadata，不再参与 `FROM` 镜像选择。需要切换真实 Dify Web/API 镜像时，必须同时覆盖 `DIFY_WEB_IMAGE_REF` 和 `DIFY_API_IMAGE_REF`。Plugin Daemon 使用 `0.6.2-local` 对应 digest，发布验证不要依赖可变的 `latest-local` tag。

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

PostgreSQL 会先尝试使用 `/persist/postgres`。由于 object-store backed mount 可能不保留空目录，entrypoint 会在启动已有 PGDATA 前补建 `pg_notify`、`pg_tblspc`、`pg_wal/archive_status` 等 PostgreSQL 必需目录。如果 bucket mount 仍不满足 live data directory 需要的权限、锁或同步语义，默认 `POSTGRES_BUCKET_FAILURE_MODE=fallback-to-runtime` 会把 `/data/postgres` 切到 `/tmp/dify-aio/postgres`，并继续把 dump 备份写到 `/persist/postgres-backups`。

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

priority 控制启动顺序，但真正的依赖等待由 `wait-for-core` 执行。`shellctl` 只监听 `127.0.0.1:5004`，由 `run-shellctl` 按 `DIFY_AGENT_ENABLED` 和 `AGENT_SHELL_ENABLED` 控制；`run-dify-agent` 在 shell layer 开启时会等待 shellctl TCP 可达后再启动 Agent backend。

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
- `postgres-backup` 会定期写 `/persist/postgres-backups/YYYYmmddTHHMMSSZ.sql.gz`，校验 gzip 和非空后更新 `latest.sql.gz`、`latest.created_at` 和 `latest.sha256`，作为 live PostgreSQL data directory 的普通文件兜底备份。
- `entrypoint.sh` 会跳过 `initdb`，继续更新 role 密码和确保数据库存在。
- Dify API migration 和 Plugin Daemon migration 仍会执行，应当保持幂等。
