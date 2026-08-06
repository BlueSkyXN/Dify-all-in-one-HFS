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
.env
```

`.env` 已被 `.gitignore` 忽略，是唯一的本地值账本，适合保存 demo/test 阶段的本地固定值、Hugging Face Settings 回读状态和人工判断。它不是直接上传给 Hugging Face 或 GitHub 的 env-file，而是一个本地笔记本：记录每个变量应该放在哪个平台、属于 Secret 还是 Variable、是否建议配置、默认值、建议值、已知值和备注。

`.env` 也可以保存本地运维便捷信息，例如 Space ID、Space URL、当前诊断入口使用方式、最近一次远程回读时间和故障回退备注。这类信息必须明确标注为 `Local Only` 或 `本地运维`，默认不参与 HF/GH 同步；如果包含 token、账号、私有 URL 或其他敏感上下文，只能保存在本地账本里，不能进入公开文档。

不要再维护 `.env.hf.local`、`local/hf-space.env` 或其他并行 env 快照；多份 env 很容易让 HF Settings、文档和本地判断互相漂移。

`.env` 的每个变量使用固定卡片字段：

| 字段 | 含义 |
| --- | --- |
| 平台 | 变量应配置在哪个平台。当前运行时配置主要是 Hugging Face Space Settings；GitHub Actions 当前只跑 static check，不需要运行时 env。 |
| 类型 | `Secret` 表示应放入 Secrets；`Variable` 表示可放入 Variables；`Variable（若值含凭据则改放 Secret）` 表示取决于实际值是否包含账号、密码、token、私有地址或其他敏感片段。 |
| 级别 | `推荐配置`、`按需配置` 或 `派生值，通常不单独上传`。 |
| 默认值 | 来自 `docker/dify.env.runtime` 或 runtime 派生逻辑。 |
| 建议值 | 当前 all-in-one HF Space demo 的建议填写方式。 |
| 已知值 | 本地账本或 Hugging Face Settings 能确认的状态。HF Secrets 是 write-only，只能确认 key 是否存在，不能回读明文。 |
| 备注 | 变量用途、风险和什么时候需要填写。 |

`.env` 当前按五层组织：

1. `HF Space / Secrets / 推荐配置`
2. `HF Space / Secrets / 按需配置`
3. `HF Space / Variables / 推荐配置`
4. `HF Space / Variables / 按需配置`
5. `GitHub Actions / 当前无需配置`

上传到 Hugging Face 时，只复制本轮真正要生效的非空值。不要把完整 `.env` 批量导入，也不要把未知 secret 写成占位字符串上传。

文档和 PR 文案只能写规则、默认值、建议值和占位符，不能写 `.env` 里的真实 token、账号、密码、私有 API 地址、内部 URL 或其他已知秘密信息。公开示例统一使用 `<...>` 占位。

初始化前推荐先在 `.env` 里明确选择这些值，再同步到 HF：

| 类别 | 变量 | 说明 |
| --- | --- | --- |
| Secret | `OPS_TOKEN` | `/_ops` 只读诊断入口 token；demo 可用固定易记值，公开长期运行应换强随机值 |
| Secret | `DB_PASSWORD` | 本容器 PostgreSQL demo 用户密码；初始化后不要随意改 |
| Secret | `REDIS_PASSWORD` | 本容器 Redis 密码；会影响 `CELERY_BROKER_URL` 派生值 |
| Secret | `SECRET_KEY` | Dify 应用签名/加密 secret；初始化后不要随意改 |
| Secret | `PLUGIN_DAEMON_KEY` | Dify 调 Plugin Daemon 的 server key |
| Secret | `PLUGIN_DIFY_INNER_API_KEY` | Plugin Daemon 访问 Dify inner API 的 key；`INNER_API_KEY_FOR_PLUGIN` 会由它派生 |
| Secret | `CODE_EXECUTION_API_KEY` | Dify 调 Sandbox 的 client key |
| Secret | `SANDBOX_API_KEY` | Sandbox server key；formal clean profile 显式登记，并与 `CODE_EXECUTION_API_KEY` 使用同一新生成值 |
| Secret | `DIFY_AGENT_SERVER_SECRET_KEY` | Agent Stub token 派生 key；formal clean profile 显式配置，其他部署仍可使用持久化 generated fallback |
| Secret | `DIFY_AGENT_SHELLCTL_AUTH_TOKEN` | Agent 与同容器 shellctl 之间的内部认证 token |
| Variable | `PERSIST_MODE=bucket` | 初始化前建议使用，比默认 `auto` 更严格；`/persist` 缺失时直接失败 |
| Variable | `POSTGRES_BUCKET_FAILURE_MODE=fallback-to-runtime` | 当前 HF bucket 推荐值；bucket live PGDATA 启动超时时重建 fresh runtime PGDATA 并从最近有效 dump 恢复 |

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
AGENT_BACKEND_BASE_URL
DIFY_AGENT_REDIS_URL
DIFY_AGENT_PLUGIN_DAEMON_API_KEY
DIFY_AGENT_INNER_API_KEY
DIFY_AGENT_SANDBOX_FILES_BASE_URL
DIFY_AGENT_STUB_API_BASE_URL
```

