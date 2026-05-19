# 交付成熟度

## Maturity table

| Capability | Baseline maturity | Critical path maturity | Status tags | Evidence anchor | Notes |
|---|---|---|---|---|---|
| CAP-001 镜像组装与官方资产复用 | M4 | M4 | specified, implemented, blocked | `Dockerfile:27-49`, `Dockerfile:80-108` | 代码完整，但缺少构建证据 |
| CAP-002 启动初始化与持久化编排 | M4 | M4 | specified, implemented, blocked | `docker/entrypoint.sh:171-211`, `docker/entrypoint.sh:561-658` | init/fallback 逻辑完整，但无提交内运行证据 |
| CAP-003 进程编排与单端口请求路由 | M4 | M4 | specified, implemented, blocked | `docker/supervisord.conf:17-156`, `docker/nginx.conf:46-157` | 路由与编排存在，未见回放 |
| CAP-004 Plugin 与 Sandbox 适配 | M4 | M4 | specified, implemented, blocked | `docker/with-plugin-env:14-64`, `docker/with-sandbox-env:14-32` | wrapper/migration 在，但无插件/沙箱 smoke |
| CAP-005 只读运维诊断 | M4 | M4 | specified, implemented, operable, blocked | `docker/ops_service.py:433-464`, `docker/ops_service.py:608-693` | 具备 operability 设计，但无测试/运行记录 |
| CAP-006 受控管理与文件边界 | M4 | M4 | specified, implemented, blocked, changed | `docker/admin_service.py:95-152`, `docker/admin_service.py:247-347`, `docker/webssh_entrypoint.sh:47-60` | admin code 已进入主线，terminal 仍未交付 |
| CAP-007 部署验证与运维文档 | M4 | M4 | specified, implemented, blocked | `scripts/hf-space-smoke.sh:160-177`, `docs/deployment.md:27-119` | 流程齐全，但证据链仍是人工 |

## Detail

### CAP-001 镜像组装与官方资产复用

- **Baseline maturity:** M4 — Implemented
- **Critical path maturity:** M4 — Implemented
- **Why these levels:** `Dockerfile` 已明确声明 build args、上游 image stages、runtime package install 和最终 entrypoint/healthcheck。[Dockerfile:17-22] [Dockerfile:27-49] [Dockerfile:141-195]
- **Why not the next level:** 仓库内没有对应 commit 的 build 成功记录，无法把能力保守提升到 M5。关联 `BLK-004`。
- **Status tags:** specified;implemented;blocked
- **Sub-module variance:** `scripts/build.sh` 已经把最小 build path 固化为单命令，但不等于实际 build 证据。[scripts/build.sh:1-4]
- **Path to next level:** 先完成 WP-002，把 build 结果和 smoke 结果绑定到 commit。

### CAP-002 启动初始化与持久化编排

- **Baseline maturity:** M4 — Implemented
- **Critical path maturity:** M4 — Implemented
- **Why these levels:** `entrypoint.sh` 实现了 bucket-lite、generated secrets、PostgreSQL init/fallback/restore、Redis/Sandbox config 和 Dify migration 的完整顺序。[docker/entrypoint.sh:171-211] [docker/entrypoint.sh:561-658]
- **Why not the next level:** 没有提交内日志证明这些分支曾在本项目版本上实际跑通，尤其是 PGDATA fallback 分支。关联 `BLK-002`、`BLK-004`。
- **Status tags:** specified;implemented;blocked
- **Sub-module variance:** `validate_ident` 和 `PUBLIC_URL` 派生规则清晰，但仍属代码证据层面。[docker/entrypoint.sh:76-83] [docker/dify.env.runtime:34-53]
- **Path to next level:** 对 bucket 模式和 fallback 模式分别拿到一组 smoke/log 证据。

### CAP-003 进程编排与单端口请求路由

- **Baseline maturity:** M4 — Implemented
- **Critical path maturity:** M4 — Implemented
- **Why these levels:** Supervisor graph、dependency waiter 和 Nginx route map 均已编码，且 smoke 脚本也已声明相关 contract。[docker/supervisord.conf:17-156] [docker/nginx.conf:46-157] [scripts/hf-space-smoke.sh:160-177]
- **Why not the next level:** 没有已保存的运行态回读去证明 public route、admin-disabled、iframe header 在目标 commit 上都有效。关联 `BLK-004`。
- **Status tags:** specified;implemented;blocked
- **Sub-module variance:** iframe header contract 比其他路由更接近可验证，因为 smoke 逻辑已经写好。[scripts/hf-space-smoke.sh:127-158]
- **Path to next level:** 先以 WP-001 对齐 contract，再以 WP-002 取得 smoke 证据。

