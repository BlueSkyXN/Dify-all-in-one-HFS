# Configuration Reference

本文档说明运行时配置来源、覆盖优先级、主要环境变量和 Hugging Face Space 推荐设置。

## 配置来源和优先级

主要配置文件：

```text
docker/dify.env.runtime
docker/dify.env.demo
/data/config/generated.env
```

运行时加载方式：

1. Docker / Hugging Face Space 注入的环境变量已经存在。
2. wrapper 脚本 source `/etc/dify/dify.env.runtime`。
3. `dify.env.runtime` 使用 `${VAR:-default}`，所以已有环境变量优先。
4. `entrypoint.sh` 先准备存储布局；bucket-lite 模式下 `/data/config` 会映射到 `/persist/config`。
5. 如果存在 `/data/config/generated.env`，再 source 这个文件，补齐自动生成的 secret。
6. 部分 wrapper 会把通用变量转换成上游服务期望的变量名。

`entrypoint.sh` 写入 `generated.env` 时会特殊处理 secrets：

- 显式传入的 Space Secrets 优先。
- 其次复用已有 `/data/config/generated.env`。
- 最后才随机生成。

## 本地 env 账本约定

本仓库只维护一个本地私有环境配置账本：

```text
.env.local
```

`.env.local` 已被 `.gitignore` 忽略，适合保存 demo/test 阶段的本地固定值、Hugging Face Settings 回读状态和人工判断。它不是直接上传给 Hugging Face 或 GitHub 的 env-file，而是一个本地笔记本：记录每个变量应该放在哪个平台、属于 Secret 还是 Variable、是否建议配置、默认值、建议值、已知值和备注。

`.env.local` 也可以保存本地运维便捷信息，例如 Space ID、Space URL、当前诊断入口使用方式、最近一次远程回读时间和故障回退备注。这类信息必须明确标注为 `Local Only` 或 `本地运维`，默认不参与 HF/GH 同步；如果包含 token、账号、私有 URL 或其他敏感上下文，只能保存在本地账本里，不能进入公开文档。

不要再维护 `.env.hf.local`、`local/hf-space.env` 或其他并行 env 快照；多份 env 很容易让 HF Settings、文档和本地判断互相漂移。

`.env.local` 的每个变量使用固定卡片字段：

| 字段 | 含义 |
| --- | --- |
| 平台 | 变量应配置在哪个平台。当前运行时配置主要是 Hugging Face Space Settings；GitHub Actions 当前只跑 static check，不需要运行时 env。 |
| 类型 | `Secret` 表示应放入 Secrets；`Variable` 表示可放入 Variables；`Variable（若值含凭据则改放 Secret）` 表示取决于实际值是否包含账号、密码、token、私有地址或其他敏感片段。 |
| 级别 | `推荐配置`、`按需配置` 或 `派生值，通常不单独上传`。 |
| 默认值 | 来自 `docker/dify.env.runtime` 或 runtime 派生逻辑。 |
| 建议值 | 当前 all-in-one HF Space demo 的建议填写方式。 |
| 已知值 | 本地账本或 Hugging Face Settings 能确认的状态。HF Secrets 是 write-only，只能确认 key 是否存在，不能回读明文。 |
| 备注 | 变量用途、风险和什么时候需要填写。 |

`.env.local` 当前按五层组织：

1. `HF Space / Secrets / 推荐配置`
2. `HF Space / Secrets / 按需配置`
3. `HF Space / Variables / 推荐配置`
4. `HF Space / Variables / 按需配置`
5. `GitHub Actions / 当前无需配置`

上传到 Hugging Face 时，只复制本轮真正要生效的非空值。不要把完整 `.env.local` 批量导入，也不要把未知 secret 写成占位字符串上传。

文档和 PR 文案只能写规则、默认值、建议值和占位符，不能写 `.env.local` 里的真实 token、账号、密码、私有 API 地址、内部 URL 或其他已知秘密信息。公开示例统一使用 `<...>` 占位。

初始化前推荐先在 `.env.local` 里明确选择这些值，再同步到 HF：

