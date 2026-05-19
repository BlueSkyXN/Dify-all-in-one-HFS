# 阻塞项列表

## Active blockers

| ID | Title | Type | Capability impacted | Severity | Status | Blocks e2e? |
|---|---|---|---|---|---|---|
| BLK-001 | `/_admin/terminal/` 只有 placeholder，没有真实终端 | dependency | CAP-006 | major | open | no |
| BLK-002 | 仓库缺少提交内自动化测试与运行证据 | test | CAP-001, CAP-002, CAP-003, CAP-005, CAP-006, CAP-007 | major | open | partial |
| BLK-003 | runtime 默认值、AGENTS 与 docs 对 Marketplace/Admin 合同存在漂移 | spec | CAP-003, CAP-006, CAP-007 | major | investigating | no |
| BLK-004 | 发布流程依赖人工 `git push` / `hf spaces info` / smoke，没有内建 CI 证据链 | deployment | CAP-001, CAP-007 | major | open | partial |

## Detail

### BLK-001: `/_admin/terminal/` 只有 placeholder，没有真实终端

- **Type:** dependency
- **Symptom:** `WEBSSH_ENABLED=false` 时返回 404 placeholder；即便显式设置 `WEBSSH_ENABLED=true`，缺少 `ttyd` 时仍只返回 503 placeholder。
- **Hypothesis (root cause):** 仓库先把 terminal 路由和 auth path 接好，但故意不把交互终端二进制打进镜像，以避免过早交付高风险能力。
- **Attempted fixes:** 当前仓库内没有看到安装 `ttyd` 的实现；只有 `docker/webssh_entrypoint.sh` 的 placeholder 逻辑。
- **Current evidence:** `docker/webssh_entrypoint.sh:47-60`, `Dockerfile:80-108`, `docs/configuration.md:400-410`
- **Next step:** 明确选择“补装并 pin `ttyd` + 补审计文档”或“将 terminal 从 active contract 中降级为未来能力”。
- **Blocks end-to-end delivery?:** no
- **First seen:** 2026-05-19
- **Owner / asker:** `[UNKNOWN]` owner 未在仓库中显式记录

### BLK-002: 仓库缺少提交内自动化测试与运行证据

- **Type:** test
- **Symptom:** `docs/development.md` 明确说明当前仓库没有单元测试框架，主要依赖 shell/Python 静态检查和 Docker/HF smoke；仓库文件列表中也没有 `tests/`、CI workflow 或持久化的执行结果。
- **Hypothesis (root cause):** 仓库目标偏 demo bundle，优先写 build/runbook，再把验证留给人工 Docker/HF smoke。
- **Attempted fixes:** 已存在 `scripts/hf-space-smoke.sh` 和 `python3 -m py_compile`/`bash -n` 文档，但都不是版本控制内的执行证据。
- **Current evidence:** `docs/development.md:27-54`, `docs/development.md:228-266`, `scripts/hf-space-smoke.sh:160-177`, `git ls-files`
- **Next step:** 至少补一条可保存的自动化验证路径，哪怕只是本地 Docker smoke 或 HF smoke 结果归档。
- **Blocks end-to-end delivery?:** partial
- **First seen:** 2026-05-19
- **Owner / asker:** `[UNKNOWN]`

### BLK-003: runtime 默认值、AGENTS 与 docs 对 Marketplace/Admin 合同存在漂移

- **Type:** spec
- **Symptom:** `AGENTS.md` 和 `docs/project-overview.md` 把 Marketplace 叙述成默认关闭，但 runtime 和 README 把 `MARKETPLACE_ENABLED` 设为 `true`；同时 admin/terminal 已进入代码合同，部分高层材料仍带有旧边界表述。
- **Hypothesis (root cause):** 目标从“保守的只读 demo 包”逐步转向“demo-first + 受控 admin”，但高层说明没有完全跟随代码演化更新。
- **Attempted fixes:** 代码层已把 `/_ops` 与 `/_admin` 分离，文档层也加入 admin 说明，但对 Marketplace 与 terminal 的高层叙述仍不完全一致。
- **Current evidence:** `AGENTS.md:82-84`, `README.md:51-52`, `docker/dify.env.runtime:209`, `docs/project-overview.md:31-33`, `docs/configuration.md:237-239`
- **Next step:** owner 确认“demo 默认值”后，对齐 README、docs、AGENTS 与 smoke 口径。
- **Blocks end-to-end delivery?:** no
- **First seen:** 2026-05-19
- **Owner / asker:** project owner

### BLK-004: 发布流程依赖人工 `git push` / `hf spaces info` / smoke，没有内建 CI 证据链

- **Type:** deployment
- **Symptom:** 发布说明要求人工 push 到 Space，再用 `hf spaces info`、`hf spaces logs` 和 smoke 手动回读 `runtime.raw.sha`；仓库内没有 `.github/workflows/` 或其他自动回收证据的流水线。
- **Hypothesis (root cause):** 仓库体量小，当前把“手工发布 + CLI 回读”当成足够的操作模型。
- **Attempted fixes:** 当前已有完整 runbook，但没有机器化地把这些结果绑定到 commit。
- **Current evidence:** `docs/deployment.md:41-119`, `docs/ops-runbook.md:286-315`, `git ls-files`
- **Next step:** 决定是否接受纯人工流程；若不接受，则补最小自动化来记录 build/smoke/runtime SHA。
- **Blocks end-to-end delivery?:** partial
- **First seen:** 2026-05-19
- **Owner / asker:** project owner

## Recently closed blockers

| ID | Title | Closed on | Resolution evidence |
|---|---|---|---|
| — | 当前 research run 未发现受版本控制的已关闭 blocker 历史 | — | — |
