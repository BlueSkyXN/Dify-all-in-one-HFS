# 能力地图

## L0 项目目标

把 Dify 的多服务部署压缩成 Hugging Face Docker Space 可运行的单容器 demo bundle，并同时交付最小可用的持久化、诊断与受控管理边界。[README.md:14-16] [README.md:32-44]

## Capability Breakdown Structure (CBS)

### CAP-001 镜像组装与官方资产复用

**Purpose:** 让仓库能够在不 vendoring 上游 Dify 源码的前提下，产出一个包含 Web/API/Plugin/Sandbox/数据库/反代的单镜像。
**Status tags:** specified;implemented;blocked
**Maturity (M0-M9):** M4 — `Dockerfile` 已定义完整 build graph，但研究回合没有拿到版本控制内的构建产物或 CI 记录。[Dockerfile:17-22] [Dockerfile:27-49] [Dockerfile:80-108]

#### L2 — Capability modules
| Module | Path | Role |
|---|---|---|
| CAP-001-01 上游镜像 intake | `Dockerfile` | 引入官方 Dify Web/API/Plugin/Sandbox 资产 |
| CAP-001-02 runtime image assembly | `Dockerfile`, `scripts/build.sh` | 组装最终 runtime image 并提供本地构建入口 |

#### L3 — Function points
| ID | Function point | Path:line | Status tags |
|---|---|---|---|
| FP-001 | 复用官方 Dify Web/API/Plugin/Sandbox 镜像资产 | `Dockerfile:27-49`, `Dockerfile:121-139` | specified, implemented |
| FP-002 | 安装 runtime 依赖并创建 rootless `user` | `Dockerfile:80-115` | specified, implemented |
| FP-003 | 暴露单镜像 entrypoint 与 Docker healthcheck contract | `Dockerfile:141-155`, `Dockerfile:190-195` | specified, implemented |

#### L4 — Spec candidates
| Spec candidate ID | Function point | Actor / trigger | Input | Output | Acceptance signal | Open question |
|---|---|---|---|---|---|---|
| SPEC-001 | FP-001, FP-002, FP-003 | 维护者升级版本或重建镜像 | `DIFY_VERSION` / image args / Docker daemon | 可构建且可 smoke 的 image | build 记录 + `scripts/hf-space-smoke.sh` 成功 | 升级前后的兼容矩阵由谁维护 |

### CAP-002 启动初始化与持久化编排

**Purpose:** 让容器在 HF/rootless 约束下自举目录、secret、数据库、迁移和 bucket-lite 数据路径。
**Status tags:** specified;implemented;blocked
**Maturity (M0-M9):** M4 — 初始化和 fallback 逻辑都已编码，但缺少提交内的启动日志或回放证据来保守提升到 M5。[docker/entrypoint.sh:21-33] [docker/entrypoint.sh:171-211] [docker/entrypoint.sh:561-658]

#### L2 — Capability modules
| Module | Path | Role |
|---|---|---|
| CAP-002-01 env synthesis | `docker/dify.env.runtime`, `docker/entrypoint.sh` | 合成默认 env、`PUBLIC_URL` 和 generated secrets |
| CAP-002-02 persistence and DB bootstrap | `docker/entrypoint.sh`, `docker/postgres-backup-loop` | bucket-lite、PostgreSQL init、fallback、备份与恢复 |

#### L3 — Function points
| ID | Function point | Path:line | Status tags |
|---|---|---|---|
| FP-004 | 生成/复用 generated secrets 并保持外部 env 优先 | `docker/entrypoint.sh:35-74`, `docker/dify.env.runtime:34-58` | specified, implemented |
| FP-005 | 自动检测 `/persist` 并映射 `/data` 为 bucket-lite 布局 | `docker/entrypoint.sh:112-141`, `docker/entrypoint.sh:171-211` | specified, implemented |
| FP-006 | 校验 PostgreSQL identifiers 并初始化 role/database/vector | `docker/entrypoint.sh:76-83`, `docker/entrypoint.sh:561-630` | specified, implemented |
| FP-007 | bucket PGDATA 失败时回退到 runtime PGDATA 并尝试恢复 dump | `docker/entrypoint.sh:499-555`, `docker/entrypoint.sh:580-601` | specified, implemented, blocked |
| FP-008 | 渲染 Redis/Sandbox 配置并在长期运行前执行 Dify migration | `docker/entrypoint.sh:263-279`, `docker/entrypoint.sh:319-362`, `docker/entrypoint.sh:632-658` | specified, implemented |

