# Hugging Face Space 部署说明

本工程已经按 Hugging Face Docker Space 形态调整：

- 根目录 `README.md` 带 `sdk: docker` 和 `app_port: 7860` 元数据。
- 根目录 `Dockerfile` 是 Space 的构建入口。
- 容器运行时使用 UID 1000 的 `user` 用户。
- 推荐把 Hugging Face Storage Bucket 挂到 `/persist`；核心状态写入 `/persist`，日志、run、cache 写入 `/tmp/dify-aio`。
- Nginx 对外监听 `7860`，内部转发到 Dify Web/API/Plugin Daemon。
- 如果运行时存在 `SPACE_HOST` 且 `PUBLIC_URL` 未设置，会自动变成 `https://${SPACE_HOST}`。

建议 Space Settings：

```text
Hardware: CPU Upgrade
Storage Bucket: mount 到 /persist
Visibility: Private 或 Protected
```

建议 Variables：

```env
PERSIST_MODE=bucket
POSTGRES_BUCKET_FAILURE_MODE=fallback-to-runtime
```

建议 Secrets：

```env
OPS_TOKEN=<强随机值>
DB_PASSWORD=<固定 demo 值或强随机值>
REDIS_PASSWORD=<固定 demo 值或强随机值>
SECRET_KEY=<固定 demo 值或强随机值>
PLUGIN_DAEMON_KEY=<固定 demo 值或强随机值>
PLUGIN_DIFY_INNER_API_KEY=<固定 demo 值或强随机值>
CODE_EXECUTION_API_KEY=<固定 demo 值或强随机值>
```

本地只维护一个 `.env.local` 作为 HF 配置事实源：其中 `[HF Secrets]` 上传到 Space Secrets，`[HF Variables]` 上传到 Space Variables；与 `docker/dify.env.runtime` 默认值一致的变量不要重复上传。不要再维护 `.env.hf.local` 或 `local/hf-space.env` 这类并行 env 快照。

不要单独上传 `SANDBOX_API_KEY` 和 `INNER_API_KEY_FOR_PLUGIN`，除非你明确要拆分内部 key。默认情况下，`SANDBOX_API_KEY` 继承 `CODE_EXECUTION_API_KEY`，`INNER_API_KEY_FOR_PLUGIN` 继承 `PLUGIN_DIFY_INNER_API_KEY`。

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

默认会先尝试把 `/persist/postgres` 当 live PostgreSQL data directory 使用。若 bucket mount 的文件系统语义导致 PostgreSQL 无法启动，`POSTGRES_BUCKET_FAILURE_MODE=fallback-to-runtime` 会让容器退回 `/tmp/dify-aio/postgres`，并继续把周期 dump 写到 `/persist/postgres-backups/`，校验后更新 `latest.sql.gz`。默认首次备份延迟 15 秒、后续间隔 60 秒，使用 `gzip -1` 快速压缩，并按 tiered retention 保留近端密、远端稀的恢复点；已开启 `/_admin` 时，可在部署或重启前调用 `/_admin/api/actions/force-postgres-backup` 强制生成一次 dump。`/_ops/persistence` 会只读显示 latest backup age、latest error 和 `safe_to_restart` 建议信号。

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

`/_ops/` 是只读诊断入口，主要用于查看 dashboard、Supervisor XML-RPC 状态、内部健康探针、系统资源、Prometheus-style metrics、非敏感配置摘要、持久化/插件包/插件 runtime state 摘要和近期错误日志。不要把 `OPS_TOKEN` 当作生产级安全边界；公开 Space 必须覆盖默认 token，并建议设置为 Private 或 Protected。

`/_ops/` 和 `/_admin/` dashboard 均支持 English / 中文切换，默认跟随浏览器语言，并把选择保存在浏览器本地。

`/_admin/` 是独立管理入口，默认 `ADMIN_ENABLED=false` 并返回 404。只有在 Private/Protected Space 或受控演示场景中才建议设置 `ADMIN_ENABLED=true` 和强随机 `ADMIN_TOKEN`；开启后可查看最近 admin 审计事件，文件管理由 `ADMIN_FILES_*` 独立控制，rename/delete 还要 `ADMIN_FILES_DESTRUCTIVE_ENABLED=true`。Web terminal / WebSSH 已从 HF Space runtime 中移除，不再支持通过 `/_admin/terminal/` 访问容器 shell。

完整工程文档见 [docs/README.md](./docs/README.md)。其中 [Deployment Guide](./docs/deployment.md) 覆盖部署流程，[Operations Runbook](./docs/ops-runbook.md) 覆盖运维、502 排障、日志入口和发布后验收。
