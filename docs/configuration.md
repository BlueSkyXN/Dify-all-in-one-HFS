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
MARKETPLACE_ENABLED=false
SANDBOX_ENABLE_NETWORK=false
FORCE_VERIFYING_SIGNATURE=false
OPS_TOKEN=<fixed-random-token>
```

说明：

- `MARKETPLACE_ENABLED=false` 降低外部依赖。
- `SANDBOX_ENABLE_NETWORK=false` 让 Code Sandbox 默认不能出网。
- `FORCE_VERIFYING_SIGNATURE=false` 方便演示第三方插件；企业环境建议按插件策略调整。
- `OPS_TOKEN` 用于保护只读 `/_ops` 诊断入口。

## 推荐 Space Secrets

```env
SECRET_KEY=<fixed-random-secret>
PLUGIN_DAEMON_KEY=<fixed-random-secret>
PLUGIN_DIFY_INNER_API_KEY=<fixed-random-secret>
CODE_EXECUTION_API_KEY=<fixed-random-secret>
SANDBOX_API_KEY=<fixed-random-secret>
```

如果挂载了 `/persist`，可以让 `entrypoint.sh` 自动生成并保存在 `/persist/config/generated.env`。如果没有持久化目录，每次重启都会重新生成，登录状态、签名、插件通信和文件 URL 可能失效。

## Persistence Layout

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PERSIST_MODE` | `auto` | `auto` 会在 `/persist` 可写时启用 bucket-lite；也可设为 `bucket` 强制要求 `/persist` 可写，或 `legacy` 保持旧 `/data` 布局 |
| `PERSIST_ROOT` | `/persist` | Hugging Face Storage Bucket 推荐挂载点 |
| `RUNTIME_ROOT` | `/tmp/dify-aio` | 日志、run、cache、Redis 默认 scratch 根目录 |
| `REDIS_PERSISTENCE` | `false` | `true` 时 `/data/redis` 映射到 `/persist/redis`；默认放 `/tmp` 节省 bucket |
| `PLUGIN_CWD_PERSISTENCE` | `false` | `true` 时插件工作目录 `cwd` 也持久化；默认只持久化已安装插件和 assets |
| `POSTGRES_BACKUP_ENABLED` | `auto` | bucket-lite 启用时自动启动 `pg_dumpall` 备份；可设 `true`/`false` |
| `POSTGRES_BACKUP_DIR` | `${PERSIST_ROOT}/postgres-backups` | `latest.sql.gz` 和时间戳写入目录 |
| `POSTGRES_BACKUP_INTERVAL_SECONDS` | `3600` | 周期备份间隔，最小有效值 60 秒 |
| `POSTGRES_BACKUP_INITIAL_DELAY_SECONDS` | `600` | supervisor 启动后首次备份延迟 |
| `HF_HOME` | `${RUNTIME_ROOT}/hf-cache` | Hugging Face cache 根目录，默认不进 bucket |
| `HF_HUB_CACHE` | `${HF_HOME}/hub` | Hugging Face Hub cache |

bucket-lite 会保持上游程序看到的 `/data/...` 路径不变，但实际映射为：

```text
/data/postgres                 -> /persist/postgres
/data/dify/storage             -> /persist/dify/storage
/data/config                   -> /persist/config
/data/plugin_daemon/plugin     -> /persist/plugin_daemon/plugin
/data/plugin_daemon/assets     -> /persist/plugin_daemon/assets
/data/logs                     -> /tmp/dify-aio/logs
/data/run                      -> /tmp/dify-aio/run
/data/redis                    -> /tmp/dify-aio/redis
/data/plugin_daemon/plugin_packages -> /tmp/dify-aio/plugin_packages
```

`/persist/postgres` 是 live PostgreSQL data directory，适合 HF Space demo/个人服务先实测；`/persist/postgres-backups/latest.sql.gz` 是普通文件备份，用于降低 bucket mount 文件系统语义风险。

## URL 变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PUBLIC_URL` | `https://${SPACE_HOST}` 或 `http://localhost:8080` | 浏览器看到的外部 URL |
| `CONSOLE_WEB_URL` | `${PUBLIC_URL}` | Console Web URL |
| `CONSOLE_API_URL` | `${PUBLIC_URL}` | Console API URL |
| `SERVICE_API_URL` | `http://127.0.0.1:5001` | 容器内服务 API URL |
| `APP_WEB_URL` | `${PUBLIC_URL}` | App Web URL |
| `APP_API_URL` | `${PUBLIC_URL}` | App API URL |
| `FILES_URL` | `${PUBLIC_URL}` | 文件外部访问 URL |
| `INTERNAL_FILES_URL` | `http://127.0.0.1:5001` | 容器内文件 URL |
| `ENDPOINT_URL_TEMPLATE` | `${PUBLIC_URL}/e/{hook_id}` | Plugin endpoint hook URL 模板 |
| `TRIGGER_URL` | `${PUBLIC_URL}` | Trigger 外部 URL |