其中 `SERVER_CONSOLE_API_URL` 在 all-in-one 容器内固定默认到 `http://127.0.0.1:5001`，供 Dify Web 的 server-side rendering 直接访问同容器 API；不要把它覆盖为 Hugging Face 公网域名。`CELERY_BROKER_URL` 会从 `REDIS_PASSWORD` 派生，`PGVECTOR_PASSWORD` 会从 `DB_PASSWORD` 派生，`INNER_API_KEY_FOR_PLUGIN` 会从 `PLUGIN_DIFY_INNER_API_KEY` 派生。`DIFY_AGENT_ENABLED=true` 时，`with-dify-env` 会派生 Agent backend base URL、Redis URL、Plugin Daemon key、Dify inner API key、Sandbox 文件传输 API base 和同容器 Agent Stub URL。formal clean profile 会显式设置 `SANDBOX_API_KEY`、`DIFY_AGENT_SERVER_SECRET_KEY` 和 `DIFY_AGENT_SHELLCTL_AUTH_TOKEN`；其他本地/demo profile 仍可沿用 generated fallback。

## Artifact Delivery

本仓已使用 artifact 车道。Space image 不携带 Dify API/Web/Agent/Plugin/Sandbox 产品 payload；启动时必须从单一 slot manifest 获取并验证 runtime archive。不要把 archive、release bucket 或 manifest 当成 `/persist` 挂载，也不要设置旧的 direct URL/PATH/S3 回退变量。

| 变量 | 类型 | 说明 |
| --- | --- | --- |
| `DIFY_ARTIFACT_MANIFEST_HF_URI` | Space Variable | 必填；只允许 `hf://buckets/<namespace>/hfs-dist/dify-all-in-one/<edge|release>/manifest.json`。 |
| `DIFY_ARTIFACT_EXPECTED_SOURCE_REF` | Space Variable | 可选但 release 推荐；40 位 producer commit，启动时必须与 manifest `artifact_ref` 一致。 |
| `DIFY_ARTIFACT_MAX_BYTES` | Space Variable | archive 下载上限，默认且最大为 `4294967296`（4 GiB）；manifest 声明超过固定上限、超过此值或非法值都会在下载前失败。 |
| `DIFY_ARTIFACT_BEARER_TOKEN` | Space Secret | 私有 HFS dist 下载 token；不写入 seed、日志、docs 或 generated env。 |

schema v2 manifest 同时声明 artifact filename、source kind/ref、artifact commit、压缩与解包 size、SHA-256、runtime lock hash 与 slot key。bootstrap 一次读取 manifest，只下载其声明的 `dify-runtime-<commit>.tar.gz`；manifest、token、archive、lock、路径、解包大小或解包任一点不匹配都会退出。解包 regular-file 总量还受固定 32 GiB 上限保护；若实际 runtime 需要突破该边界，必须先经过 producer 体积审查和单独的 consumer contract 变更。它不扫描 bucket、不会沿用旧 image assembly，也没有 direct artifact URL/S3/PATH fallback。

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

