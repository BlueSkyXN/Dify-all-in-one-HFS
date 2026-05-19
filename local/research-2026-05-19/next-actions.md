# 下一步动作

## Short-term loop-closing

| # | Action | Reason | Links |
|---|---|---|---|
| 1 | 先对齐 `MARKETPLACE_ENABLED`、`/_admin`、terminal 的高层合同表述 | 这是当前最明显的事实漂移，继续规划会放大误判 | WP-001, BLK-003 |
| 2 | 产出一组真实 build/run/smoke/runtime SHA 证据 | 这是把多个能力从“只有代码”推向“可运行”的最短路径 | WP-002, BLK-004 |
| 3 | 给 `/_ops` 和 `/_admin` 的关键 endpoint 补最小自动回归 | 不解决它，所有成熟度都会停在 M4 | WP-003, BLK-002 |
| 4 | 对 terminal 做 yes/no 决策，不再长期维持“文档出现但能力未交付”的灰区 | 这是当前 admin 面最集中的不确定性 | WP-005, BLK-001 |

## Mid-term build

| # | Action | Capability served | Links |
|---|---|---|---|
| 1 | 建立版本升级 checklist，覆盖 Dify/Plugin/Sandbox/Node/uv | CAP-001, CAP-004 | WP-006 |
| 2 | 把 `ops-service` 提炼成可迁移诊断合同示例 | CAP-005 | WP-007 |
| 3 | 为 plugin install 和 sandbox code execution 增加专项 smoke | CAP-004 | WP-003, WP-006 |

## Long-term optimization

- 若项目要长期维护，考虑把“发布证据收集”自动化到最小 CI，而不是只留在人肉 runbook。
- 若 admin 面会持续扩大，应该把 action catalog、风险级别和审计字段抽成独立设计文档。
- 若 bucket-lite 继续作为核心卖点，值得补一套 `/persist` 失败模式演练与恢复脚本样例。

## Needs human / owner confirmation

| # | Question | What is `[UNKNOWN]` or `[INFERRED]` | Suggested decision owner |
|---|---|---|---|
| 1 | Marketplace 默认值到底应该是什么 | AGENTS/docs 与 runtime 默认值冲突 | project owner |
| 2 | `/_admin/terminal/` 要不要真实交付 | 当前只有 placeholder/optional ttyd contract | project owner + security |
| 3 | 是否接受纯手工发布与回读流程 | 仓库未内建 CI 证据链 | project owner |
| 4 | admin file write 是否会进入正式演示流 | 当前只看出默认关闭和局部保护规则 | project owner + ops |

## Reporting hooks

- **For PRD work:** 从 `project-overview.md` + `capability-map.md` + 本文件开始。
- **For functional spec:** 先看 `function-spec-cards/` 和 `evidence-map.md`。
- **For task planning:** 先看 `work-breakdown.md` + `blocker-list.md`。
- **For progress report:** 先补运行证据，再基于 `tracking-matrix.md` 生成，不要直接把本研究包写成完成度汇报。
