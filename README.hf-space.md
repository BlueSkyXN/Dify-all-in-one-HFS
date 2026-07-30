# Hugging Face Space 部署说明

本工程已经按 Hugging Face Docker Space 形态调整：

- 根目录 `README.md` 带 `sdk: docker` 和 `app_port: 7860` 元数据。
- 根目录 `Dockerfile` 是 Space 的构建入口。
- 容器运行时使用 UID 1000 的 `user` 用户。
- 推荐把 Hugging Face Storage Bucket 挂到 `/persist`；核心状态写入 `/persist`，日志、run、cache 写入 `/tmp/dify-aio`。
- Nginx 对外监听 `7860`，内部转发到 Dify Web/API/Plugin Daemon。
- 如果运行时存在 `SPACE_HOST` 且 `PUBLIC_URL` 未设置，会自动变成 `https://${SPACE_HOST}`。
- Dify Web SSR 使用 `SERVER_CONSOLE_API_URL=http://127.0.0.1:5001` 直连同容器 API，不通过 Hugging Face 公网域名回环。

建议 Space Settings：

```text
Hardware: CPU Upgrade
Storage Bucket: mount 到 /persist
Visibility: Protected
Registered/formal-use Buckets: Private
```

Protected 是本仓 HFS v2.1 的明确 Space contract；不能用 `SpaceInfo.private=true`
代替，因为这个布尔值无法区分 Protected 与 Private。formal workflow 会通过 exact
repository ID 和 `repo_type=space` 的 settings surface 在首次写入前、写入后读回
Protected，并同时确认登记 Bucket 与当前 artifact manifest 使用的 Bucket 都是 Private。

Artifact Variables（必须按已批准 slot 填入）：

```env
DIFY_ARTIFACT_MANIFEST_HF_URI=hf://buckets/<namespace>/hfs-dist/dify-all-in-one/release/manifest.json
DIFY_ARTIFACT_EXPECTED_SOURCE_REF=<40-char-producer-commit>
DIFY_ARTIFACT_MAX_BYTES=4294967296
```

建议 Variables：

```env
PERSIST_MODE=bucket
POSTGRES_BUCKET_FAILURE_MODE=exit
```

`DIFY_ARTIFACT_MANIFEST_HF_URI` 是唯一 runtime delivery 输入；缺失、错误或 manifest/archive/lock 不一致会让启动 fail-closed。不要设置 direct artifact URL、路径、S3 fallback，也不要将 hfs-dist 挂载到 `/persist`。

建议 Secrets：

```env
DIFY_ARTIFACT_BEARER_TOKEN=<用于私有 hfs-dist 下载的 token>
OPS_TOKEN=<强随机值>
DB_PASSWORD=<固定 demo 值或强随机值>
REDIS_PASSWORD=<固定 demo 值或强随机值>
SECRET_KEY=<固定 demo 值或强随机值>
PLUGIN_DAEMON_KEY=<固定 demo 值或强随机值>
PLUGIN_DIFY_INNER_API_KEY=<固定 demo 值或强随机值>
CODE_EXECUTION_API_KEY=<固定 demo 值或强随机值>
SANDBOX_API_KEY=<与 CODE_EXECUTION_API_KEY 相同的新值>
DIFY_AGENT_SERVER_SECRET_KEY=<强随机值>
DIFY_AGENT_SHELLCTL_AUTH_TOKEN=<强随机值>
```

本地只维护一个 `.env` 作为 HF 配置事实源：其中 `[HF Secrets]` 上传到 Space Secrets，`[HF Variables]` 上传到 Space Variables；与 `docker/dify.env.runtime` 默认值一致的变量不要重复上传。不要再维护 `.env.hf.local` 或 `local/hf-space.env` 这类并行 env 快照。

formal clean profile 显式登记 `SANDBOX_API_KEY`，并要求它与 `CODE_EXECUTION_API_KEY` 使用同一新生成值；`INNER_API_KEY_FOR_PLUGIN` 仍从 `PLUGIN_DIFY_INNER_API_KEY` 派生，不单独上传。

bucket-lite 模式下会持久化：

```text
/persist/postgres
/persist/config/generated.env
/persist/dify/storage
/persist/plugin_daemon/plugin
/persist/plugin_daemon/assets
/persist/plugin_daemon/plugin_packages
/persist/postgres-backups/latest.sql.gz
/persist/postgres-backups/YYYYmmddTHHMMSSZ.sql.gz
```

