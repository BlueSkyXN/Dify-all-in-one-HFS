# 目标漂移记录

## Entries

### 2026-05-19 — 管理面从本地计划稿进入仓库主线

- **Old goal:** 以 `/_ops/*` 为主的只读诊断面，写操作仍停留在独立计划稿讨论。
- **Trigger / reason:** 需要在不污染 `/_ops` 的前提下，为 demo 环境提供最小受控管理能力。
- **New goal:** 保持 `/_ops` 只读，同时在默认关闭的 `/_admin/*` 下交付 token/cookie/csrf、白名单 action、file manager 和 terminal placeholder。
- **Affected capabilities:** CAP-005，CAP-006，CAP-007
- **Reusable artifacts:** `ops-service`、Nginx 路由、Supervisor、smoke script、`local/ops-admin-plan.md`
- **Refactor / rework required:** 对齐高层文档、AGENTS、runtime 默认值和 terminal 能力边界。
- **Current status:** in progress
- **Evidence source:** `local/ops-admin-plan.md:1-54`, `README.md:181-189`, `docker/admin_service.py:247-347`, `docker/nginx.conf:82-112`

## Removed claims

| Date | Removed item | Was claimed in | Reason for removal |
|---|---|---|---|
| — | 当前首次 research snapshot 无已删除 claim | — | — |