### CAP-004 Plugin 与 Sandbox 适配

- **Baseline maturity:** M4 — Implemented
- **Critical path maturity:** M4 — Implemented
- **Why these levels:** Plugin 和 Sandbox 的 wrapper、migration/start 命令、默认安全变量均在仓库内有明确定义。[docker/with-plugin-env:14-64] [docker/with-sandbox-env:14-32] [docker/supervisord.conf:47-65]
- **Why not the next level:** 没有插件安装、sandbox code execution 或 migration success 的提交内证据。关联 `BLK-002`。
- **Status tags:** specified;implemented;blocked
- **Sub-module variance:** Sandbox 的 no-network 默认值与 rootless 清理逻辑比较明确；Plugin 的 upgrade 风险更高。[docker/dify.env.runtime:156-179] [docker/dify.env.runtime:181-214]
- **Path to next level:** 增加至少一条 plugin/sandbox smoke 场景，并纳入升级清单。

### CAP-005 只读运维诊断

- **Baseline maturity:** M4 — Implemented
- **Critical path maturity:** M4 — Implemented
- **Why these levels:** `ops-service` 已覆盖健康聚合、资源概览、metrics、日志白名单、错误摘要和 HTML dashboard，且 docs 对使用方式有完整说明。[docker/ops_service.py:433-464] [docker/ops_service.py:608-693] [docs/ops-runbook.md:49-84]
- **Why not the next level:** 仓库没有证明这些 endpoint 在当前提交上已经跑通；自动化验证也缺失。关联 `BLK-002`。
- **Status tags:** specified;implemented;operable;blocked
- **Sub-module variance:** 文档层面的 operability 较强，但仍不能替代运行证据。
- **Path to next level:** 让 `/_ops/*` 至少拿到一组本地或 live smoke 回读，并为关键 endpoint 补自动化检查。

### CAP-006 受控管理与文件边界

- **Baseline maturity:** M4 — Implemented
- **Critical path maturity:** M4 — Implemented
- **Why these levels:** `admin-service` 已实现独立 token、cookie session、CSRF、action catalog、file manager root confinement 和 audit log；`/_admin/terminal/` 也已有 auth route 与 placeholder 行为。[docker/admin_service.py:95-152] [docker/admin_service.py:350-587] [docker/nginx.conf:86-112]
- **Why not the next level:** terminal 没有真实终端能力，admin-enabled 流程也缺少提交内运行证据。关联 `BLK-001`、`BLK-003`。
- **Status tags:** specified;implemented;blocked;changed
- **Sub-module variance:** action/file manager 比 terminal 更成熟；terminal 仍处于“合同已出现，真实能力未交付”的状态。
- **Path to next level:** 先完成 WP-004、WP-005，决定 terminal fate 并对 admin-enabled 流程做 smoke。

### CAP-007 部署验证与运维文档

- **Baseline maturity:** M4 — Implemented
- **Critical path maturity:** M4 — Implemented
- **Why these levels:** 本地 build/run、线上 smoke、runtime SHA 回读、502 排障都有脚本或文档承接。[scripts/build.sh:1-4] [scripts/run-demo.sh:1-18] [scripts/hf-space-smoke.sh:160-177] [docs/ops-runbook.md:286-359]
- **Why not the next level:** 所有证据收集仍是人工动作，没有提交内自动化结果或发布流水线。关联 `BLK-004`。
- **Status tags:** specified;implemented;blocked
- **Sub-module variance:** 文档完整度高于执行证据密度。
- **Path to next level:** 先拿一条真实 evidence chain，再决定是否引入最小 CI。

## Coverage summary

| Maturity level | Capability count |
|---|---:|
| M0 — Idea | 0 |
| M1 — Scoped | 0 |
| M2 — Specified | 0 |
| M3 — Designed | 0 |
| M4 — Implemented | 7 |
| M5 — Runnable | 0 |
| M6 — Integrated | 0 |
| M7 — Tested | 0 |
| M8 — Pilotable | 0 |
| M9 — Deliverable | 0 |