在 Hugging Face Space 中，通常不需要手动设置 `PUBLIC_URL`，因为 `SPACE_HOST` 会自动注入。

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
| `TEXT_GENERATION_TIMEOUT_MS` | `60000` | 文本生成 timeout |
| `NEXT_TELEMETRY_DISABLED` | `1` | 关闭 Next telemetry |
| `MARKETPLACE_API_URL` | `https://marketplace.dify.ai` | Marketplace API |
| `MARKETPLACE_URL` | `https://marketplace.dify.ai` | Marketplace Web |
| `MARKETPLACE_ENABLED` | `false` | 是否启用 Marketplace |

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
| `SANDBOX_PYTHON_DEPS_UPDATE_INTERVAL` | `30m` | Python deps update interval |

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
| `PLUGIN_STORAGE_LOCAL_ROOT` | `/data/plugin_daemon` | Plugin storage 根目录 |
| `PLUGIN_WORKING_PATH` | `/data/plugin_daemon/cwd` | Plugin working directory |
| `PLUGIN_INSTALLED_PATH` | `plugin` | 已安装插件目录 |
| `PLUGIN_PACKAGE_CACHE_PATH` | `plugin_packages` | 插件包缓存目录 |
| `PLUGIN_MEDIA_CACHE_PATH` | `assets` | 插件媒体缓存目录 |
| `PLUGIN_DEBUGGING_HOST` | `0.0.0.0` | remote installing/debug host |
| `PLUGIN_DEBUGGING_PORT` | `5003` | remote installing/debug port |
| `PLUGIN_MAX_PACKAGE_SIZE` | `52428800` | 插件包最大大小 |
| `PLUGIN_PYTHON_ENV_INIT_TIMEOUT` | `120` | 插件 Python 环境初始化 timeout |
| `PLUGIN_MAX_EXECUTION_TIMEOUT` | `600` | 插件执行 timeout |
| `ENFORCE_LANGGENIUS_PLUGIN_SIGNATURES` | `true` | 是否强制 LangGenius plugin signature |
| `FORCE_VERIFYING_SIGNATURE` | `false` | 是否强制验证签名 |

`with-plugin-env` 会把 `DB_PLUGIN_DATABASE` 映射到 Plugin Daemon 期望的 `DB_DATABASE`。

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
| `OPS_DEFAULT_CHECKS_ENABLED` | `true` | 是否启用内置 Dify 健康探针 |
| `OPS_EXTRA_HTTP_CHECKS_JSON` | empty | 额外 HTTP 探针 JSON list |
| `OPS_EXTRA_TCP_CHECKS_JSON` | empty | 额外 TCP 探针 JSON list |
| `OPS_EXTRA_COMMAND_CHECKS_JSON` | empty | 额外只读 command 探针 JSON list |
| `OPS_LOG_DIR` | `/data/logs` | `/_ops/logs` 只读日志目录 |
| `OPS_LOG_SERVICES_JSON` | empty | 额外日志白名单 JSON map，例如 `{"my-api":"my-api.log"}` |
| `OPS_LOG_LINES_MAX` | `1000` | 单次日志 tail 最大行数 |

`/_ops` 认证支持：

```text
X-Ops-Token: <token>
Authorization: Bearer <token>
?token=<token>
```

CLI 和自动化优先使用 header，不建议长期使用 query token。

迁移到非 Dify 程序时，可以关闭内置探针，只保留通用探针：

```env
OPS_DEFAULT_CHECKS_ENABLED=false
OPS_EXTRA_HTTP_CHECKS_JSON=[{"name":"api","url":"http://127.0.0.1:8000/health","expected_status":200,"timeout":2}]
OPS_EXTRA_TCP_CHECKS_JSON=[{"name":"queue","host":"127.0.0.1","port":5672,"timeout":1}]
OPS_EXTRA_COMMAND_CHECKS_JSON=[{"name":"worker","args":["/usr/local/bin/workerctl","status"],"expect":"running","timeout":2}]
```

`OPS_EXTRA_COMMAND_CHECKS_JSON` 只应配置只读命令。它不会从请求参数接收命令，但会在每次健康检查时执行部署时配置的 `args`。
自定义探针最多执行 32 个；HTTP 探针未设置 `expected_status` 时沿用内置语义，即 HTTP `<500` 代表 upstream 可达。
如果关闭内置探针又没有配置任何额外探针，`/healthz` 会返回不健康，避免空检查被误判为正常。
`/_ops/config` 不返回这些 JSON 的原文，只返回解析出的检查名称，避免误把 URL 或 command args 中的敏感片段暴露成配置摘要。