如果显式设置 `PLUGIN_CWD_PERSISTENCE=true`，还会持久化 `/persist/plugin_daemon/cwd`。

默认会先尝试把 `/persist/postgres` 当 live PostgreSQL data directory 使用。若 bucket mount 的文件系统语义导致 PostgreSQL 无法启动，`POSTGRES_BUCKET_FAILURE_MODE=fallback-to-runtime` 会在确认旧 PostgreSQL 已停止后重建全新的 `/tmp/dify-aio/postgres` scratch PGDATA，再从最近的有效 dump 恢复；不会删除或复用 `/persist/postgres`。恢复点最多只新到最近一次成功 dump，可能落后于故障前最后提交的事务。容器会继续把周期 dump 写到 `/persist/postgres-backups/`，校验后更新 `latest.sql.gz`。默认首次备份延迟 15 秒、后续间隔 60 秒，使用 `gzip -1` 快速压缩，并按 tiered retention 保留近端密、远端稀的恢复点；已开启 `/_admin` 时，可在部署或重启前调用 `/_admin/api/actions/force-postgres-backup` 强制生成一次 dump。`/_ops/persistence` 会只读显示 latest backup age、latest error 和 `safe_to_restart` 建议信号。

如果需要强持久化数据库状态，使用外部 PostgreSQL，并设置 `EXTERNAL_POSTGRES_ENABLED=true`、`DB_HOST`、`DB_PORT`、`DB_USERNAME`、`DB_PASSWORD`、`DB_DATABASE`、`DB_PLUGIN_DATABASE` 和必要的 `DB_SSL_MODE`。外部 PostgreSQL 模式要求两个 database 已创建并可用 `pgvector`，本容器不会再把本地 `/data/postgres` 当权威数据库。

bucket-lite 下 Plugin Daemon 默认直接以 `/persist/plugin_daemon` 作为 `PLUGIN_STORAGE_LOCAL_ROOT`。`/data/plugin_daemon/*` 仍保留为兼容路径，但启动扫描必须避开 symlink root，否则重建后 installed 插件文件可能存在却不会自动 relaunch runtime。

这些目录不会占用 bucket：

```text
/tmp/dify-aio/logs
/tmp/dify-aio/run
/tmp/dify-aio/redis
/tmp/dify-aio/hf-cache
/tmp/dify-aio/plugin_cwd
```

## 运维诊断

部署成功后可以用：

```bash
curl https://your-space.hf.space/nginx-health
curl https://your-space.hf.space/healthz
curl -H "X-Ops-Token: $OPS_TOKEN" https://your-space.hf.space/_ops/health
```

也可以运行仓库脚本：

```bash
OPS_TOKEN=<fixed-random-token> \
  scripts/hf-space-smoke.sh https://your-space.hf.space
```

`/_ops/` 是只读诊断入口，主要用于查看 dashboard、Supervisor XML-RPC 状态、内部健康探针、系统资源、Prometheus-style metrics、非敏感配置摘要、持久化/插件包/插件 runtime state 摘要和近期错误日志。不要把 `OPS_TOKEN` 当作生产级安全边界；Protected Space 必须覆盖默认 token。

`/_ops/` 和 `/_admin/` dashboard 均支持 English / 中文切换，默认跟随浏览器语言，并把选择保存在浏览器本地。

`/_admin/` 是独立管理入口，默认 `ADMIN_ENABLED=false` 并返回 404。只有在 Private/Protected Space 或受控演示场景中才建议设置 `ADMIN_ENABLED=true` 和强随机 `ADMIN_TOKEN`；开启后可查看最近 admin 审计事件，文件管理由 `ADMIN_FILES_*` 独立控制，rename/delete 还要 `ADMIN_FILES_DESTRUCTIVE_ENABLED=true`。Web terminal / WebSSH 已从 HF Space runtime 中移除，不再支持通过 `/_admin/terminal/` 访问容器 shell。

完整工程文档见 [docs/README.md](./docs/README.md)。其中 [Deployment Guide](./docs/deployment.md) 覆盖部署流程，[Operations Runbook](./docs/ops-runbook.md) 覆盖运维、502 排障、日志入口和发布后验收。
