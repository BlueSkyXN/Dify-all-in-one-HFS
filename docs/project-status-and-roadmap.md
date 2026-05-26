# Project Status and Roadmap

本文档记录截至 2026-05-23 的当前实现状态、验证项和下一步开发计划。结论以当前 GitHub `main`、runtime 文件、脚本和 docs 为事实源；运行证据只在本仓库实际执行或从 Hugging Face runtime 回读后才标记为已验证。

## 当前定位

`dify-all-in-one` 是面向 Hugging Face Docker Space 的 Dify 单容器 Demo 工程，不是生产部署方案。当前实现已经覆盖核心 demo 目标：

- 单容器多进程：`supervisord` 管理 Dify Web、API、Worker、Beat、Plugin Daemon、Sandbox、PostgreSQL、Redis、ops-service、admin-service、默认关闭的 web-terminal 和 Nginx。
- 单公开端口：Nginx 固定监听 `7860`，与 Hugging Face `app_port: 7860`、`Dockerfile EXPOSE 7860` 保持一致。
- Demo 存储边界：程序继续访问 `/data`，bucket-lite 模式把核心状态映射到 `/persist`，scratch/log/cache/run 默认放到 `/tmp/dify-aio`。
- 运维边界：`/_ops` 保持只读诊断面；`/_admin` 是默认关闭的独立管理面，写 action 保持白名单、独立 token、CSRF、confirm 和审计边界，并可只读查看最近 admin 审计事件。
- 管理体验：`/_ops/` 和 `/_admin/` dashboard 支持 English / 中文切换，默认跟随浏览器语言，并把选择保存在浏览器本地。
- Hugging Face iframe 兼容：Nginx 隐藏上游 `X-Frame-Options`，并统一返回允许 Hugging Face 嵌入的 `Content-Security-Policy frame-ancestors`。

## 验证口径

当前仓库没有 package manager 或单元测试框架。GitHub Actions 已提供最小 `Static Check` workflow，PR 和 `main` push 会运行：

```bash
scripts/static-check.sh
```

该脚本聚合以下轻量检查：

- 所有 runtime/helper shell 脚本 `bash -n`。
- `docker/ops_service.py` 和 `docker/admin_service.py` 的 Python 语法检查。
- `git diff --check` whitespace 检查。
- changed/untracked 文件的 trailing whitespace 检查。

Docker build、local container smoke 和 Hugging Face live smoke 仍是最终运行证据，但它们依赖 Docker daemon、网络、HF CLI 登录态和 live Space 状态，不应被包装成每次小改动的默认本地门禁。

## 发布证据口径

本文件不是自动更新的 release log，不应把下方历史快照当成任意新提交的运行证据。每次发布或推送 Hugging Face 后，都必须用目标 commit 重新回读 `hf spaces info`，并按实际 token/权限跑 smoke。

最近一次完整带 `OPS_TOKEN` 的线上 smoke 快照：

```text
Date: 2026-05-20
GitHub PR: #15
Merge SHA: d398057683de11335fdfe666678ededc36298828
origin/main: d398057683de11335fdfe666678ededc36298828
hf/main: d398057683de11335fdfe666678ededc36298828
HF runtime.stage: RUNNING
HF runtime.raw.sha: d398057683de11335fdfe666678ededc36298828
```

该快照覆盖 public health、iframe headers、`/_admin/` 默认关闭、`/_admin/terminal/` 默认关闭、setup/init API，以及带 Space `OPS_TOKEN` 的 `/_ops/health`、`/_ops/system`、`/_ops/metrics`、`/_ops/errors`。若后续是 docs-only 发布，仍要至少确认 GitHub/HF head、`runtime.stage`、`runtime.raw.sha` 和无需 token 的 public smoke；没有 `OPS_TOKEN` 时，不要声称 token-protected `/_ops/*` 已完成线上验证。

## 后续验证项

