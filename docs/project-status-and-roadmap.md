# Project Status and Roadmap

本文档记录截至 2026-05-19 的当前实现状态、未完成事项和下一步开发计划。结论以当前 GitHub `main`、runtime 文件、脚本和 docs 为事实源；运行证据只在本仓库实际执行或从 Hugging Face runtime 回读后才标记为已验证。

## 当前定位

`dify-all-in-one` 是面向 Hugging Face Docker Space 的 Dify 单容器 Demo 工程，不是生产部署方案。当前实现已经覆盖核心 demo 目标：

- 单容器多进程：`supervisord` 管理 Dify Web、API、Worker、Beat、Plugin Daemon、Sandbox、PostgreSQL、Redis、ops-service、admin-service、web-terminal placeholder 和 Nginx。
- 单公开端口：Nginx 固定监听 `7860`，与 Hugging Face `app_port: 7860`、`Dockerfile EXPOSE 7860` 保持一致。
- Demo 存储边界：程序继续访问 `/data`，bucket-lite 模式把核心状态映射到 `/persist`，scratch/log/cache/run 默认放到 `/tmp/dify-aio`。
- 运维边界：`/_ops` 保持只读诊断面；`/_admin` 是默认关闭的独立管理面，写 action 保持白名单、独立 token、CSRF、confirm 和审计边界。
- Hugging Face iframe 兼容：Nginx 隐藏上游 `X-Frame-Options`，并统一返回允许 Hugging Face 嵌入的 `Content-Security-Policy frame-ancestors`。

## 本次静态审计结论

当前仓库没有 package manager、单元测试框架或 CI workflow。可直接运行、无需额外安装第三方程序的验证面是：

```bash
scripts/static-check.sh
```

该脚本聚合以下轻量检查：

- 所有 runtime/helper shell 脚本 `bash -n`。
- `docker/ops_service.py` 和 `docker/admin_service.py` 的 Python 语法检查。
- `git diff --check` whitespace 检查。
- changed/untracked 文件的 trailing whitespace 检查。

Docker build、local container smoke 和 Hugging Face live smoke 仍是最终运行证据，但它们依赖 Docker daemon、网络、HF CLI 登录态和 live Space 状态，不应被包装成每次小改动的默认本地门禁。

## 未完成事项

| Priority | Item | Current state | Next evidence needed |
| --- | --- | --- | --- |
| P0 | 本地 build/run/smoke 证据 | 静态检查可跑；完整 Docker build/run 未在本次静态审计阶段作为默认动作执行 | `scripts/build.sh`、`scripts/run-demo.sh`、`OPS_TOKEN=dify_ops_demo_token scripts/hf-space-smoke.sh http://localhost:8080` |
| P0 | Hugging Face runtime 回读 | 文档和脚本已覆盖流程；是否接管最新 commit 必须 live 回读 | `hf spaces info BlueSkyXN/dify-all-in-one` 中 `runtime.stage=RUNNING` 且 `runtime.raw.sha=<expected sha>` |
| P1 | Admin/File Manager 场景验证 | 代码和 docs 已实现默认关闭、token、CSRF、白名单 action、file root 限制 | admin disabled/enabled smoke、file manager read/write/protected path smoke |
| P1 | bucket-lite 持久化演练 | 代码支持 `/persist`、PostgreSQL fallback 和 dump restore；仍需要场景实测 | 独立 volume 或 live Space 上的 PGDATA、fallback、dump restore 记录 |
| P1 | 发布证据留存 | 目前依赖人工 runbook，不绑定 commit 自动归档 | 最小 CI 或 release checklist，记录 static check、build/smoke、runtime SHA |
| P2 | Web terminal 决策 | 当前只有 disabled/503 placeholder；没有安装 `ttyd` | owner 明确保持 placeholder，或单独设计 terminal binary、auth、audit、WebSocket smoke |
| P2 | `/_ops` 增强 | 当前诊断面已覆盖 health/status/system/config/logs/errors/metrics | 增加版本漂移提示、日志过滤、Plugin Daemon schema 只读检查或 warmup 状态 |

## 下一步开发计划

1. P0 先补运行证据：先跑 `scripts/static-check.sh`，再在具备 Docker daemon 的环境跑 build/run/local smoke；如果要验证线上，先确认 GitHub 与 Hugging Face remote 分叉关系，再回读 Space runtime SHA。
2. P1 扩展 smoke 覆盖 admin/file manager：保持无额外依赖，用 shell + curl 先覆盖默认关闭、token 鉴权、action catalog、CSRF、protected path 和 root escape。
3. P1 做 bucket-lite 演练：使用新的临时 Docker volume 或独立测试 Space，避免破坏现有 demo 数据；记录每组 env、commit SHA、日志关键行、`/_ops/health` 和 `/_ops/errors`。
4. P1 建立发布证据模板：不急于引入复杂 CI，先把 static/build/smoke/runtime SHA 的输出格式固定，保证每次 PR 或发布可以复核。
5. P2 再决定 Web terminal 和 `/_ops` 增强：除非 owner 明确需要真实 terminal，否则继续把它定义为 placeholder，避免把高风险能力误写成已交付。

## 本次实施审查循环

| Loop | Finding | Fix | Verification |
| --- | --- | --- | --- |
| 1 | `space-frame-headers` smoke 没有重试，冷启动短暂 502 会被误判为 header 回归 | 为 header 检查补齐 `SMOKE_RETRIES` / `SMOKE_DELAY` 重试逻辑 | Python stdlib stub server 模拟 `/apps` 首次 503 后恢复 200；`scripts/static-check.sh` |
| 2 | 新增验证入口和 roadmap 后，根 README、AGENTS 和项目目录图需要同步 | 增加 `scripts/static-check.sh` 作为单一轻量验证入口，并同步 README、AGENTS、docs index 和 file reference | `scripts/static-check.sh` |
| 3 | 项目状态和 roadmap 需要受版本控制；新增文件在未 staged 时也需要 whitespace 覆盖 | 新增本文档，并让 `scripts/static-check.sh` 额外扫描 changed/untracked 文件的 trailing whitespace | `scripts/static-check.sh` |