| 类别 | 变量 | 说明 |
| --- | --- | --- |
| Secret | `OPS_TOKEN` | `/_ops` 只读诊断入口 token；demo 可用固定易记值，公开长期运行应换强随机值 |
| Secret | `DB_PASSWORD` | 本容器 PostgreSQL demo 用户密码；初始化后不要随意改 |
| Secret | `REDIS_PASSWORD` | 本容器 Redis 密码；会影响 `CELERY_BROKER_URL` 派生值 |
| Secret | `SECRET_KEY` | Dify 应用签名/加密 secret；初始化后不要随意改 |
| Secret | `PLUGIN_DAEMON_KEY` | Dify 调 Plugin Daemon 的 server key |
| Secret | `PLUGIN_DIFY_INNER_API_KEY` | Plugin Daemon 访问 Dify inner API 的 key；`INNER_API_KEY_FOR_PLUGIN` 会由它派生 |
| Secret | `CODE_EXECUTION_API_KEY` | Dify 调 Sandbox 的 key；`SANDBOX_API_KEY` 默认继承它 |
| Variable | `PERSIST_MODE=bucket` | 初始化前建议使用，比默认 `auto` 更严格；`/persist` 缺失时直接失败 |
| Variable | `POSTGRES_BUCKET_FAILURE_MODE=fallback-to-runtime` | 当前 HF bucket 推荐值；bucket live PGDATA 启动超时时回退到 runtime PGDATA 并从 dump 恢复 |

不要上传以下派生值或同容器内部默认值，除非你明确要覆盖默认推导或改变部署拓扑：

```env
PUBLIC_URL
CONSOLE_WEB_URL
CONSOLE_API_URL
SERVER_CONSOLE_API_URL
APP_WEB_URL
APP_API_URL
FILES_URL
ENDPOINT_URL_TEMPLATE
TRIGGER_URL
CELERY_BROKER_URL
PGVECTOR_PASSWORD
INNER_API_KEY_FOR_PLUGIN
SANDBOX_API_KEY
```

其中 `SERVER_CONSOLE_API_URL` 在 all-in-one 容器内固定默认到 `http://127.0.0.1:5001`，供 Dify Web 的 server-side rendering 直接访问同容器 API；不要把它覆盖为 Hugging Face 公网域名。`CELERY_BROKER_URL` 会从 `REDIS_PASSWORD` 派生，`PGVECTOR_PASSWORD` 会从 `DB_PASSWORD` 派生，`INNER_API_KEY_FOR_PLUGIN` 会从 `PLUGIN_DIFY_INNER_API_KEY` 派生，`SANDBOX_API_KEY` 会从 `CODE_EXECUTION_API_KEY` 派生。重复上传这些变量会增加配置漂移风险。

## Hugging Face Space Metadata

`README.md` 顶部 YAML：

```yaml
sdk: docker
app_port: 7860
suggested_hardware: cpu-upgrade
```

Hugging Face 会根据 `app_port` 把外部流量转发到容器端口 `7860`。

## 推荐 Space Variables

```env
PERSIST_MODE=bucket
POSTGRES_BUCKET_FAILURE_MODE=fallback-to-runtime
```

说明：

- 这些值只是当前 HF Space demo 的推荐覆盖值；完整来源应以本地 `.env.local` 为准。
- 与 `docker/dify.env.runtime` 默认值一致的变量不要上传到 HF Variables。
- `POSTGRES_BUCKET_FAILURE_MODE=exit` 适合故障演练或强制暴露 bucket live PGDATA 问题；当前 HF bucket 上 PostgreSQL 启动可能超过 `pg_ctl` 等待窗口，线上服务默认保留 `fallback-to-runtime`。

## 推荐 Space Secrets

```env
OPS_TOKEN=<fixed-demo-or-random-token>
DB_PASSWORD=<fixed-demo-or-random-password>
REDIS_PASSWORD=<fixed-demo-or-random-password>
SECRET_KEY=<fixed-demo-or-random-secret>
PLUGIN_DAEMON_KEY=<fixed-demo-or-random-secret>
PLUGIN_DIFY_INNER_API_KEY=<fixed-demo-or-random-secret>
CODE_EXECUTION_API_KEY=<fixed-demo-or-random-secret>
```

不要单独上传 `SANDBOX_API_KEY` 和 `INNER_API_KEY_FOR_PLUGIN`，除非你明确要拆分内部 key。默认情况下，`SANDBOX_API_KEY` 继承 `CODE_EXECUTION_API_KEY`，`INNER_API_KEY_FOR_PLUGIN` 继承 `PLUGIN_DIFY_INNER_API_KEY`。