- 这些值只是当前 HF Space demo 的推荐覆盖值；完整来源应以本地 `.env` 为准。
- 与 `docker/dify.env.runtime` 默认值一致的变量不要上传到 HF Variables。
- `POSTGRES_BUCKET_FAILURE_MODE=exit` 适合故障演练或强制暴露 bucket live PGDATA 问题；当前 HF bucket 上 PostgreSQL 启动可能超过 `pg_ctl` 等待窗口，线上服务默认保留 `fallback-to-runtime`。

## OpenAPI Variables

默认不要开启 OpenAPI；只有需要验证 `difyctl` 或其他 `/openapi/v1` 客户端时，才在 Space Settings 中单独设置：

```env
OPENAPI_ENABLED=true
ENABLE_OAUTH_BEARER=true
OPENAPI_KNOWN_CLIENT_IDS=difyctl
OPENAPI_RATE_LIMIT_PER_TOKEN=60
DEVICE_FLOW_APPROVE_RATE_LIMIT_PER_HOUR=10
OPENAPI_CORS_ALLOW_ORIGINS=
```

`OPENAPI_ENABLED=true` 暴露的是整个 `/openapi/v1` user/workspace-scoped programmatic surface，不是只开放 `difyctl` 子集。`difyctl auth login` 使用 OAuth device flow，需要在 Console 的 `/device` 页面人工批准；如果要做无人值守 CI，需要另行设计 token 注入方式，且不能把 `dfoa_` / `dfoe_` token 写入 tracked docs、logs 或示例配置。

## Agent v2 / Collaboration Variables

本 demo 默认打开可见的 Agent v2 前端、Collaboration、同容器 `dify-agent` backend 和 Agent Drive manifest，便于受控验证。Hugging Face Space Settings 里显式设置的变量仍会覆盖这些默认值。

```env
ENABLE_AGENT_V2=true
NEXT_PUBLIC_ENABLE_AGENT_V2=true
ENABLE_COLLABORATION_MODE=true
NEXT_PUBLIC_ENABLE_COLLABORATION_MODE=true
NEXT_PUBLIC_SOCKET_URL=wss://<your-space-host>
DIFY_AGENT_ENABLED=true
AGENT_DRIVE_MANIFEST_ENABLED=true
AGENT_SHELL_ENABLED=true
DIFY_AGENT_RUNTIME_BACKEND=local
DIFY_AGENT_LOCAL_SANDBOX_ENDPOINT=http://127.0.0.1:5004
```

通常不要额外上传下面这些派生值；它们由 `with-dify-env` 在 `DIFY_AGENT_ENABLED=true` 时从同容器默认值和 generated secrets 派生：

```env
AGENT_BACKEND_BASE_URL=http://127.0.0.1:5005
DIFY_AGENT_REDIS_URL=redis://:<url-encoded-REDIS_PASSWORD>@127.0.0.1:6379/2
DIFY_AGENT_PLUGIN_DAEMON_URL=http://127.0.0.1:5002
DIFY_AGENT_PLUGIN_DAEMON_API_KEY=${PLUGIN_DAEMON_KEY}
DIFY_AGENT_INNER_API_URL=http://127.0.0.1:5001
DIFY_AGENT_INNER_API_KEY=${INNER_API_KEY_FOR_PLUGIN}
DIFY_AGENT_SANDBOX_FILES_BASE_URL=http://127.0.0.1:5001
DIFY_AGENT_STUB_API_BASE_URL=http://127.0.0.1:5005/agent-stub
DIFY_AGENT_SERVER_SECRET_KEY=<generated-in-/data/config/generated.env>
DIFY_AGENT_API_TOKEN=<derived-from-DIFY_AGENT_SERVER_SECRET_KEY>
AGENT_BACKEND_API_TOKEN=${DIFY_AGENT_API_TOKEN}
```

`DIFY_AGENT_SHELLCTL_ENTRYPOINT`、`DIFY_AGENT_SHELLCTL_AUTH_TOKEN`、`DIFY_AGENT_DIFY_API_BASE_URL`、`DIFY_AGENT_DIFY_API_INNER_API_KEY` 和 `DIFY_AGENT_STUB_URL` 仍作为兼容 alias 接受，但最新 self fork 实际读取的是上面的 canonical 变量；新配置不要继续上传旧名。API 与 Agent backend 的内部 Bearer token 由 wrapper 从既有 `DIFY_AGENT_SERVER_SECRET_KEY` 单向派生，不需要新增或修改 HF Secret。

