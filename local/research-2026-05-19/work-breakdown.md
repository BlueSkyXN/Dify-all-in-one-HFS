# 工作分解（WBS）

本 WBS 面向管理和跟踪，不做排期、成本或资源估算。

## Work packages

| ID | Work package | Linked capability | Linked function points | Maturity transition | Tracking status | Management unit | Depends on | Blocked by |
|---|---|---|---|---|---|---|---|---|
| WP-001 | 收口 runtime/docs/AGENTS 合同漂移 | CAP-003, CAP-006, CAP-007 | FP-011, FP-020, FP-024 | M2 -> M4 | in-progress | yes | — | BLK-003 |
| WP-002 | 产出可复现的 Docker + live smoke 证据链 | CAP-001, CAP-002, CAP-003, CAP-007 | FP-001, FP-005, FP-011, FP-024 | M4 -> M5 | not-started | yes | WP-001 | BLK-004 |
| WP-003 | 给 public/ops/admin 路径补自动化验证基线 | CAP-005, CAP-006, CAP-007 | FP-016, FP-017, FP-018, FP-019, FP-020, FP-021, FP-022, FP-024 | M4 -> M7 | not-started | yes | WP-002 | BLK-002 |
| WP-004 | 固化 admin surface 的产品边界与 file-write 策略 | CAP-006 | FP-020, FP-021, FP-022 | M4 -> M5 | in-progress | yes | WP-001 | BLK-003 |
| WP-005 | 决定 terminal 是真实能力还是占位能力 | CAP-006 | FP-023 | M3 -> M4 | blocked | yes | WP-004 | BLK-001 |
| WP-006 | 形成版本升级与上游兼容性回归流程 | CAP-001, CAP-004 | FP-001, FP-002, FP-014, FP-015 | M2 -> M4 | not-started | yes | WP-002 | — |
| WP-007 | 将 `ops-service` 抽象成可迁移的诊断合同 | CAP-005 | FP-016, FP-017, FP-018, FP-019 | M3 -> M4 | not-started | split-needed | WP-003 | — |

## Package detail

### WP-001: 收口 runtime/docs/AGENTS 合同漂移

- **Capability served:** CAP-003 进程编排与单端口请求路由；CAP-006 受控管理与文件边界；CAP-007 部署验证与运维文档
- **Function points served:** FP-011, FP-020, FP-024
- **Maturity transition:** M2 → M4
- **Tracking status:** in-progress
- **Management unit:** yes
- **Scope:** 对齐 `MARKETPLACE_ENABLED` 默认值、`/_admin` 当前合同、`NGINX_PORT`/`NGINX_CLIENT_MAX_BODY_SIZE` 的静态事实，以及 AGENTS 与 docs 的差异来源。只收口事实，不扩展新功能。
- **Definition of done:** `README.md`、`docs/project-overview.md`、`docs/configuration.md`、`AGENTS.md` 对相同运行时事实给出一致表述。
- **Evidence needed at completion:** 对齐后的 diff + path-limited 文档校验。
- **Dependencies:** —
- **Open blockers:** BLK-003

### WP-002: 产出可复现的 Docker + live smoke 证据链

- **Capability served:** CAP-001, CAP-002, CAP-003, CAP-007
- **Function points served:** FP-001, FP-005, FP-011, FP-024
- **Maturity transition:** M4 → M5
- **Tracking status:** not-started
- **Management unit:** yes
- **Scope:** 在本地 Docker 或 HF Space 上至少拿到一组可保存的 build、run、smoke、runtime SHA 回读证据。该包不追求 CI，只追求研究包可引用的运行证据。
- **Definition of done:** 存在一组与 commit 绑定的 build/smoke 记录，且 `runtime.raw.sha` 与目标 commit 一致。
- **Evidence needed at completion:** build log、`scripts/hf-space-smoke.sh` 输出摘要、`hf spaces info` 关键字段。
- **Dependencies:** WP-001
- **Open blockers:** BLK-004

### WP-003: 给 public/ops/admin 路径补自动化验证基线

- **Capability served:** CAP-005, CAP-006, CAP-007
- **Function points served:** FP-016, FP-017, FP-018, FP-019, FP-020, FP-021, FP-022, FP-024
- **Maturity transition:** M4 → M7
- **Tracking status:** not-started
- **Management unit:** yes
- **Scope:** 补最小自动化回归，至少覆盖 `/_ops` 健康、日志、错误摘要，`/_admin` 默认关闭/开启后关键 endpoint，以及 iframe header contract。
- **Definition of done:** 有可重复执行的自动化检查，能在 contract 破坏时直接失败。
- **Evidence needed at completion:** 测试脚本或 CI 记录，不只是文档命令。
- **Dependencies:** WP-002
- **Open blockers:** BLK-002

### WP-004: 固化 admin surface 的产品边界与 file-write 策略