#### L4 — Spec candidates
| Spec candidate ID | Function point | Actor / trigger | Input | Output | Acceptance signal | Open question |
|---|---|---|---|---|---|---|
| SPEC-002 | FP-007 | HF bucket 文件系统语义变化或首启失败 | `PERSIST_MODE`, `POSTGRES_BUCKET_FAILURE_MODE`, dump presence | 选择 `exit` 还是 fallback，并给出明确恢复路径 | 同一套错误能稳定导向预期分支 | owner 是否接受“静默回退到 `/tmp` 后服务继续运行” |

### CAP-003 进程编排与单端口请求路由

**Purpose:** 让所有 Dify 相关进程在单容器里有序启动，并通过 `7860` 对外形成稳定路径合同。
**Status tags:** specified;implemented;blocked
**Maturity (M0-M9):** M4 — `supervisord.conf`、`wait-for-core` 和 `nginx.conf` 已定义完整图谱，但缺少运行态证据确认所有路由都被实际验证。[docker/supervisord.conf:17-156] [docker/wait-for-core:16-49] [docker/nginx.conf:46-157]

#### L2 — Capability modules
| Module | Path | Role |
|---|---|---|
| CAP-003-01 process graph | `docker/supervisord.conf`, `docker/wait-for-core` | 启动顺序、依赖等待、日志归集 |
| CAP-003-02 request routing | `docker/nginx.conf`, `scripts/hf-space-smoke.sh` | 单端口 path routing、iframe/header、smoke validation |

#### L3 — Function points
| ID | Function point | Path:line | Status tags |
|---|---|---|---|
| FP-009 | 用 Supervisor 编排 Postgres/Redis/Plugin/API/Worker/Beat/Web/Ops/Admin/Nginx | `docker/supervisord.conf:17-156` | specified, implemented |
| FP-010 | 用 `wait-for-core` 在 service 启动前等待 `postgres` / `redis` / `api` | `docker/wait-for-core:16-49`, `docker/supervisord.conf:47-55` | specified, implemented |
| FP-011 | 通过 `7860` 代理 Web/API/Plugin/Ops/Admin/Trigger/Files 路径 | `docker/nginx.conf:46-157` | specified, implemented |
| FP-012 | 为 `/socket.io/` 和 `/e/` / `/_admin/terminal/` 保留关键 header | `docker/nginx.conf:86-106`, `docker/nginx.conf:138-149` | specified, implemented |
| FP-013 | 隐藏上游 `X-Frame-Options` 并下发 Hugging Face iframe 兼容 CSP | `docker/nginx.conf:55-61`, `scripts/hf-space-smoke.sh:127-158` | specified, implemented |

#### L4 — Spec candidates
| Spec candidate ID | Function point | Actor / trigger | Input | Output | Acceptance signal | Open question |
|---|---|---|---|---|---|---|
| SPEC-003 | FP-011 | 维护者希望让 `NGINX_PORT` / body size 动态生效 | env var + Nginx template | 一致的 runtime port/body-size contract | `README.md`, `Dockerfile`, `nginx.conf` 与 smoke 同步 | 是否值得引入模板渲染复杂度 |

### CAP-004 Plugin 与 Sandbox 适配

**Purpose:** 在不拆多容器的前提下，把 Plugin Daemon 和 Sandbox 接到 Dify API 的同一容器运行平面。
**Status tags:** specified;implemented;blocked
**Maturity (M0-M9):** M4 — wrapper、migration 和默认安全边界都已编码，但没有提交内的端到端插件/代码执行记录。[docker/with-plugin-env:14-64] [docker/with-sandbox-env:14-32] [docker/supervisord.conf:47-65]

#### L2 — Capability modules
| Module | Path | Role |
|---|---|---|
| CAP-004-01 plugin daemon adaptation | `docker/with-plugin-env`, `docker/supervisord.conf` | 变量映射、migration、plugin storage |
| CAP-004-02 sandbox adaptation | `docker/with-sandbox-env`, `docker/dify.env.runtime` | API key、网络开关、rootless 启动修正 |

#### L3 — Function points
| ID | Function point | Path:line | Status tags |
|---|---|---|---|
| FP-014 | 映射 repo env 到 plugin-daemon contract 并在启动前执行 migration | `docker/with-plugin-env:14-64`, `docker/supervisord.conf:47-55` | specified, implemented |
| FP-015 | 以默认 no-network 配置和 rootless 目录清理启动 Sandbox | `docker/with-sandbox-env:14-32`, `docker/dify.env.runtime:156-179` | specified, implemented |

#### L4 — Spec candidates
| Spec candidate ID | Function point | Actor / trigger | Input | Output | Acceptance signal | Open question |
|---|---|---|---|---|---|---|
| SPEC-004 | FP-014, FP-015 | 需要跨版本升级 Dify Plugin/Sandbox | version args + env defaults | 稳定的 upgrade checklist | migration 日志与 smoke 兼容 | 上游 image 版本漂移由谁回归验证 |

