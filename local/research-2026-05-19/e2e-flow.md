# 端到端主链路

## Primary flow

```text
Hugging Face / local browser request
  ↓
Nginx :7860 接收外部路径
  ↓
按路径转发到 Dify Web / Dify API / Plugin Daemon / Ops / Admin
  ↓
entrypoint 预先准备的 PostgreSQL / Redis / generated secrets / storage 布局被长期进程使用
  ↓
Dify API 按需访问 PostgreSQL、Redis、本地文件、Plugin Daemon、Sandbox
  ↓
响应经 Nginx 返回浏览器或 API client
  ↓
运行状态与错误进入 stdout、`/data/logs`、`ADMIN_AUDIT_LOG`、`/persist/postgres-backups/latest.sql.gz`
```

## Step detail

| # | Step | Triggered by | Component | Function points | Human-in-loop? | AI/ML involved? | Status | Evidence |
|---|---|---|---|---|---|---|---|---|
| 1 | 外部请求到达单一公网入口 `7860` | browser / curl / Space iframe | PBS-003 `docker/nginx.conf` | FP-011, FP-013 | 否 | 否 | implemented | `docker/nginx.conf:46-61` |
| 2 | 路由到 Web/API/Ops/Admin/Plugin | Nginx path match | PBS-003 `docker/nginx.conf` | FP-011, FP-012 | 否 | 否 | implemented | `docker/nginx.conf:63-157` |
| 3 | 长期进程已由 bootstrap 与 supervisor 准备就绪 | container entrypoint + supervisord | PBS-002 + PBS-003 | FP-004, FP-005, FP-006, FP-008, FP-009, FP-010 | 否 | 否 | implemented | `docker/entrypoint.sh:644-658`, `docker/supervisord.conf:17-156` |
| 4 | Dify API 读取 DB/Redis/storage，并可调用 Plugin/Sandbox | API request or internal worker flow | PBS-002 + PBS-003 | FP-006, FP-008, FP-014, FP-015 | 否 | 是，代码执行/插件调用 | implemented | `docker/with-plugin-env:14-64`, `docker/with-sandbox-env:14-32` |
| 5 | 响应返回客户端；同时 logs/metrics/errors 对 operator 可见 | Nginx response + ops/admin endpoint | PBS-004 | FP-016, FP-017, FP-018, FP-019, FP-021 | 可选，operator 诊断时需要 | 否 | implemented | `docker/ops_service.py:1241-1269`, `docker/admin_service.py:1110-1115` |
| 6 | 受控管理动作写入 audit log；PostgreSQL dump 定期写入 backup | admin POST / backup loop | PBS-002 + PBS-004 | FP-007, FP-021, FP-022 | 是，需 operator 明确触发 | 否 | implemented, blocked | `docker/admin_service.py:278-295`, `docker/postgres-backup-loop:52-71` |

## Failure points

| Step | Failure mode | Impact | Linked blocker |
|---|---|---|---|
| 3 | `/persist/postgres` 的文件系统语义不满足 live PGDATA 要求 | 容器可能 fallback 到 runtime PGDATA 或直接退出 | BLK-004 |
| 5 | `/_ops` 和 `/_admin` 没有提交内执行证据 | 研究只能保守评到 M4 | BLK-002 |
| 6 | `/_admin/terminal/` 不是实终端 | break-glass 调试链路断在 placeholder | BLK-001 |
| 1/2 | Marketplace/admin 高层合同与 runtime 默认值不一致 | operator 可能按错预期配置或汇报 | BLK-003 |

## Alternative or secondary flows

| Flow | When it runs | Status |
|---|---|---|
| `/_ops/*` 只读诊断流 | operator 排障、查看资源与日志时 | implemented |
| `/_admin/*` 受控管理流 | admin-enabled 场景中执行重启/文件查看时 | implemented, blocked |
| PostgreSQL backup/restore 流 | bucket-lite 启用且需要 dump 兜底时 | implemented, blocked |

## Demo chain

- **Input sample:** `http://localhost:8080` 或 `https://blueskyxn-dify-all-in-one.hf.space`
- **Steps to reproduce:**
  1. 运行 `scripts/build.sh` 与 `scripts/run-demo.sh`，或确认 HF runtime 已是目标 SHA。
  2. 打开 `/`、`/console/api/setup`、`/healthz`。
  3. 用 `OPS_TOKEN` 访问 `/_ops/health`、`/_ops/system`、`/_ops/errors`。
  4. 若明确启用 admin，再用 `ADMIN_TOKEN` 访问 `/_admin/api/status`。
- **Expected output:** Web 根路径返回 200；`/healthz` 200；`/_ops/*` 返回 JSON 诊断；admin-disabled 默认 404。
- **Failure fallback:** 若根路径 502，转到 `/_ops/health`、`/_ops/status`、`/_ops/errors` 和 `hf spaces info` 做分层排障。[docs/ops-runbook.md:331-359]
