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
MARKETPLACE_ENABLED=false
SANDBOX_ENABLE_NETWORK=false
FORCE_VERIFYING_SIGNATURE=false
OPS_TOKEN=<fixed-random-token>
ADMIN_ENABLED=false
PERSIST_MODE=auto
REDIS_PERSISTENCE=false
POSTGRES_BACKUP_ENABLED=auto
```

建议 Secrets：

```env
SECRET_KEY=<固定强随机值>
PLUGIN_DAEMON_KEY=<固定强随机值>
PLUGIN_DIFY_INNER_API_KEY=<固定强随机值>
CODE_EXECUTION_API_KEY=<固定强随机值>
SANDBOX_API_KEY=<固定强随机值>
```

如果只做一次性公开演示，可以不设置 Secret；如果要多次重启后保持登录、文件 URL、插件凭据一致，必须设置固定 Secret 或把 bucket 挂到 `/persist`，让自动生成的 `/data/config/generated.env` 实际落到 `/persist/config/generated.env`。

bucket-lite 模式下会持久化：

```text
/persist/postgres
/persist/config/generated.env
/persist/dify/storage
/persist/plugin_daemon/plugin
/persist/plugin_daemon/assets
/persist/postgres-backups/latest.sql.gz
```

默认会先尝试把 `/persist/postgres` 当 live PostgreSQL data directory 使用。若 bucket mount 的文件系统语义导致 PostgreSQL 无法启动，`POSTGRES_BUCKET_FAILURE_MODE=fallback-to-runtime` 会让容器退回 `/tmp/dify-aio/postgres`，并继续把周期 dump 写到 `/persist/postgres-backups/latest.sql.gz`。

这些目录不会占用 bucket：

```text
/tmp/dify-aio/logs
/tmp/dify-aio/run
/tmp/dify-aio/redis
/tmp/dify-aio/hf-cache
/tmp/dify-aio/plugin_packages
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

`/_ops/` 是只读诊断入口，主要用于查看 dashboard、supervisor 状态、内部健康探针、系统资源、Prometheus-style metrics、非敏感配置摘要和近期错误日志。不要把 `OPS_TOKEN` 当作生产级安全边界；公开 Space 建议设置为 Private 或 Protected。

`/_admin/` 是独立管理入口，默认 `ADMIN_ENABLED=false` 并返回 404。只有在 Private/Protected Space 或受控演示场景中才建议设置 `ADMIN_ENABLED=true` 和强随机 `ADMIN_TOKEN`；文件管理由 `ADMIN_FILES_*` 独立控制，Web terminal 当前只保留 `WEBSSH_*` 变量、不暴露路由。

完整工程文档见 [docs/README.md](./docs/README.md)。其中 [Deployment Guide](./docs/deployment.md) 覆盖部署流程，[Operations Runbook](./docs/ops-runbook.md) 覆盖运维、502 排障、日志入口和发布后验收。