### CAP-005 只读运维诊断

**Purpose:** 让 operator 在不授予写权限的前提下，观察健康、进程、资源、日志和错误摘要。
**Status tags:** specified;implemented;operable;blocked
**Maturity (M0-M9):** M4 — `ops-service` 已具备完整 endpoint 和 dashboard，但缺少提交内的执行记录，仍不能把 capability 记为 M5。[docker/ops_service.py:433-464] [docker/ops_service.py:608-693] [docker/ops_service.py:1241-1269]

#### L2 — Capability modules
| Module | Path | Role |
|---|---|---|
| CAP-005-01 health and dashboard | `docker/ops_service.py` | 健康聚合、system/config/version/metrics、HTML dashboard |
| CAP-005-02 logs and error summary | `docker/ops_service.py`, `docs/ops-runbook.md` | 白名单日志 tail、pattern-based 错误摘要 |

#### L3 — Function points
| ID | Function point | Path:line | Status tags |
|---|---|---|---|
| FP-016 | 聚合 HTTP/TCP/command health 到 `/healthz` 和 `/_ops/health` | `docker/ops_service.py:433-464` | specified, implemented |
| FP-017 | 暴露 supervisor/system/config/version/metrics dashboard | `docker/ops_service.py:481-493`, `docker/ops_service.py:584-693`, `docker/ops_service.py:805-1270` | specified, implemented, operable |
| FP-018 | 用 service whitelist 暴露 `/_ops/logs` | `docker/ops_service.py:29-46`, `docker/ops_service.py:721-736` | specified, implemented |
| FP-019 | 聚合近期错误并过滤已知 benign startup pattern | `docker/ops_service.py:106-120`, `docker/ops_service.py:748-802` | specified, implemented |

#### L4 — Spec candidates
| Spec candidate ID | Function point | Actor / trigger | Input | Output | Acceptance signal | Open question |
|---|---|---|---|---|---|---|
| SPEC-005 | FP-016, FP-017, FP-018, FP-019 | 其他单容器项目要复用 `ops-service` | `OPS_DEFAULT_CHECKS_ENABLED`, `OPS_EXTRA_*`, `OPS_LOG_*` | 一个可迁移的 non-Dify 诊断合同 | 文档里有最小移植清单 + 至少一个实证样本 | 是否把 `ops-service` 抽成独立 bundle |

### CAP-006 受控管理与文件边界

**Purpose:** 在不污染 `/_ops` 的前提下，提供默认关闭、可审计、白名单化的受控管理能力。
**Status tags:** specified;implemented;blocked;changed
**Maturity (M0-M9):** M4 — `admin-service` 已实现登录、CSRF、action catalog、file manager 和 placeholder terminal；但 terminal 仍未交付真实交互能力，且未见自动化执行证据。[docker/admin_service.py:95-152] [docker/admin_service.py:247-347] [docker/admin_service.py:1025-1169] [docker/webssh_entrypoint.sh:47-60]

#### L2 — Capability modules
| Module | Path | Role |
|---|---|---|
| CAP-006-01 admin auth and actions | `docker/admin_service.py` | token/cookie/csrf gating，白名单 action，审计日志 |
| CAP-006-02 file and terminal boundary | `docker/admin_service.py`, `docker/webssh_entrypoint.sh`, `docker/nginx.conf` | 文件根目录约束、protected path、terminal placeholder |

#### L3 — Function points
| ID | Function point | Path:line | Status tags |
|---|---|---|---|
| FP-020 | 用 `ADMIN_ENABLED` + token/cookie/csrf 保护 `/_admin` | `docker/admin_service.py:95-152`, `docker/admin_service.py:954-1013` | specified, implemented, changed |
| FP-021 | 白名单 restart/reload/healthcheck action，并写审计日志 | `docker/admin_service.py:247-347`, `docker/admin_service.py:278-295`, `docker/admin_service.py:1110-1115` | specified, implemented |
| FP-022 | 将文件操作限制在 `ADMIN_FILES_ROOT` 内并保护 secret-like paths | `docker/admin_service.py:350-412`, `docker/admin_service.py:446-587` | specified, implemented |
| FP-023 | 暴露默认 disabled 的 web terminal placeholder，仅在 `ttyd` 可用时执行 | `docker/webssh_entrypoint.sh:11-18`, `docker/webssh_entrypoint.sh:47-60`, `docker/nginx.conf:86-106` | specified, implemented, blocked |