## Persistence Layout

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PERSIST_MODE` | `auto` | `auto` 会在 `/persist` 是挂载点且可写时启用 bucket-lite；也可设为 `bucket` 强制要求 `/persist` 可写，或 `legacy` 保持旧 `/data` 布局 |
| `PERSIST_ROOT` | `/persist` | Hugging Face Storage Bucket 推荐挂载点 |
| `RUNTIME_ROOT` | `/tmp/dify-aio` | 日志、run、cache、Redis 默认 scratch 根目录 |
| `REDIS_PERSISTENCE` | `false` | `true` 时 `/data/redis` 映射到 `/persist/redis`；默认放 `/tmp` 节省 bucket |
| `PLUGIN_CWD_PERSISTENCE` | `false` | `true` 时插件工作目录 `cwd` 也持久化；默认只持久化已安装插件和 assets |
| `POSTGRES_BUCKET_FAILURE_MODE` | `fallback-to-runtime` | `/persist/postgres` 启动失败时切到 `${RUNTIME_ROOT}/postgres`；设为 `exit` 可强制失败并只保留诊断日志 |
| `POSTGRES_BACKUP_ENABLED` | `auto` | bucket-lite 启用时自动启动 `pg_dumpall` 备份；可设 `true`/`false` |
| `POSTGRES_BACKUP_DIR` | `${PERSIST_ROOT}/postgres-backups` | `latest.sql.gz` 和时间戳写入目录 |
| `POSTGRES_BACKUP_INTERVAL_SECONDS` | `3600` | 周期备份间隔，最小有效值 60 秒 |
| `POSTGRES_BACKUP_INITIAL_DELAY_SECONDS` | `60` | supervisor 启动后首次备份延迟；只影响第一次 `pg_dumpall` 前等待多久，后续周期由 `POSTGRES_BACKUP_INTERVAL_SECONDS` 控制 |
| `POSTGRES_BACKUP_RETAIN_COUNT` | `5` | 保留最近多少份 timestamped dump，范围 `1..50` |
| `HF_HOME` | `${RUNTIME_ROOT}/hf-cache` | Hugging Face cache 根目录，默认不进 bucket |
| `HF_HUB_CACHE` | `${HF_HOME}/hub` | Hugging Face Hub cache |

bucket-lite 会保持上游程序看到的 `/data/...` 路径不变，但实际映射为：

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

`/persist/postgres` 会先作为 live PostgreSQL data directory 实测。启动已有 PGDATA 前会补建 object storage 可能丢失的 PostgreSQL 空目录；`/persist/postgres-backups/` 会保留 timestamped `YYYYmmddTHHMMSSZ.sql.gz` dump，并更新普通文件 `latest.sql.gz`、`latest.created_at` 和 `latest.sha256`。默认失败策略是 `fallback-to-runtime`：bucket PGDATA 起不来时，容器改用 `${RUNTIME_ROOT}/postgres` 保证服务启动，并在 dump 通过 `latest.sha256`、gzip 和非空校验后先恢复 dump；旧实例没有 `latest.sha256` 时会打印 warning 并只走 gzip/非空校验。

如果设置 `PLUGIN_CWD_PERSISTENCE=true`，`/data/plugin_daemon/cwd` 会改为映射到 `/persist/plugin_daemon/cwd`。

## URL 变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PUBLIC_URL` | `https://${SPACE_HOST}` 或 `http://localhost:8080` | 浏览器看到的外部 URL |
| `CONSOLE_WEB_URL` | `${PUBLIC_URL}` | Console Web URL |
| `CONSOLE_API_URL` | `${PUBLIC_URL}` | Console API URL |
| `SERVER_CONSOLE_API_URL` | `http://127.0.0.1:5001` | Dify Web SSR 的同容器 API origin；显式环境变量仍可覆盖 |
| `SERVICE_API_URL` | `http://127.0.0.1:5001` | 容器内服务 API URL |
| `APP_WEB_URL` | `${PUBLIC_URL}` | App Web URL |
| `APP_API_URL` | `${PUBLIC_URL}` | App API URL |
| `FILES_URL` | `${PUBLIC_URL}` | 文件外部访问 URL |
| `INTERNAL_FILES_URL` | `http://127.0.0.1:5001` | 容器内文件 URL |
| `ENDPOINT_URL_TEMPLATE` | `${PUBLIC_URL}/e/{hook_id}` | Plugin endpoint hook URL 模板 |
| `TRIGGER_URL` | `${PUBLIC_URL}` | Trigger 外部 URL |

在 Hugging Face Space 中，通常不需要手动设置 `PUBLIC_URL`，因为 `SPACE_HOST` 会自动注入。浏览器 URL 继续使用公网 `PUBLIC_URL`；Dify Web 的 server-side 请求使用 `SERVER_CONSOLE_API_URL` 直连本地 API，避免再次经过 Hugging Face public domain / ELB 并触发边缘限流。