- **Capability served:** CAP-006 受控管理与文件边界
- **Function points served:** FP-020, FP-021, FP-022
- **Maturity transition:** M4 → M5
- **Tracking status:** in-progress
- **Management unit:** yes
- **Scope:** 明确 `ADMIN_ENABLED` 的推荐场景、`ADMIN_FILES_WRITE_ENABLED` 的允许场景、protected path 的范围，以及 CLI/browser 两套 auth 体验。
- **Definition of done:** admin 相关 docs、默认值和 smoke 预期一致；operator 能明确知道哪些能力是 demo 默认关闭的。
- **Evidence needed at completion:** 文档对齐 + admin-enabled smoke 记录。
- **Dependencies:** WP-001
- **Open blockers:** BLK-003

### WP-005: 决定 terminal 是真实能力还是占位能力

- **Capability served:** CAP-006 受控管理与文件边界
- **Function points served:** FP-023
- **Maturity transition:** M3 → M4
- **Tracking status:** blocked
- **Management unit:** yes
- **Scope:** 只做一个决策并落实其后果：要么安装并 pin `ttyd`、补安全/审计说明；要么从对外合同里降级为“未交付”。
- **Definition of done:** `/_admin/terminal/` 的文档、镜像内容和 smoke 预期一致。
- **Evidence needed at completion:** 真实终端 smoke 或删除/降级后的 contract diff。
- **Dependencies:** WP-004
- **Open blockers:** BLK-001

### WP-006: 形成版本升级与上游兼容性回归流程

- **Capability served:** CAP-001 镜像组装与官方资产复用；CAP-004 Plugin 与 Sandbox 适配
- **Function points served:** FP-001, FP-002, FP-014, FP-015
- **Maturity transition:** M2 → M4
- **Tracking status:** not-started
- **Management unit:** yes
- **Scope:** 围绕 `DIFY_VERSION`、Plugin Daemon、Sandbox、Node、uv 建立升级前后需要验证的固定清单。
- **Definition of done:** 任意一次升级都有同一套前置检查、构建验证和 smoke 验证。
- **Evidence needed at completion:** 升级 checklist 文档 + 至少一次升级样本。
- **Dependencies:** WP-002
- **Open blockers:** —

### WP-007: 将 `ops-service` 抽象成可迁移的诊断合同

- **Capability served:** CAP-005 只读运维诊断
- **Function points served:** FP-016, FP-017, FP-018, FP-019
- **Maturity transition:** M3 → M4
- **Tracking status:** not-started
- **Management unit:** split-needed
- **Scope:** 抽取面向非 Dify 项目的最小迁移清单和 probe preset；不在本包里真正拆仓或发布新组件。
- **Definition of done:** 文档能说明如何关闭 Dify 默认探针并注入其他程序的 probe/log mapping。
- **Evidence needed at completion:** 一个非 Dify 场景的示例配置。
- **Dependencies:** WP-003
- **Open blockers:** —

## Drill-down to task cards (deep tier)

### WP-002 task cards

| Task ID | Task | Owner role | Acceptance signal |
|---|---|---|---|
| WP-002-T1 | 在本地或 HF 上完成一次 build 并保存关键日志摘要 | ops | 有可引用的 build 证据 |
| WP-002-T2 | 对目标 URL 跑 `scripts/hf-space-smoke.sh` 并记录失败/成功项 | ops | smoke 结果可映射到 FP-001/FP-005/FP-011/FP-024 |
| WP-002-T3 | 用 `hf spaces info` 回读 `runtime.stage` 与 `runtime.raw.sha` | ops | 目标 commit 与运行镜像一致 |

### WP-004 task cards

| Task ID | Task | Owner role | Acceptance signal |
|---|---|---|---|
| WP-004-T1 | 明确 `ADMIN_ENABLED` 与 `ADMIN_FILES_*` 的推荐矩阵 | product/ops | 文档和默认值没有歧义 |
| WP-004-T2 | 审核 protected path 规则是否覆盖所有 demo secrets | security/ops | `generated.env`、key、token 类路径都被拦截 |
| WP-004-T3 | 补一组 admin-enabled smoke 场景 | ops | 至少覆盖 `status`、`actions`、`files/list` |

### WP-005 task cards

| Task ID | Task | Owner role | Acceptance signal |
|---|---|---|---|
| WP-005-T1 | 评估在镜像中加入 `ttyd` 的依赖、审计和 rootless 风险 | ops/security | 有一份 yes/no 决策记录 |
| WP-005-T2 | 若不交付 terminal，则更新 docs/smoke 使其退回非合同能力 | docs/ops | 文档不再暗示“可立即使用” |

## 本 WBS 不覆盖

- 全项目任务级拆解和跨包依赖图
- 排期、人员、owner 正式分配
- 成本、工时、容量估算
- 详细测试计划生成