#### L4 — Spec candidates
| Spec candidate ID | Function point | Actor / trigger | Input | Output | Acceptance signal | Open question |
|---|---|---|---|---|---|---|
| SPEC-006 | FP-023 | 需要真正交付 `/_admin/terminal/` | `WEBSSH_*`, terminal binary, auth/audit contract | 明确的 break-glass terminal product contract | 有真实终端 smoke + 审计边界文档 | 是补装 `ttyd`，还是移除该路由 |

### CAP-007 部署验证与运维文档

**Purpose:** 让维护者能在本地或 Hugging Face 上执行 build/run/smoke，并据此判断 runtime 是否已接管流量。
**Status tags:** specified;implemented;blocked
**Maturity (M0-M9):** M4 — 本地脚本和完整文档体系都在仓库内，但没有 CI 或提交内运行记录来把它提升到 M5/M7。[scripts/build.sh:1-4] [scripts/run-demo.sh:1-18] [scripts/hf-space-smoke.sh:160-177] [docs/deployment.md:27-119]

#### L2 — Capability modules
| Module | Path | Role |
|---|---|---|
| CAP-007-01 local wrappers | `scripts/` | 本地 build/run/smoke |
| CAP-007-02 deployment docs | `README*.md`, `docs/` | 远端 deploy、runtime SHA 回读、502 排障、人类入口 |

#### L3 — Function points
| ID | Function point | Path:line | Status tags |
|---|---|---|---|
| FP-024 | 提供本地 build/run/smoke 与 HF runtime SHA 回读的脚本和文档合同 | `scripts/build.sh:1-4`, `scripts/run-demo.sh:1-18`, `scripts/hf-space-smoke.sh:4-177`, `docs/deployment.md:27-119`, `docs/development.md:96-129` | specified, implemented, blocked |

#### L4 — Spec candidates
| Spec candidate ID | Function point | Actor / trigger | Input | Output | Acceptance signal | Open question |
|---|---|---|---|---|---|---|
| SPEC-007 | FP-024 | 维护者要证明某次发布真的被 HF runtime 接管 | commit sha + Space URL + tokens | 明确的 release evidence pack | `hf spaces info` + smoke + expected sha 一致 | 是否需要最小 CI 自动收集这些证据 |

## Engineering mapping

| L1 capability | Frontend | Backend | Data | AI/ML | Deploy/Ops |
|---|---|---|---|---|---|
| CAP-001 镜像组装与官方资产复用 | Dify Web bundle intake | Dify API bundle intake | PostgreSQL/Redis binaries | Sandbox/Plugin binary intake | Docker multi-stage build |
| CAP-002 启动初始化与持久化编排 | — | `entrypoint.sh` orchestration | `/data` `/persist` PostgreSQL Redis | Sandbox config rendering | secret/env/persistence bootstrap |
| CAP-003 进程编排与单端口请求路由 | Nginx -> Web | Nginx -> API/admin/ops | route-to-data paths | Plugin hook path | Supervisor + Nginx |
| CAP-004 Plugin 与 Sandbox 适配 | — | wrapper scripts | plugin storage | code execution + plugins | migration/startup glue |
| CAP-005 只读运维诊断 | HTML dashboard | Python HTTP service | logs/config/resource summary | — | health/metrics/ops |
| CAP-006 受控管理与文件边界 | Admin HTML UI | Python admin actions | `/data` file root + audit log | — | auth/csrf/terminal |
| CAP-007 部署验证与运维文档 | docs usage paths | smoke endpoints | runtime SHA + logs | — | build/run/deploy runbooks |

## Cross-view alignment

| L1 capability | Primary product modules (→ `product-structure.md`) | Key function points | Spec candidates | Work items (→ `work-breakdown.md`) | Tracking row |
|---|---|---|---|---|---|
| CAP-001 | PBS-001, PBS-002 | FP-001, FP-002, FP-003 | SPEC-001 | WP-002, WP-006 | TRK-001 |
| CAP-002 | PBS-002 | FP-004, FP-005, FP-006, FP-007, FP-008 | SPEC-002 | WP-002 | TRK-004 |
| CAP-003 | PBS-003 | FP-009, FP-010, FP-011, FP-012, FP-013 | SPEC-003 | WP-001, WP-002 | TRK-009 |
| CAP-004 | PBS-002, PBS-003 | FP-014, FP-015 | SPEC-004 | WP-006 | TRK-014 |
| CAP-005 | PBS-004 | FP-016, FP-017, FP-018, FP-019 | SPEC-005 | WP-003, WP-007 | TRK-016 |
| CAP-006 | PBS-004 | FP-020, FP-021, FP-022, FP-023 | SPEC-006 | WP-004, WP-005 | TRK-020 |
| CAP-007 | PBS-005 | FP-024 | SPEC-007 | WP-001, WP-002, WP-003 | TRK-024 |