可按需覆盖的非 secret 开关：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `ENABLE_AGENT_V2` | `true` | 打开上游 Web 的 Agent v2 route gate；设为 `false` 会让 `/roster` 等 Agent v2 页面隐藏 |
| `NEXT_PUBLIC_ENABLE_AGENT_V2` | `${ENABLE_AGENT_V2}` | 浏览器侧 Agent v2 gate；默认跟随 `ENABLE_AGENT_V2` |
| `ENABLE_COLLABORATION_MODE` | `true` | 打开自托管协作模式，配合同容器 WebSocket worker 使用 |
| `NEXT_PUBLIC_ENABLE_COLLABORATION_MODE` | `${ENABLE_COLLABORATION_MODE}` | 浏览器侧协作开关 |
| `NEXT_PUBLIC_SOCKET_URL` | 从 `PUBLIC_URL` 派生 | 浏览器 WebSocket URL；`https://...` 派生为 `wss://...`，`http://...` 派生为 `ws://...` |
| `DIFY_AGENT_ENABLED` | `true` | 是否启动本容器内 `dify-agent` FastAPI backend |
| `DIFY_AGENT_HOST` | `127.0.0.1` | backend 监听地址；不要绑定公网 |
| `DIFY_AGENT_PORT` | `5005` | backend 内部端口 |
| `DIFY_AGENT_VIRTUAL_ENV` | `/opt/dify-agent/.venv` | 独立 Agent Python backend 环境；不要改回 `/app/api/.venv`，两边 `graphon` 版本不兼容 |
| `DIFY_AGENT_STARTUP_DELAY_SECONDS` | `30` | core API health 通过后再启动 backend 的延迟，降低 HFS cpu-basic 启动期资源竞争 |
| `AGENT_BACKEND_USE_FAKE` | `false` | API 侧 fake backend 开关，仅用于局部开发/测试 |
| `AGENT_SHELL_ENABLED` | `true` | shell layer 开关；默认由同容器 loopback `shellctl` 支撑，设为 `false` 时 `run-shellctl` 保持 idle |
| `SHELLCTL_BINARY` | `/usr/local/bin/shellctl` | 从 self Agent runtime image 复制的 Go shellctl server；不从 Python virtualenv 启动 |
| `AGENT_DRIVE_MANIFEST_ENABLED` | `true` | drive manifest 开关；让 Agent runtime 接收 Skills & Files drive manifest 声明 |
| `DIFY_AGENT_INNER_API_URL` | `http://127.0.0.1:5001` | Agent backend 调用同容器 Dify `/inner/api/...` 的 canonical base URL |
| `DIFY_AGENT_SANDBOX_FILES_BASE_URL` | `http://127.0.0.1:5001` | Sandbox 内 CLI 上传/下载文件时访问的 Dify API base；新版 Agent Stub 启用文件操作时必填，all-in-one 保持 loopback |
| `DIFY_AGENT_STUB_API_BASE_URL` | `http://127.0.0.1:5005/agent-stub` | 注入 shell job 的同容器 Agent Stub API；只保持 loopback，不经 Nginx 暴露 |
| `DIFY_AGENT_RUNTIME_BACKEND` | `local` | Agent Working Environment runtime backend；本 all-in-one 只使用同容器 local backend |
| `DIFY_AGENT_LOCAL_SANDBOX_ENDPOINT` | `http://127.0.0.1:5004` | local runtime 的 shellctl endpoint；只能保持 loopback，不要暴露到 Nginx 或公网 |
| `DIFY_AGENT_REDIS_PREFIX` | `dify-agent` | Agent backend Redis key prefix |