## Dify API / Worker

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MIGRATION_ENABLED` | `true` | entrypoint 是否执行 Dify API migration |
| `DIFY_BIND_ADDRESS` | `0.0.0.0` | API 绑定地址 |
| `DIFY_PORT` | `5001` | API 端口 |
| `SERVER_WORKER_AMOUNT` | `1` | gunicorn worker 数 |
| `SERVER_WORKER_CLASS` | `geventwebsocket.gunicorn.workers.GeventWebSocketWorker` | gunicorn worker class |
| `SERVER_WORKER_CONNECTIONS` | `10` | worker connections |
| `GUNICORN_TIMEOUT` | `360` | API timeout |
| `CELERY_WORKER_CLASS` | `gevent` | Celery worker class |
| `CELERY_WORKER_AMOUNT` | `1` | Celery worker 数 |
| `CELERY_PREFETCH_MULTIPLIER` | `1` | Celery prefetch |
| `MAX_TASKS_PER_CHILD` | `50` | worker 子进程任务上限 |

## PostgreSQL / pgvector

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DB_TYPE` | `postgresql` | Dify DB 类型 |
| `DB_USERNAME` | `dify` | DB role |
| `DB_PASSWORD` | `dify_demo_password` | DB 密码 |
| `DB_HOST` | `127.0.0.1` | DB host |
| `DB_PORT` | `5432` | DB port |
| `DB_DATABASE` | `dify` | Dify 主库 |
| `DB_PLUGIN_DATABASE` | `dify_plugin` | Plugin Daemon 库 |
| `DB_SSL_MODE` | `disable` | PostgreSQL SSL mode |
| `VECTOR_STORE` | `pgvector` | 向量库类型 |
| `PGVECTOR_HOST` | `127.0.0.1` | pgvector host |
| `PGVECTOR_PORT` | `5432` | pgvector port |
| `PGVECTOR_USER` | `${DB_USERNAME}` | pgvector user |
| `PGVECTOR_PASSWORD` | `${DB_PASSWORD}` | pgvector password |
| `PGVECTOR_DATABASE` | `${DB_DATABASE}` | pgvector database |

`DB_USERNAME`、`DB_DATABASE`、`DB_PLUGIN_DATABASE` 必须匹配：

```text
^[A-Za-z_][A-Za-z0-9_]*$
```

否则 entrypoint 会退出，避免 SQL identifier 注入和非法数据库名。

## Redis / Celery

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `REDIS_HOST` | `127.0.0.1` | Redis host |
| `REDIS_PORT` | `6379` | Redis port |
| `REDIS_PASSWORD` | `dify_redis_password` | Redis 密码 |
| `REDIS_DB` | `0` | Redis DB |
| `REDIS_KEY_PREFIX` | empty | Dify Redis key prefix |
| `CELERY_BROKER_URL` | `redis://:${REDIS_PASSWORD}@127.0.0.1:6379/1` | Celery broker |
| `CELERY_BACKEND` | `redis` | Celery backend |

`entrypoint.sh` 会根据这些变量渲染 `/data/run/redis.conf`。

## Web / Browser

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `WEB_API_CORS_ALLOW_ORIGINS` | `*` | Web API CORS |
| `CONSOLE_CORS_ALLOW_ORIGINS` | `*` | Console CORS |
| `NEXT_PUBLIC_BATCH_CONCURRENCY` | `5` | 前端批量并发 |
| `TEXT_GENERATION_TIMEOUT_MS` | `120000` | 文本生成 timeout |
| `NEXT_TELEMETRY_DISABLED` | `1` | 关闭 Next telemetry |
| `MARKETPLACE_API_URL` | `https://marketplace.dify.ai` | Marketplace API |
| `MARKETPLACE_URL` | `https://marketplace.dify.ai` | Marketplace Web |
| `MARKETPLACE_ENABLED` | `true` | 是否启用 Marketplace |

## Storage

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `STORAGE_TYPE` | `opendal` | Dify storage backend |
| `OPENDAL_SCHEME` | `fs` | OpenDAL scheme |
| `OPENDAL_FS_ROOT` | `/data/dify/storage` | 本地文件根目录 |