| Priority | Item | Current state | Next evidence needed |
| --- | --- | --- | --- |
| P0 | 本地 build/run/smoke 证据 | 静态检查可跑；完整 Docker build/run 未在本次文档审计阶段作为默认动作执行 | `scripts/build.sh`、`scripts/run-demo.sh`、`OPS_TOKEN=dify_ops_demo_token ALLOW_DEMO_OPS_TOKEN=true scripts/hf-space-smoke.sh http://localhost:8080` |
| P0 | Hugging Face runtime 回读 | 每个新发布都必须按目标 commit 单独验证；不要用历史 SHA 证明当前 head | `hf spaces info <space-id>` 中 `runtime.stage=RUNNING` 且 `runtime.raw.sha=<expected sha>` |
| P1 | Admin/File Manager 场景验证 | 默认关闭状态已在线上 smoke 覆盖；代码和 docs 已实现 token、CSRF、白名单 action、audit 只读查看、file root 限制 | admin enabled smoke、audit endpoint、file manager read/write/protected path smoke |
| P1 | bucket-lite 持久化演练 | 已有演练模板；代码支持 `/persist`、PostgreSQL fallback 和 dump restore；仍需要场景实测 | 独立 volume 或 live Space 上的 PGDATA、fallback、dump restore 记录 |
| P1 | 发布证据留存 | 已有最小 CI 和 release checklist；仍需要每次发布按模板记录结果 | 记录 static check、build/smoke、runtime SHA 和 skipped checks |
| P1 | Web terminal 启用验证 | 默认关闭状态已在线上 smoke 覆盖；已内置 `ttyd`，开启后通过 `/_admin/terminal/` 走 admin 鉴权 | `ADMIN_EXPECTED_ENABLED=true WEBSSH_EXPECTED_ENABLED=true ADMIN_TOKEN=<token> scripts/webssh-smoke.sh <base>` 和可选 live smoke |
| P2 | `/_ops` 增强 | 当前诊断面已覆盖 health/status/system/config/logs/errors/metrics；admin 审计查看已放在 `/_admin` | 增加版本漂移提示、日志过滤、Plugin Daemon schema 只读检查或 warmup 状态 |

## 下一步开发计划

1. P0 继续补本地运行证据：先跑 `scripts/static-check.sh`，再在具备 Docker daemon 的环境跑 build/run/local smoke；如果要验证线上，先确认 GitHub 与 Hugging Face remote 分叉关系，再回读 Space runtime SHA。
2. P1 扩展 smoke 覆盖 admin/file manager：保持无额外依赖，用 shell + curl 先覆盖默认关闭、token 鉴权、action catalog、audit endpoint、CSRF、protected path 和 root escape。
3. P1 按 bucket-lite 演练模板执行实测：使用新的临时 Docker volume 或独立测试 Space，避免破坏现有 demo 数据；记录每组 env、commit SHA、日志关键行、`/_ops/health` 和 `/_ops/errors`。
4. P1 持续使用发布证据模板：把 static/build/smoke/runtime SHA 的输出格式固定，保证每次 PR 或发布可以复核。
5. P2 继续增强 `/_ops`：增加版本漂移提示、日志过滤、Plugin Daemon schema 只读检查或 warmup 状态；Web terminal 只在 Private/Protected 环境按需启用。

## 本次实施审查循环

| Loop | Finding | Fix | Verification |
| --- | --- | --- | --- |
| 1 | `space-frame-headers` smoke 没有重试，冷启动短暂 502 会被误判为 header 回归 | 为 header 检查补齐 `SMOKE_RETRIES` / `SMOKE_DELAY` 重试逻辑 | Python stdlib stub server 模拟 `/apps` 首次 503 后恢复 200；`scripts/static-check.sh` |
| 2 | 新增验证入口和 roadmap 后，根 README、AGENTS 和项目目录图需要同步 | 增加 `scripts/static-check.sh` 作为单一轻量验证入口，并同步 README、AGENTS、docs index 和 file reference | `scripts/static-check.sh` |
| 3 | 项目状态和 roadmap 需要受版本控制；新增文件在未 staged 时也需要 whitespace 覆盖 | 新增本文档，并让 `scripts/static-check.sh` 额外扫描 changed/untracked 文件的 trailing whitespace | `scripts/static-check.sh` |
| 4 | live Space 已覆盖自定义 `OPS_TOKEN`，文档继续写死 demo token 会造成 401/503 误判 | 线上命令统一改为 `your-configured-ops-token` 或 `$OPS_TOKEN`，本地 demo 才保留 `dify_ops_demo_token` 和 `ALLOW_DEMO_OPS_TOKEN=true` | `rg -n "dify_ops_demo_token" README.md README.hf-space.md docs/*.md AGENTS.md` |
| 5 | ops/admin 已补中英双语 UI，AGENTS 和文件职责说明需要同步该维护约束 | 文档补充 English / 中文切换能力，AGENTS 增加双语文案同步规则 | `scripts/static-check.sh`；`git diff --check` |