`DIFY_AGENT_SERVER_SECRET_KEY` 未设置时仍由 entrypoint 生成并持久化到 `/data/config/generated.env`；formal clean profile 则从 HF Secret 显式注入新值。它用于 Agent Stub token 派生，`/_ops` 只返回 presence boolean，不返回原文。`SERVER_WORKER_CLASS` 和 `API_WEBSOCKET_WORKER_CLASS` 默认使用 `geventwebsocket.gunicorn.workers.GeventWebSocketWorker`，Nginx 保留 `/socket.io/` WebSocket upgrade headers。`/_ops/health` 会暴露 `agent_backend` 和 `shellctl` 只读状态。`DIFY_AGENT_ENABLED=false` 时状态为 `disabled` 且不降级；设置为 `true` 后，`run-dify-agent` 会先等待 Redis、Plugin Daemon、Dify API health，以及 `AGENT_SHELL_ENABLED=true` 时的 shellctl，再按 `DIFY_AGENT_STARTUP_DELAY_SECONDS` 延迟启动，并检查 `127.0.0.1:${DIFY_AGENT_PORT}` TCP 可达。启动期间或失败时会使 `/_ops/health` 标记 degraded。这个探针只证明 backend 与 shellctl 进程可达，不等价于完整 Agent App / workflow Agent node 已通过真实工具调用验证。

## 推荐 Space Secrets

```env
OPS_TOKEN=<fixed-demo-or-random-token>
DB_PASSWORD=<fixed-demo-or-random-password>
REDIS_PASSWORD=<fixed-demo-or-random-password>
SECRET_KEY=<fixed-demo-or-random-secret>
PLUGIN_DAEMON_KEY=<fixed-demo-or-random-secret>
PLUGIN_DIFY_INNER_API_KEY=<fixed-demo-or-random-secret>
CODE_EXECUTION_API_KEY=<fixed-demo-or-random-secret>
SANDBOX_API_KEY=<same-new-value-as-CODE_EXECUTION_API_KEY>
DIFY_AGENT_SERVER_SECRET_KEY=<fixed-demo-or-random-secret>
DIFY_AGENT_SHELLCTL_AUTH_TOKEN=<fixed-demo-or-random-secret>
```

formal clean profile 同时登记 `CODE_EXECUTION_API_KEY` 和 `SANDBOX_API_KEY`，两者必须写入同一新生成值，使 Dify client 与 Sandbox server 的认证保持一致。`INNER_API_KEY_FOR_PLUGIN` 继续从 `PLUGIN_DIFY_INNER_API_KEY` 派生，不单独上传。