## Sandbox

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `CODE_EXECUTION_ENDPOINT` | `http://127.0.0.1:8194` | Dify API 访问 Sandbox 的地址 |
| `CODE_EXECUTION_API_KEY` | generated | Code execution API key |
| `SANDBOX_API_KEY` | `${CODE_EXECUTION_API_KEY}` | Sandbox server key |
| `SANDBOX_GIN_MODE` | `release` | Sandbox gin mode |
| `SANDBOX_WORKER_TIMEOUT` | `15` | Sandbox worker timeout |
| `SANDBOX_ENABLE_NETWORK` | `false` | Sandbox 是否允许出网 |
| `SANDBOX_HTTP_PROXY` | empty | Sandbox HTTP proxy |
| `SANDBOX_HTTPS_PROXY` | empty | Sandbox HTTPS proxy |
| `SANDBOX_PORT` | `8194` | Sandbox port |
| `SANDBOX_PYTHON_PATH` | `/usr/local/bin/python3` | Python path |
| `SANDBOX_NODEJS_PATH` | `/usr/bin/node` | Node path |
| `SANDBOX_PYTHON_DEPS_UPDATE_INTERVAL` | `876000h` | Python deps update interval；HF rootless 环境默认等效禁用周期刷新，避免只读 sandbox rootfs 被重复覆盖 |

## Plugin Daemon

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PLUGIN_DAEMON_HOST` | `0.0.0.0` | Plugin Daemon host |
| `PLUGIN_DAEMON_PORT` | `5002` | Plugin Daemon API port |
| `PLUGIN_DAEMON_KEY` | generated | Dify API 访问 Plugin Daemon 的 key |
| `PLUGIN_DAEMON_URL` | `http://127.0.0.1:5002` | Dify API 访问 Plugin Daemon 的 URL |
| `PLUGIN_DIFY_INNER_API_KEY` | generated | Plugin Daemon 访问 Dify inner API 的 key |
| `PLUGIN_DIFY_INNER_API_URL` | `http://127.0.0.1:5001` | Dify inner API URL |
| `INNER_API_KEY_FOR_PLUGIN` | `${PLUGIN_DIFY_INNER_API_KEY}` | Dify API 使用的 inner API key |
| `PLUGIN_STORAGE_TYPE` | `local` | Plugin storage 类型 |
| `PLUGIN_STORAGE_LOCAL_ROOT` | bucket-lite: `/persist/plugin_daemon`; legacy: `/data/plugin_daemon` | Plugin storage 根目录；bucket-lite 下默认使用真实 `/persist` 目录，避免 Plugin Daemon 启动扫描停在 `/data` symlink |
| `PLUGIN_WORKING_PATH` | `/data/plugin_daemon/cwd` | Plugin working directory |
| `PLUGIN_INSTALLED_PATH` | `plugin` | 已安装插件目录 |
| `PLUGIN_PACKAGE_CACHE_PATH` | `plugin_packages` | 插件包目录；bucket-lite 下由 `/persist/plugin_daemon/plugin_packages` 持久化 |
| `PLUGIN_MEDIA_CACHE_PATH` | `assets` | 插件媒体缓存目录 |
| `PLUGIN_DEBUGGING_HOST` | `0.0.0.0` | remote installing/debug host |
| `PLUGIN_DEBUGGING_PORT` | `5003` | remote installing/debug port |
| `PLUGIN_MAX_PACKAGE_SIZE` | `52428800` | 插件包最大大小 |
| `PLUGIN_PYTHON_ENV_INIT_TIMEOUT` | `120` | 插件 Python 环境初始化 timeout |
| `PLUGIN_MAX_REQUEST_TIMEOUT` | `300` | 插件 Python runtime 对外模型/API 请求 read timeout；`with-plugin-env` 会映射为 Dify Plugin SDK 使用的 `MAX_REQUEST_TIMEOUT` |
| `PLUGIN_CONNECT_TIMEOUT_SECONDS` | `60` | OpenAI-compatible SDK 请求的连接/TLS timeout；镜像 shim 只把 SDK 固定的 `(10, MAX_REQUEST_TIMEOUT)` tuple 改为该值，范围 `10..300` |
| `PLUGIN_SSL_EOF_MAX_RETRIES` | `0` | OpenAI-compatible SDK `_generate` 遇到精确 TLS unexpected EOF 时的额外 retry 次数，只允许 `0` 或 `1`；非法值 fail closed 为 `0`，一次 retry 使用固定 250ms backoff |
| `PLUGIN_MAX_EXECUTION_TIMEOUT` | `600` | 插件执行 timeout |
| `ENFORCE_LANGGENIUS_PLUGIN_SIGNATURES` | `false` | 是否强制 LangGenius plugin signature |
| `FORCE_VERIFYING_SIGNATURE` | `false` | 是否强制验证签名 |

