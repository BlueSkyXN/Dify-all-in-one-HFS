# 跟踪矩阵

这是 capability / product / work / evidence 的管理入口。行保持短小，用于跳转，不替代源文档。

## Tracking matrix

| Tracking ID | Capability domain | Function point / work package | Spec candidate | Product module | Work package | Evidence | Status tags | Maturity | Blocker | Next action |
|---|---|---|---|---|---|---|---|---|---|---|
| TRK-001 | CAP-001 | FP-001 复用官方 Dify 资产 | SPEC-001 | PBS-001 | WP-002 | EVD-001 | specified, implemented | M4 | BLK-004 | 补 build + smoke 证据 |
| TRK-002 | CAP-001 | FP-002 runtime deps/rootless user | SPEC-001 | PBS-001 | WP-006 | EVD-002 | specified, implemented | M4 | — | 建立升级检查清单 |
| TRK-003 | CAP-001 | FP-003 entrypoint + healthcheck contract | SPEC-001 | PBS-001 | WP-002 | EVD-003 | specified, implemented | M4 | BLK-004 | 对应 commit 保存构建结果 |
| TRK-004 | CAP-002 | FP-004 generated secrets 与 URL/env precedence | — | PBS-002 | WP-002 | EVD-004 | specified, implemented | M4 | — | 记录运行态回读 |
| TRK-005 | CAP-002 | FP-005 bucket-lite `/data` -> `/persist` 映射 | — | PBS-002 | WP-002 | EVD-005 | specified, implemented | M4 | BLK-004 | 验证 bucket 模式首启 |
| TRK-006 | CAP-002 | FP-006 PostgreSQL init + vector | — | PBS-002 | WP-002 | EVD-006 | specified, implemented | M4 | — | 保存 init/migration 日志 |
| TRK-007 | CAP-002 | FP-007 PGDATA fallback + restore | SPEC-002 | PBS-002 | WP-002 | EVD-007 | specified, implemented, blocked | M4 | BLK-004 | 明确 fallback 是否可接受 |
| TRK-008 | CAP-002 | FP-008 Redis/Sandbox config + Dify migration | — | PBS-002 | WP-002 | EVD-008 | specified, implemented | M4 | BLK-002 | 增加 migration smoke |
| TRK-009 | CAP-003 | FP-009 supervisor process graph | — | PBS-003 | WP-002 | EVD-009 | specified, implemented | M4 | BLK-004 | 拿一组 supervisor 运行证据 |
| TRK-010 | CAP-003 | FP-010 `wait-for-core` dependency gating | — | PBS-003 | WP-002 | EVD-010 | specified, implemented | M4 | — | 运行态验证依赖顺序 |
| TRK-011 | CAP-003 | FP-011 单端口路由合同 | SPEC-003 | PBS-003 | WP-001 | EVD-011 | specified, implemented | M4 | BLK-003 | 对齐静态/动态端口叙述 |
| TRK-012 | CAP-003 | FP-012 WebSocket 和 hook headers | — | PBS-003 | WP-002 | EVD-012 | specified, implemented | M4 | — | 追加 websocket smoke |
| TRK-013 | CAP-003 | FP-013 HF iframe CSP override | — | PBS-003 | WP-002 | EVD-013 | specified, implemented | M4 | — | 保持 header smoke 常驻 |
| TRK-014 | CAP-004 | FP-014 plugin env mapping + migration | SPEC-004 | PBS-002 | WP-006 | EVD-014 | specified, implemented | M4 | BLK-002 | 增加 plugin 安装 smoke |
| TRK-015 | CAP-004 | FP-015 sandbox no-network + rootless prep | SPEC-004 | PBS-002 | WP-006 | EVD-015 | specified, implemented | M4 | BLK-002 | 增加 code execution smoke |
| TRK-016 | CAP-005 | FP-016 `/healthz` / `/_ops/health` 聚合 | SPEC-005 | PBS-004 | WP-003 | EVD-016 | specified, implemented | M4 | BLK-002 | 自动化校验 probe contract |
| TRK-017 | CAP-005 | FP-017 dashboard/system/config/version/metrics | SPEC-005 | PBS-004 | WP-003 | EVD-017 | specified, implemented, operable | M4 | BLK-002 | 保存运行态 JSON 样本 |
| TRK-018 | CAP-005 | FP-018 `/_ops/logs` 白名单 | SPEC-005 | PBS-004 | WP-003 | EVD-018 | specified, implemented | M4 | BLK-002 | 校验扩展 whitelist 行为 |
| TRK-019 | CAP-005 | FP-019 `/_ops/errors` 模式聚合 | SPEC-005 | PBS-004 | WP-003 | EVD-019 | specified, implemented | M4 | BLK-002 | 准备失败样本回归 |
| TRK-020 | CAP-006 | FP-020 admin auth + CSRF gating | — | PBS-004 | WP-004 | EVD-020 | specified, implemented, changed | M4 | BLK-003 | 对齐 admin-enabled 合同 |
| TRK-021 | CAP-006 | FP-021 白名单动作 + audit log | — | PBS-004 | WP-004 | EVD-021 | specified, implemented | M4 | BLK-002 | 增加 admin-enabled smoke |
| TRK-022 | CAP-006 | FP-022 文件根目录约束 | — | PBS-004 | WP-004 | EVD-022 | specified, implemented | M4 | BLK-003 | 明确 write 场景与 protected path |
| TRK-023 | CAP-006 | FP-023 terminal placeholder / optional ttyd | SPEC-006 | PBS-004 | WP-005 | EVD-023 | specified, implemented, blocked | M4 | BLK-001 | 选择交付或降级 |
| TRK-024 | CAP-007 | FP-024 build/run/smoke + runtime SHA 回读 | SPEC-007 | PBS-005 | WP-002 | EVD-024 | specified, implemented, blocked | M4 | BLK-004 | 固化发布证据链 |
| TRK-025 | CAP-003/CAP-006/CAP-007 | WP-001 收口合同漂移 | — | PBS-003, PBS-004, PBS-005 | WP-001 | EVD-025 | in-progress, blocked | M2->M4 | BLK-003 | 先做事实对齐 |
| TRK-026 | CAP-001/CAP-002/CAP-003/CAP-007 | WP-002 可复现 Docker + live smoke 证据链 | — | PBS-001, PBS-002, PBS-003, PBS-005 | WP-002 | EVD-026 | not-started, blocked | M4->M5 | BLK-004 | 收集 build/smoke/SHA |
| TRK-027 | CAP-005/CAP-006/CAP-007 | WP-003 自动化验证基线 | — | PBS-004, PBS-005 | WP-003 | EVD-027 | not-started, blocked | M4->M7 | BLK-002 | 增加自动回归 |
| TRK-028 | CAP-006 | WP-004 admin 边界固化 | — | PBS-004 | WP-004 | EVD-028 | in-progress, blocked | M4->M5 | BLK-003 | 决定 write 策略 |
| TRK-029 | CAP-006 | WP-005 terminal fate | — | PBS-004 | WP-005 | EVD-029 | blocked | M3->M4 | BLK-001 | 终端要么交付要么降级 |
| TRK-030 | CAP-001/CAP-004 | WP-006 版本升级回归流程 | — | PBS-001, PBS-002 | WP-006 | EVD-030 | not-started | M2->M4 | — | 固化升级 checklist |
| TRK-031 | CAP-005 | WP-007 ops-service 可迁移合同 | — | PBS-004 | WP-007 | EVD-031 | not-started | M3->M4 | — | 抽出 non-Dify 示例 |

## Status legend

- `specified`: 代码或文档已经给出行为合同
- `implemented`: 受版本控制实现存在
- `operable`: 具有健康、日志或 runbook 支撑
- `blocked`: 被 blocker 卡住，不能自然推进到下一成熟度
- `changed`: 能力目标在本轮材料中出现了明显演化

## Reporting hooks

| Report question | Rows to inspect | Notes |
|---|---|---|
| 当前工程都有哪些能力 | TRK-001 到 TRK-024 | 结合 `capability-map.md` |
| 哪些点最影响后续交付 | TRK-025 到 TRK-031 | 结合 `work-breakdown.md` 和 `blocker-list.md` |
| 哪些事实还没有运行证据 | 所有 baseline=M4 且 blocker 指向 BLK-002/004 的行 | 先补证据，再做完成度判断 |