## Persistence Layout

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PERSIST_MODE` | `auto` | `auto` 会在 `/persist` 是挂载点且可写时启用 bucket-lite；也可设为 `bucket` 强制要求 `/persist` 可写，或 `legacy` 保持旧 `/data` 布局 |
| `PERSIST_ROOT` | `/persist` | Hugging Face Storage Bucket 推荐挂载点 |
| `RUNTIME_ROOT` | `/tmp/dify-aio` | 日志、run、cache、Redis 默认 scratch 根目录 |
| `REDIS_PERSISTENCE` | `false` | `true` 时 `/data/redis` 映射到 `/persist/redis`；默认放 `/tmp` 节省 bucket |
| `PLUGIN_CWD_PERSISTENCE` | `false` | `true` 时插件工作目录 `cwd` 也持久化；默认只持久化已安装插件和 assets |
| `POSTGRES_BUCKET_FAILURE_MODE` | `fallback-to-runtime` | `/persist/postgres` 启动失败时重建并切到 fresh `${RUNTIME_ROOT}/postgres`；设为 `exit` 可强制失败并只保留诊断日志 |
| `POSTGRES_BACKUP_ENABLED` | `auto` | bucket-lite 启用时自动启动 `pg_dumpall` 备份；可设 `true`/`false` |
| `POSTGRES_BACKUP_DIR` | `${PERSIST_ROOT}/postgres-backups` | `latest.sql.gz` 和时间戳写入目录 |
| `POSTGRES_BACKUP_INTERVAL_SECONDS` | `60` | 周期备份间隔，最小有效值 60 秒 |
| `POSTGRES_BACKUP_INITIAL_DELAY_SECONDS` | `15` | supervisor 启动后首次备份延迟；只影响第一次 `pg_dumpall` 前等待多久，后续周期由 `POSTGRES_BACKUP_INTERVAL_SECONDS` 控制 |
| `POSTGRES_BACKUP_RETENTION_POLICY` | `tiered` | `tiered` 按近端密、远端稀保留恢复点；`count` 保留最近 N 份 |
| `POSTGRES_BACKUP_RETAIN_COUNT` | `65` | timestamped dump 最大保留数；`tiered` 下作为上限，`count` 下作为最近 N 份，范围 `2..200` |
| `POSTGRES_BACKUP_COMPRESSION_LEVEL` | `1` | `gzip` 压缩级别，范围 `1..9`；默认偏向快速落盘 |
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

`/persist/postgres` 会先作为 live PostgreSQL data directory 实测。启动已有 PGDATA 前会补建 object storage 可能丢失的 PostgreSQL 空目录；`/persist/postgres-backups/` 会保留 timestamped `YYYYmmddTHHMMSSZ.sql.gz` dump，并更新普通文件 `latest.sql.gz`、`latest.created_at` 和 `latest.sha256`。默认 `tiered` 保留策略约等于：15 分钟内每分钟保留、2 小时内每 5 分钟保留、24 小时内每小时保留、7 天内每天保留，并受 `POSTGRES_BACKUP_RETAIN_COUNT` 上限约束；每次成功备份后才会清理旧备份。默认失败策略是 `fallback-to-runtime`：bucket PGDATA 起不来时，容器先确认旧 PostgreSQL 进程已停止，再只删除并重建 `${RUNTIME_ROOT}/postgres` scratch，绝不删除 `/persist/postgres`；随后在 dump 通过 `latest.sha256`、gzip 和非空校验后恢复。旧实例没有 `latest.sha256` 时会打印 warning 并只走 gzip/非空校验。恢复点最多只新到最近一次成功 dump，因此可能丢失之后已提交但尚未备份的事务。

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

### External PostgreSQL

bucket-lite 会优先尝试 `/persist/postgres` live PGDATA，并在失败时 fallback 到 `${RUNTIME_ROOT}/postgres` + dump restore。这个模式适合 demo 和 PoC，但不是强一致数据库持久化。如果要保留模型配置、Agent、Workflow 和运行记录，推荐使用外部 PostgreSQL：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `EXTERNAL_POSTGRES_ENABLED` | `false` | `true` 时入口脚本跳过本地 PostgreSQL init/start，Supervisor 的 `postgres` program 保持 idle |
| `EXTERNAL_POSTGRES_WAIT_SECONDS` | `120` | 启动时等待外部 PostgreSQL ready 的最长秒数 |
| `EXTERNAL_POSTGRES_REQUIRE_VECTOR` | `true` | `true` 时启动阶段确认 `DB_DATABASE` 和 `DB_PLUGIN_DATABASE` 可用 `pgvector` |

外部 PostgreSQL 模式仍使用同一组 `DB_HOST`、`DB_PORT`、`DB_USERNAME`、`DB_PASSWORD`、`DB_SSL_MODE`、`DB_DATABASE` 和 `DB_PLUGIN_DATABASE`。启用前需要先创建两个 database，并授予 `DB_USERNAME` 访问权限；如果当前账号不能 `CREATE EXTENSION vector`，需要数据库管理员提前在两个 database 中创建 `vector` extension。

外部 PostgreSQL 模式下，`postgres-backup` 默认 disabled，`/_admin/api/actions/force-postgres-backup` 也会返回备份 disabled。数据库备份应交给托管 PostgreSQL 自身的 snapshot/PITR 或运维流程。

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
| `DISABLE_TELEMETRY` | `true` | 延续 demo 的 telemetry-off 默认，关闭 upstream Community Telemetry install/heartbeat 上报 |
| `MARKETPLACE_API_URL` | `https://marketplace.dify.ai` | Marketplace API |
| `MARKETPLACE_URL` | `https://marketplace.dify.ai` | Marketplace Web |
| `MARKETPLACE_ENABLED` | `true` | 是否启用 Marketplace |