Plugin Daemon 会用 `plugin_unique_identifier` 作为 package bucket key 在 `PLUGIN_PACKAGE_CACHE_PATH` 下查找本地包，例如 `plugin_packages/langgenius/openai_api_compatible:0.0.49@<checksum>`。本地 runtime watchdog 则从 `PLUGIN_INSTALLED_PATH` 枚举已安装插件并拉起 local runtime；Redis `plugin_state` 是 cluster routing 视图，单容器本机 runtime 已 ready 时它可能不是唯一证据。bucket-lite 下 wrapper 会让 Plugin Daemon 直接使用 `/persist/plugin_daemon` 作为 storage root；不要把 `PLUGIN_STORAGE_LOCAL_ROOT` 强制回 `/data/plugin_daemon`，否则 Go `filepath.WalkDir` 不会跟随 `/data/plugin_daemon/plugin` 这个 symlink root，重建后已安装插件可能不会被重新拉起。重建后如果数据库中的 `plugin_unique_identifier` 还在、但 package cache、installed bucket 或 local runtime ready 证据缺失，Dify 页面可能仍显示 provider 配置，实际 plugin runtime 却无法重新拉起。用 `/_ops/persistence` 检查 `plugin_storage_layout_issues`、`missing_package_files`、`missing_installed_files`、`missing_runtime_states`、`plugin_runtime_state.checked` 和 `plugin_runtime_state.identifiers[].log.ready` 可以直接确认这类错配；`scripts/hf-space-smoke.sh` 也会把这些字段作为 `ops-persistence` 回归条件。

`with-plugin-env` 会把 `DB_PLUGIN_DATABASE` 映射到 Plugin Daemon 期望的 `DB_DATABASE`，并把镜像内只读的 `/opt/dify/plugin-runtime-patches` 前置到 Plugin runtime 的 `PYTHONPATH`。该 shim 不修改已签名 `.difypkg`，也不改 scalar timeout、credential validation 的 `(10, 300)` 或其他 request shape；只有运行时请求精确使用 `(10, MAX_REQUEST_TIMEOUT)` 时才提高 connect/TLS timeout。它通过精确 SDK module import hook 延迟安装 Requests wrapper，确保 `dify_plugin` 先完成 `gevent.monkey.patch_all()`，不会在启动期提前导入 `requests`/`ssl`。官方 SDK 移除固定 10 秒 tuple 后，timeout rewrite 自动不再生效。

`PLUGIN_SSL_EOF_MAX_RETRIES=1` 是独立的 opt-in 恢复门，只作用于 `dify_plugin.interfaces.model.openai_compatible.llm._generate` 调用栈中、`requests.exceptions.SSLError` 的包装链明确包含 `ssl.SSLEOFError` 或 `UNEXPECTED_EOF_WHILE_READING` 的失败。它不会 retry credential validation、其他 SDK 调用、HTTP status、connect/read timeout 或普通 connection error；第二次失败会原样抛出。虽然异常发生在 Requests 返回 response 之前，模型 `POST` 仍可能已经到达上游，因此 retry 可能产生重复推理或双计费；默认保持 `0`，生产部署应优先在 provider/gateway 或上游 SDK 中使用可观测、可幂等的 retry 机制。

## Nginx

| 变量 | 默认值 | 当前状态 |
| --- | --- | --- |
| `NGINX_PORT` | `7860` | 保留变量，`nginx.conf` 当前固定监听 `7860` |
| `NGINX_CLIENT_MAX_BODY_SIZE` | `100M` | 保留变量，`nginx.conf` 当前固定 `100M` |

如果要让这些变量动态生效，需要新增配置模板渲染逻辑。

## Ops Service

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `OPS_HOST` | `127.0.0.1` | ops-service bind host |
| `OPS_PORT` | `8081` | ops-service port |
| `OPS_TOKEN` | `dify_ops_demo_token` | `/_ops` 认证 token |
| `ALLOW_DEMO_OPS_TOKEN` | `false` | 显式允许默认 demo token；仅本地 demo 应设置为 `true` |
| `OPS_CACHE_TTL_SECONDS` | `5` | `health` / `status` / `metrics` 共享缓存 TTL；`0` 禁用 |
| `OPS_SESSION_TTL_SECONDS` | `3600` | `/_ops/` dashboard signed HttpOnly cookie 有效期 |
| `OPS_COOKIE_SECURE` | `auto` | `auto` 时 `X-Forwarded-Proto=https` 自动加 `Secure` |
| `OPS_HTTP_TIMEOUT_SECONDS` | `30` | ops-service 单连接 socket timeout |
| `OPS_DEFAULT_CHECKS_ENABLED` | `true` | 是否启用内置 Dify 健康探针 |
| `OPS_EXTRA_HTTP_CHECKS_JSON` | empty | 额外 HTTP 探针 JSON list |
| `OPS_EXTRA_TCP_CHECKS_JSON` | empty | 额外 TCP 探针 JSON list |
| `OPS_LOG_DIR` | `/data/logs` | `/_ops/logs` 只读日志目录 |
| `OPS_LOG_SERVICES_JSON` | empty | 额外日志白名单 JSON map，例如 `{"my-api":"my-api.log"}` |
| `OPS_LOG_LINES_MAX` | `1000` | 单次日志 tail 最大行数 |
| `OPS_LOG_TAIL_MAX_BYTES` | `1048576` | 单个日志 tail 最多读取字节数，避免超长日志行占用过多内存 |

