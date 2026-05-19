# 证据地图

## Function-point evidence

| Function point | Code path | Evidence type | Evidence strength | Confidence | Notes |
|---|---|---|---|---|---|
| FP-001 | `Dockerfile:27-49`, `Dockerfile:121-139` | Docker build code | Code | 高 | 明确复用官方 Dify Web/API/Plugin/Sandbox 资产 |
| FP-004 | `docker/entrypoint.sh:35-74`, `docker/dify.env.runtime:34-58` | Bootstrap code | Code | 高 | secret 复用顺序和 URL 派生都在脚本内 |
| FP-005 | `docker/entrypoint.sh:112-141`, `docker/entrypoint.sh:171-211` | Bootstrap code | Code | 高 | bucket-lite 的切换条件和映射动作可直接追踪 |
| FP-007 | `docker/entrypoint.sh:499-555`, `docker/entrypoint.sh:580-601` | Bootstrap code | Code | 中高 | fallback 分支存在，但缺少运行态证据 |
| FP-011 | `docker/nginx.conf:46-157` | Route config | Code | 高 | 单端口公开路由合同全部在静态配置中 |
| FP-013 | `docker/nginx.conf:55-61`, `scripts/hf-space-smoke.sh:127-158` | Config + smoke logic | Code | 高 | 既有 header 写法，也有 smoke 断言逻辑 |
| FP-016 | `docker/ops_service.py:433-464` | Python service code | Code | 高 | 默认 probe 集合和 `/healthz` 语义清晰 |
| FP-017 | `docker/ops_service.py:481-493`, `docker/ops_service.py:608-693`, `docker/ops_service.py:805-1270` | Python service code | Code | 高 | config/system/version/metrics/dashboard 都可对应到实现 |
| FP-018 | `docker/ops_service.py:29-46`, `docker/ops_service.py:721-736` | Python service code | Code | 高 | service whitelist 和 tail 行数限制可追踪 |
| FP-019 | `docker/ops_service.py:106-120`, `docker/ops_service.py:748-802` | Python service code | Code | 高 | 错误 pattern 与 ignored pattern 均可追踪 |
| FP-020 | `docker/admin_service.py:95-152`, `docker/admin_service.py:954-1013` | Python service code | Code | 高 | `ADMIN_ENABLED`、header/cookie auth、CSRF 规则明确定义 |
| FP-021 | `docker/admin_service.py:247-347`, `docker/admin_service.py:1110-1115` | Python service code | Code | 高 | action catalog 与执行函数一一对应 |
| FP-022 | `docker/admin_service.py:350-412`, `docker/admin_service.py:446-587` | Python service code | Code | 高 | root confinement 与 protected path 规则明确定义 |
| FP-023 | `docker/webssh_entrypoint.sh:47-60`, `docker/nginx.conf:86-106` | Bash + route config | Code | 高 | 当前能力是 placeholder，不是实终端 |
| FP-024 | `scripts/build.sh:1-4`, `scripts/run-demo.sh:1-18`, `scripts/hf-space-smoke.sh:4-177`, `docs/deployment.md:27-119` | Shell + docs | Code / Doc | 中高 | 有完整脚本和 runbook，但未见版本控制内执行记录 |

## Coverage summary

| Capability domain | Function points total | With code evidence | With runnable evidence | With tested evidence |
|---|---:|---:|---:|---:|
| CAP-001 镜像组装与官方资产复用 | 3 | 3 | 0 | 0 |
| CAP-002 启动初始化与持久化编排 | 5 | 5 | 0 | 0 |
| CAP-003 进程编排与单端口请求路由 | 5 | 5 | 0 | 0 |
| CAP-004 Plugin 与 Sandbox 适配 | 2 | 2 | 0 | 0 |
| CAP-005 只读运维诊断 | 4 | 4 | 0 | 0 |
| CAP-006 受控管理与文件边界 | 4 | 4 | 0 | 0 |
| CAP-007 部署验证与运维文档 | 1 | 1 | 0 | 0 |

## Inferred entries

| Function point | Inferred from | What would promote it to evidenced |
|---|---|---|
| `[INFERRED]` “复用 `ops-service` 到其他单容器项目” | `docs/architecture.md:200-215`, `docs/configuration.md:327-339` | 看到至少一个非 Dify 工程的真实采纳样本 |
| `[INFERRED]` “admin surface 会继续扩大动作目录” | `local/ops-admin-plan.md:13-54` 与 `docker/admin_service.py:247-347` 的差异 | owner 或后续提交给出新的 action catalog |