## OpenAPI / difyctl

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `OPENAPI_ENABLED` | `false` | 是否注册 `/openapi/v1/*` endpoint group |
| `OPENAPI_CORS_ALLOW_ORIGINS` | empty | `/openapi/v1/*` CORS allowlist；默认 same-origin |
| `OPENAPI_KNOWN_CLIENT_IDS` | `difyctl` | 允许发起 device flow 的 client id |
| `OPENAPI_RATE_LIMIT_PER_TOKEN` | `60` | `/openapi/v1/*` bearer token 每分钟请求限制 |
| `DEVICE_FLOW_APPROVE_RATE_LIMIT_PER_HOUR` | `10` | `/device` approve 相关限流 |
| `ENABLE_OAUTH_BEARER` | `false` | 是否接受 `dfoa_` / `dfoe_` bearer token |

Nginx 会把 `/openapi` 代理到内部 Dify API。`/openapi/v1/_health` 和 `/openapi/v1/_version` 可作为启用后的基础探针；`/_version` 返回的是上游 Dify 服务端版本，`difyctl version --check-compat` 按这个值判断兼容性，不按本仓库 `DIFY_VERSION` metadata 判断。

## Storage

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `STORAGE_TYPE` | `opendal` | Dify storage backend |
| `OPENDAL_SCHEME` | `fs` | OpenDAL scheme |
| `OPENDAL_FS_ROOT` | `/data/dify/storage` | 本地文件根目录 |

默认配置下，Dify 通过 OpenDAL `fs` 后端把文件对象写入 `OPENDAL_FS_ROOT`。bucket-lite 激活时，程序仍看到 `/data/dify/storage`，实际落盘路径是 `/persist/dify/storage`。

常见 Dify 文件对象 key 是相对 `OPENDAL_FS_ROOT` 的路径：

```text
upload_files/<tenant_id>/<file_id>.<ext>
tools/<tenant_id>/<file_id>.<ext>
```

对应的数据库元数据主要在 `upload_files.key` 和 `tool_files.file_key`。因此清理 Hugging Face Storage Bucket 配额时，不要直接删除整个 `/persist/dify/storage` 或只按目录名判断；应先从数据库 key 生成候选清单，做 dry-run 和备份，再联动删除 storage object 与对应元数据。当前工程没有提供默认 retention job，workflow 上传和工具产物会持续占用 bucket，直到上游业务逻辑或管理员清理它们。

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
| `SANDBOX_UID_POOL_MIN` | `1000` | HFS patched sandbox 的执行 UID pool 起点；HF rootless 环境默认只能使用映射的 Space user |
| `SANDBOX_UID_POOL_MAX` | `1001` | HFS patched sandbox 的执行 UID pool 终点（不含）；默认串行化为单 UID |
| `SANDBOX_RUN_GID` | `1000` | HFS patched sandbox 执行 GID；默认使用映射的 Space group |
| `SANDBOX_SELFCHECK_ENABLED` | `true` | 启动后一次性调用内部 `/v1/sandbox/run`，验证 Python code execution 热路径；要求 HTTP 200、JSON envelope 成功、`exit_code=0`、`error=""` 且 stdout 命中 marker |
| `SANDBOX_SELFCHECK_STRICT` | `false` | `false` 时自检失败只在 `/_ops/health.sandbox_exec` 标记 degraded；`true` 时让 health 失败 |
| `SANDBOX_SELFCHECK_RESULT_PATH` | `${RUNTIME_ROOT}/sandbox-selfcheck.json` | 自检结果文件；`ops-service` 只读读取，不包含 secret 原文 |
| `SANDBOX_SELFCHECK_TIMEOUT_SECONDS` | `30` | 等待 sandbox `/health` 并执行 probe 的总超时 |
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
| `PLUGIN_UV_CACHE_DIR` | `${RUNTIME_ROOT}/plugin-uv-cache` | Plugin Python 环境初始化使用的 uv cache；`with-plugin-env` 会映射为 `UV_CACHE_DIR` 并确保目录可写，避免回落到 `/home/user/.cache/uv` |
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