`/_ops` 认证支持：

```text
X-Ops-Token: <token>
Authorization: Bearer <token>
?token=<token>
```

CLI 和自动化优先使用 header，不建议长期使用 query token。`/_ops/?token=<token>` 仅保留为临时浏览器入口：成功后会设置 signed HttpOnly cookie 并跳转到无 query 的 `/_ops/`。如果 `OPS_TOKEN` 为空，或仍为默认 `dify_ops_demo_token` 且没有设置 `ALLOW_DEMO_OPS_TOKEN=true`，ops-service 会进入 locked mode，`/healthz` 和 `/_ops/*` 返回 503。

`/_ops/` dashboard 支持 English / 中文切换，默认跟随浏览器语言，并把选择保存在浏览器本地。该偏好属于浏览器本地状态，不是容器配置项。

迁移到非 Dify 程序时，可以关闭内置探针，只保留通用探针：

```env
OPS_DEFAULT_CHECKS_ENABLED=false
OPS_EXTRA_HTTP_CHECKS_JSON=[{"name":"api","url":"http://127.0.0.1:8000/health","expected_status":200,"timeout":2}]
OPS_EXTRA_TCP_CHECKS_JSON=[{"name":"queue","host":"127.0.0.1","port":5672,"timeout":1}]
```

自定义 HTTP/TCP 探针最多执行 32 个；HTTP 探针未设置 `expected_status` 时沿用内置语义，即 HTTP `<500` 代表 upstream 可达。
如果关闭内置探针又没有配置任何额外探针，`/healthz` 会返回不健康，避免空检查被误判为正常。
`/_ops/config` 不返回这些 JSON 的原文，只返回解析出的检查名称，避免误把 URL 中的敏感片段暴露成配置摘要。`/_ops` 不再支持自定义 command 探针；需要执行命令的受控操作必须放入 `/_admin` 白名单 action。

## Admin Service

`/_admin` 是独立于 `/_ops` 的受控管理面，默认关闭。Nginx 会把 `/_admin/` 代理到 `ADMIN_HOST:ADMIN_PORT`，但 `ADMIN_ENABLED=false` 时 admin-service 只返回 404，保持默认 smoke 行为。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `ADMIN_ENABLED` | `false` | 是否开启 `/_admin` 管理面 |
| `ADMIN_HOST` | `127.0.0.1` | admin-service bind host |
| `ADMIN_PORT` | `8082` | admin-service port |
| `ADMIN_TOKEN` | empty | 独立 admin token；开启 admin 时必须设置 |
| `ADMIN_CSRF_KEY` | empty | 可选 CSRF HMAC key；未设置时优先从 `SECRET_KEY` 派生，最后兼容回退到 `ADMIN_TOKEN` |
| `ADMIN_SESSION_TTL_SECONDS` | `3600` | Browser session cookie 有效期 |
| `ADMIN_COOKIE_SECURE` | `auto` | `auto` 时 `X-Forwarded-Proto=https` 自动加 `Secure`；本地 HTTP demo 不加 |
| `ADMIN_HTTP_TIMEOUT_SECONDS` | `30` | admin-service 单连接 socket timeout |
| `ADMIN_LOGIN_RATE_LIMIT_WINDOW_SECONDS` | `300` | 登录失败统计窗口 |
| `ADMIN_LOGIN_RATE_LIMIT_BLOCK_SECONDS` | `300` | 命中登录限速后的阻断时间 |
| `ADMIN_LOGIN_RATE_LIMIT_MAX_PER_IP` | `5` | 单 IP 窗口内允许的登录失败次数 |
| `ADMIN_LOGIN_RATE_LIMIT_MAX_GLOBAL` | `30` | 全局窗口内允许的登录失败次数 |
| `ADMIN_AUDIT_LOG` | `/data/logs/admin-audit.jsonl` | admin action 和文件写操作审计日志 |

