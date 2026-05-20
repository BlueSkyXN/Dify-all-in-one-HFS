# Bucket-Lite Persistence Drill

本文档用于演练 Hugging Face Storage Bucket / `/persist` 持久化边界。目标是验证当前实现能否在 bucket-lite 模式下保留核心状态，并在 PostgreSQL live data directory 不适合 bucket mount 时走可观察的 fallback / dump restore 路径。

本演练不要使用正在给课程或 PoC 展示的正式 Space。优先使用新的临时 Docker volume、临时 Space 或已明确可丢弃的数据环境。

## 演练目标

需要分别记录：

```text
Commit SHA:
Image tag or Space:
PERSIST_MODE:
POSTGRES_BUCKET_FAILURE_MODE:
PERSIST_ROOT:
RUNTIME_ROOT:
Storage backend:
```

核心验收点：

- `/persist` 是挂载点且 UID `1000` 可写。
- `/data/config/generated.env` 能跨重启保留。
- `/data/dify/storage`、`/data/plugin_daemon/plugin` 和 `/data/plugin_daemon/assets` 指向 `/persist`。
- PostgreSQL 能在 `/persist/postgres` 正常启动，或明确 fallback 到 `${RUNTIME_ROOT}/postgres`。
- `/persist/postgres-backups/latest.sql.gz` 可生成。
- `/_ops/health` 和 `/_ops/errors` 能说明当前状态。

## 本地 Docker 演练

构建并启动：

```bash
scripts/build.sh
scripts/run-demo.sh
```

确认容器内映射：

```bash
docker exec dify-aio-hf-demo sh -lc '
set -eu
id
mount | grep " /persist " || true
ls -ld /persist /data /data/config /data/postgres
find /data -maxdepth 3 -type l -ls | sort
test -f /data/config/generated.env
'
```

确认健康和错误摘要：

```bash
OPS_TOKEN=dify_ops_demo_token scripts/hf-space-smoke.sh http://localhost:8080
curl -H "X-Ops-Token: dify_ops_demo_token" http://localhost:8080/_ops/health
curl -H "X-Ops-Token: dify_ops_demo_token" http://localhost:8080/_ops/errors
```

重启并复核 generated env：

```bash
docker exec dify-aio-hf-demo sh -lc 'sha256sum /data/config/generated.env'
docker restart dify-aio-hf-demo
sleep 30
docker exec dify-aio-hf-demo sh -lc 'sha256sum /data/config/generated.env'
```

两次 hash 应一致。若不一致，说明 `/data/config` 没有落到持久化边界。

## PostgreSQL Backup 检查

等待 backup loop 写出 dump：

```bash
docker exec dify-aio-hf-demo sh -lc '
ls -lh /persist/postgres-backups || true
test -s /persist/postgres-backups/latest.sql.gz
cat /persist/postgres-backups/latest.created_at
'
```

如果 dump 没有生成，查看日志：

```bash
docker logs dify-aio-hf-demo 2>&1 | grep -i "postgres-backup" | tail -n 80
docker exec dify-aio-hf-demo sh -lc 'tail -n 120 /data/logs/postgres-backup.log /data/logs/postgres-backup.err 2>/dev/null || true'
```

## Fallback 行为检查

默认：

```text
POSTGRES_BUCKET_FAILURE_MODE=fallback-to-runtime
```

如果 `/persist/postgres` 无法作为 live PGDATA 启动，entrypoint 应打印诊断并切到：

```text
${RUNTIME_ROOT}/postgres
```

检查方式：

```bash
docker exec dify-aio-hf-demo sh -lc '
readlink /data/postgres || true
ls -ld /tmp/dify-aio/postgres /persist/postgres 2>/dev/null || true
grep -i "fallback" /data/logs/*.log 2>/dev/null || true
'
```

如果演练目标是严格失败而不是 fallback，使用独立环境设置：

```env
POSTGRES_BUCKET_FAILURE_MODE=exit
```

此模式下 bucket PGDATA 失败应让容器退出，便于及早发现持久化语义问题。

## Hugging Face Space 演练

只在需要验证 live Space 时执行。

发布前记录目标 SHA：

```bash
git rev-parse origin/main
git remote -v
```

推送到 Space remote 后回读：

```bash
git push hf main
hf spaces info BlueSkyXN/dify-all-in-one
```

必须确认：

```text
runtime.stage = RUNNING
runtime.raw.sha = <expected sha>
```

线上 smoke：

```bash
OPS_TOKEN=your-configured-ops-token \
  scripts/hf-space-smoke.sh https://blueskyxn-dify-all-in-one.hf.space
```

只读诊断：

```bash
curl -H "X-Ops-Token: $OPS_TOKEN" \
  https://blueskyxn-dify-all-in-one.hf.space/_ops/health

curl -H "X-Ops-Token: $OPS_TOKEN" \
  https://blueskyxn-dify-all-in-one.hf.space/_ops/errors
```

## 证据模板

```text
Date:
Environment:
Commit SHA:
Space runtime.raw.sha:
PERSIST_MODE:
POSTGRES_BUCKET_FAILURE_MODE:
PERSIST_ROOT:
RUNTIME_ROOT:

/persist mounted:
/persist writable by UID 1000:
generated.env hash before restart:
generated.env hash after restart:
PostgreSQL data location:
PostgreSQL fallback observed:
latest.sql.gz exists:
latest.sql.gz size:

Smoke result:
/_ops/health summary:
/_ops/errors summary:
App/build log references:

Conclusion:
Follow-up:
```