Plugin Daemon 会用 `plugin_unique_identifier` 作为 package bucket key 在 `PLUGIN_PACKAGE_CACHE_PATH` 下查找本地包，例如 `plugin_packages/langgenius/openai_api_compatible:<version>@<checksum>`。本地 runtime watchdog 则从 `PLUGIN_INSTALLED_PATH` 枚举已安装插件并拉起 local runtime；Redis `plugin_state` 是 cluster routing 视图，单容器本机 runtime 已 ready 时它可能不是唯一证据。bucket-lite 下 wrapper 会让 Plugin Daemon 直接使用 `/persist/plugin_daemon` 作为 storage root；不要把 `PLUGIN_STORAGE_LOCAL_ROOT` 强制回 `/data/plugin_daemon`，否则 Go `filepath.WalkDir` 不会跟随 `/data/plugin_daemon/plugin` 这个 symlink root，重建后已安装插件可能不会被重新拉起。重建后如果数据库中的 `plugin_unique_identifier` 还在、但 package cache、installed bucket 或 local runtime ready 证据缺失，Dify 页面可能仍显示 provider 配置，实际 plugin runtime 却无法重新拉起。用 `/_ops/persistence` 检查 `plugin_storage_layout_issues`、`missing_package_files`、`missing_installed_files`、`missing_runtime_states`、`plugin_runtime_state.checked` 和 `plugin_runtime_state.identifiers[].log.ready` 可以直接确认这类错配；`scripts/hf-space-smoke.sh` 也会把这些字段作为 `ops-persistence` 回归条件。

`with-plugin-env` 会把 `DB_PLUGIN_DATABASE` 映射到 Plugin Daemon 期望的 `DB_DATABASE`，并把镜像内只读的 `/opt/dify/plugin-runtime-patches` 前置到 Plugin runtime 的 `PYTHONPATH`。该 shim 不修改已签名 `.difypkg`，也不改 scalar timeout、credential validation 的 `(10, 300)` 或其他 request shape；只有运行时请求精确使用 `(10, MAX_REQUEST_TIMEOUT)` 时才提高 connect/TLS timeout。它通过精确 SDK module import hook 延迟安装 Requests wrapper，确保 `dify_plugin` 先完成 `gevent.monkey.patch_all()`，不会在启动期提前导入 `requests`/`ssl`。官方 SDK 移除固定 10 秒 tuple 后，timeout rewrite 自动不再生效。

`PLUGIN_SSL_EOF_MAX_RETRIES=1` 是独立的 opt-in 恢复门，只作用于 `dify_plugin.interfaces.model.openai_compatible.llm._generate` 调用栈中、`requests.exceptions.SSLError` 的包装链明确包含 `ssl.SSLEOFError` 或 `UNEXPECTED_EOF_WHILE_READING` 的失败。它不会 retry credential validation、其他 SDK 调用、HTTP status、connect/read timeout 或普通 connection error；第二次失败会原样抛出。虽然异常发生在 Requests 返回 response 之前，模型 `POST` 仍可能已经到达上游，因此 retry 可能产生重复推理或双计费；默认保持 `0`，生产部署应优先在 provider/gateway 或上游 SDK 中使用可观测、可幂等的 retry 机制。

部署后可通过 `/_ops/process-env?service=plugin-daemon&runtime_scan=true&runtime_inspect=true` 脱敏回读 `PLUGIN_SSL_EOF_MAX_RETRIES`。该字段属于固定 safe-key allowlist，只返回 `0` 或 `1` 等配置值，不返回 provider credential；应同时核对 Supervisor 进程和实际 Plugin runtime 的值，避免只改 Space variable 但旧 runtime 尚未接管。

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

`/_ops/health` 还会暴露 `sandbox_exec`，它来自启动后一次性 `sandbox-selfcheck` 结果，覆盖真实 `python3` code execution 路径。这个探针会解析 sandbox response，要求 `data.exit_code=0`、`data.error=""` 和 stdout marker，而不是只看 HTTP 200。默认 `SANDBOX_SELFCHECK_STRICT=false`，失败时 `/_ops/health` 会出现 `degraded=true` 和 `warnings`，但不会因为一次性探针失败直接让 Space readiness 掉线；需要 CI/受控验证时可设为 `true`。

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