认证方式：

```text
X-Admin-Token: <token>
Authorization: Bearer <token>
Browser login -> signed HttpOnly cookie
```

写操作必须使用 `POST` / `PUT` / `PATCH` / `DELETE`。浏览器 cookie session 必须携带 session 对应的 CSRF token；CLI 使用 `X-Admin-Token` 或 `Authorization: Bearer` 时不会被浏览器自动携带，因此显式跳过 CSRF，但仍需要 action 白名单和 `confirm=true`。

`/_admin/` 登录页和管理 dashboard 支持 English / 中文切换，默认跟随浏览器语言，并把选择保存在浏览器本地。语言选择不改变鉴权、CSRF、action 白名单或 file manager 权限。

当前 action catalog：

```text
POST /_admin/api/actions/restart-service
POST /_admin/api/actions/reload-nginx
POST /_admin/api/actions/run-health-checks
POST /_admin/api/actions/force-postgres-backup
POST /_admin/api/actions/ensure-app-api-token
POST /_admin/api/actions/ensure-plugin-installed-from-cache
POST /_admin/api/actions/set-provider-model-read-timeout
```

`restart-service` 只允许白名单 Supervisor service；`reload-nginx` 会先执行 Nginx 配置测试；`run-health-checks` 复用已有 `/usr/local/bin/dify-demo-healthcheck`；`force-postgres-backup` 固定调用 `/usr/local/bin/postgres-backup-loop --once`，用于部署或重启前把当前 PostgreSQL 状态写入 `${POSTGRES_BACKUP_DIR}`；`ensure-app-api-token` 只补指定 app 的 service token；`ensure-plugin-installed-from-cache` 只从已登记 package cache 恢复 installed package；`set-provider-model-read-timeout` 只给匹配的 provider model credential JSON 补非 secret `read_timeout`，且默认 dry-run。Admin action 不接受任意 shell command、任意 SQL 或任意文件路径。

`GET /_admin/api/audit?limit=50` 返回最近的 `ADMIN_AUDIT_LOG` 事件，用于追踪 login/logout、白名单 action 和 file manager 写操作。`limit` 会限制在 `1..500`，缺失或非法时使用默认值 `100`。日志不存在时仍返回 200、`exists=false`、`returned=0` 和空 `events`。事件字段固定为 `time`、`action`、`ok`、`actor`、`target`、`details`；返回内容会对 `token`、`apiKey`、`authorization`、`cookie` 等敏感 detail key 做递归兜底脱敏。该接口仍需要 `ADMIN_TOKEN` 或已登录 session，但不增加新的写能力。

## Admin File Manager

文件管理属于 `/_admin`，不是 `/_ops`。它默认关闭，即使开启 admin，也需要单独打开 `ADMIN_FILES_ENABLED`。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `ADMIN_FILES_ENABLED` | `false` | 是否开启 `/_admin/api/files/*` |
| `ADMIN_FILES_ROOT` | `/data` | 文件管理根目录 |
| `ADMIN_FILES_WRITE_ENABLED` | `false` | 是否允许 mkdir、写文本、上传 |
| `ADMIN_FILES_DESTRUCTIVE_ENABLED` | `false` | 是否允许 rename/delete API；后续若接入 UI 也必须受同一开关控制，且仍要求 write enabled |
| `ADMIN_FILES_MAX_UPLOAD_BYTES` | `10485760` | 上传和文本写入最大字节数 |

路径会被当作相对 `ADMIN_FILES_ROOT` 的路径处理，`/foo` 表示 `${ADMIN_FILES_ROOT}/foo`，不会读取宿主意义上的绝对 `/foo`。解析后的路径必须仍在 `ADMIN_FILES_ROOT` 内；symlink 跳出 root 会被标记为 protected。

默认保护规则会拒绝读取或写入：

```text
/data/config/generated.env
generated.env
*.pem
*.key
*secret*
*token*
```

上传和重命名不会覆盖已有目标；删除只支持文件或空目录，不做递归删除。

## Removed WebSSH / Web Terminal

Web terminal / WebSSH 已从 Hugging Face Space runtime 中移除。镜像不再安装 `ttyd`，Nginx 不再暴露 `/_admin/terminal/`，`WEBSSH_*` 变量不再是受支持配置。需要排障时使用 Hugging Face logs、`/_ops` 只读诊断、`/_admin` 白名单 action 和 smoke 脚本。
