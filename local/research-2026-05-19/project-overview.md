# 项目概览

## 一句话定位

`dify-all-in-one` 是一个面向 Hugging Face Docker Space 的 Dify 单容器 demo/deployment bundle，用单一 Docker image 和单一公网端口把 Dify 运行、持久化、诊断和受控管理收敛到一个可演示、可排障的最小工程中。[README.md:14-16] [README.md:32-44]

## 明确目标

| 目标 | 来源 |
|---|---|
| 在 Hugging Face Docker Space 中以 `sdk: docker` 方式部署 Dify | `README.md:55-84` |
| 用单一外部端口 `7860` 暴露 Web/API/Plugin/Ops/Admin 路由 | `README.md:32-44`, `docker/nginx.conf:46-157` |
| 保持该工程是 demo/课程/PoC 方案，而不是生产部署方案 | `README.md:14-16`, `AGENTS.md:5-7` |
| 用 bucket-lite 持久化布局把核心状态映射到 `/persist`，同时保持应用内部仍访问 `/data` | `README.md:161-178`, `docker/entrypoint.sh:171-211` |
| 保持 `/_ops` 只读，并把写操作隔离到默认关闭的 `/_admin` | `README.md:181-189`, `README.md:228-230`, `docker/ops_service.py:1241-1269`, `docker/admin_service.py:1068-1169` |

## 隐含目标（推断）

| 目标 | 推断来源 | 置信度 |
|---|---|---|
| `[INFERRED]` 尽量复用官方上游镜像资产，而不是在仓库内长期维护 Dify 源码 fork | `Dockerfile:27-49`, `Dockerfile:121-139` | 高 |
| `[INFERRED]` 适配 Hugging Face rootless 运行约束是设计中心之一 | `Dockerfile:110-115`, `README.md:52-53`, `docker/with-sandbox-env:28-32` | 高 |
| `[INFERRED]` 诊断面和管理面必须严格分层，避免把 `/_ops` 演化成任意写操作入口 | `local/ops-admin-plan.md:1-24`, `docker/ops_service.py:1241-1269`, `docker/admin_service.py:247-347` | 中高 |
| `[INFERRED]` 本仓库把“脚本化验证”视为主要验证手段，而不是语言级测试框架 | `scripts/build.sh:1-4`, `scripts/run-demo.sh:1-18`, `scripts/hf-space-smoke.sh:160-177`, `docs/development.md:27-54` | 高 |

## 当前状态

当前仓库已经具备完整的 Docker build 入口、rootless runtime bootstrap、PostgreSQL/Redis/Plugin/Sandbox 编排、Nginx 单端口路由、`/_ops` 只读诊断、默认关闭的 `/_admin` 管理面、以及本地/HF smoke 文档和脚本，因此核心能力整体处于 `specified` + `implemented` 状态；但仓库内没有随版本提交的 Docker build 结果、自动化测试结果或 live Space 回读证据，保守基线成熟度仍以 M4 为主。`/_admin/terminal/` 目前只是 placeholder 路由，Marketplace 默认值与部分文档/AGENTS 叙述存在漂移，这两点是当前研究包里最需要收口的边界。[Dockerfile:141-195] [docker/admin_service.py:1025-1169] [docker/webssh_entrypoint.sh:47-60] [docs/development.md:261-266]

## 本次研究不覆盖

- 完成 Docker build、本地容器启动或 live Hugging Face Space 验证
- 生产级高可用、备份演练、监控告警、访问控制与审计体系设计
- 对 Dify 上游业务功能本身做 PRD、功能验收或完成度评分
- 资源估算、排期、owner 分配、成本分解

## 需要项目 owner 确认的问题

- `MARKETPLACE_ENABLED` 的默认值到底应当是 demo-first 的 `true`，还是 AGENTS/部分文档所说的默认关闭
- `/_admin/terminal/` 是保留为未来能力、补装 `ttyd` 真正交付，还是从公开合同中移除
- 当前“手工 `git push` + `hf spaces info` + smoke”是否就是可接受的发布流程，还是需要最小 CI/CD 收口
- `ADMIN_FILES_WRITE_ENABLED` 是否预期只在本地/Private Space 调试时开启，还是未来会进入正式演示流程
