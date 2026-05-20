# 仓库 Agent 指令

## 项目目的

`dify-all-in-one` 是面向 Hugging Face Docker Space 的 Dify 单容器 Demo 工程。它把 Dify Web、API、Worker、Beat、Plugin Daemon、Sandbox、PostgreSQL、Redis、Nginx、只读 `ops-service`、默认关闭的 `/_admin` 管理面（由 `admin-service` 承载）和 Web terminal placeholder 收敛到一个 Docker 容器中，用于企业内训、课程演示、PoC 和快速功能验证。

本仓库不是生产部署方案。生产环境应回到官方 Docker Compose、Kubernetes 或企业内网拆分式部署，并单独设计高可用、备份、鉴权、审计和正式监控。

## Codex 启动行为

- 默认从仓库根目录启动 Codex。
- 本文件是根级 router，也是默认项目指令。
- 子目录 `AGENTS.md` 是按需 navigation card；除非 Codex 从该子树启动或被明确读取，否则不会替代根规则。
- 修改 `Local AGENTS.md = Yes` 的目录前，必须先运行 `cat <path>/AGENTS.md`。
- 如果未来出现多层本地卡片，按从浅到深的顺序读取。
- 文档和代码冲突时，以受版本控制的 runtime 文件为准；如果用户要求同步文档，再更新对应 docs。
- 不要假设 Git remote 名称永远固定。本机可能用 `hf` 指向 Hugging Face Space、`origin` 指向 GitHub 镜像，也可能用其他命名；push、merge 或对比前先看 `git remote -v`。

## 目录地图

| Path | Responsibility | Local AGENTS.md | Read when |
| --- | --- | ---: | --- |
| `README.md` | Hugging Face Space card、根项目介绍、Space metadata | No | 修改 Space metadata、项目说明、本地运行摘要或运维入口时 |
| `README.hf-space.md` | Hugging Face Space 专用部署说明 | No | 修改 Space Settings、Variables、Secrets、诊断命令时 |
| `Dockerfile` | Docker Space 构建入口和 runtime image 组装 | No | 修改 Dify/Plugin/Sandbox 版本、系统依赖、runtime user、`HEALTHCHECK`、`EXPOSE` 或复制资产时 |
| `.dockerignore` | Docker build context 过滤 | No | 修改哪些文件进入 Docker build context 时 |
| `.gitattributes` | Git/LFS 文件处理规则 | No | 修改大文件、二进制文件或 LFS 跟踪规则时 |
| `.gitignore` | 本地 generated/cache 忽略规则 | No | 新增 `.DS_Store`、浏览器 profile、Python cache 等本地 artifact 时 |
| `docker/` | 容器 runtime 合同：entrypoint、env defaults、Supervisor、Nginx、ops-service、admin-service、web terminal placeholder、PostgreSQL backup loop、healthcheck | Yes | 修改 `docker/` 下任何文件前 |
| `scripts/` | 本地 build/run wrapper 和 HF/local smoke 脚本 | No | 修改命令包装、smoke 预期、重试策略、默认 image tag 或默认 Space URL 时 |
| `docs/` | 工程文档、部署指南、运维 runbook、配置和安全说明 | No | 修改用户/运维文档时；先用真实 runtime 文件核对事实 |
| `local/` | 如果存在，为本地计划或 scratch 材料 | No | 除非用户明确要求本地计划材料，否则不要编辑 |
| `.codex/` | 如果存在，为本地 Codex workspace metadata | No | 除非用户明确要求本地 Codex 配置变更，否则不要编辑 |

## 按需 cat 协议

修改有本地卡片的目录前运行：

```bash
cat docker/AGENTS.md
```

然后同时遵守根文件和本地卡片。若规则冲突，目标文件所在目录更近的本地卡片优先。若命令、变量、endpoint、route 或启动顺序不确定，直接查真实文件，不要根据文件名推断。

## 真实命令面

仓库没有 `package.json`、`pyproject.toml`、`Makefile` 或 workspace package manager。真实命令面来自 shell 脚本、Docker、Python 语法检查、curl smoke 和可选 Hugging Face CLI。

| Command | Purpose | Scope | Sandbox notes |
| --- | --- | --- | --- |
| `scripts/static-check.sh` | 聚合轻量静态检查：shell 语法、Python 语法和 diff whitespace | repo | 本地 shell/Python 可跑；不需要 Docker 或网络 |
| `bash -n docker/entrypoint.sh docker/with-dify-env docker/with-plugin-env docker/with-sandbox-env docker/wait-for-core docker/healthcheck.sh docker/postgres-backup-loop docker/webssh_entrypoint.sh scripts/build.sh scripts/run-demo.sh scripts/admin-smoke.sh scripts/hf-space-smoke.sh scripts/static-check.sh` | 检查所有 runtime/helper shell 脚本语法 | `docker/`, `scripts/` | 本地 shell 可跑；不需要 Docker 或网络 |
| `python3 -m py_compile docker/ops_service.py docker/admin_service.py` | 检查 ops/admin Python 服务语法 | `docker/ops_service.py`, `docker/admin_service.py` | 需要 Python 3 |
| `git diff --check` | 检查 diff whitespace 问题 | repo | 只读；如果有无关 dirty diff，使用 path-limited 形式 |
| `scripts/build.sh` | 构建默认镜像 `dify-all-in-one-hf-space:1.14.1` | repo | 需要 Docker daemon；构建阶段通常需要访问 Docker Hub、APT、PyPI/npm、PostgreSQL repo |
| `scripts/build.sh my-dify-aio:dev` | 用自定义 tag 构建镜像 | repo | 需要 Docker daemon 和构建网络 |
| `scripts/run-demo.sh` | 本地启动 demo，默认 `http://localhost:8080` | repo | 需要 Docker daemon 和已构建镜像；会删除同名 `dify-aio-hf-demo` 容器 |
| `OPS_TOKEN=dify_ops_demo_token scripts/hf-space-smoke.sh http://localhost:8080` | smoke 本地运行容器 | repo | 需要本地容器正在运行 |
| `OPS_TOKEN=dify_ops_demo_token scripts/hf-space-smoke.sh https://blueskyxn-dify-all-in-one.hf.space` | smoke 线上 HF Space | live Space | 需要网络和有效 demo 或配置后的 `OPS_TOKEN` |
| `SMOKE_ADMIN_ENABLED=true ADMIN_TOKEN=<admin-token> OPS_TOKEN=dify_ops_demo_token scripts/hf-space-smoke.sh <base-url>` | smoke 已开启的 `/_admin` 管理面 | local/live Space | 仅在 `ADMIN_ENABLED=true` 且有有效 `ADMIN_TOKEN` 时使用；写 action 还需显式 `SMOKE_ADMIN_ACTIONS=true` |
| `ADMIN_EXPECTED_ENABLED=true ADMIN_TOKEN=<admin-token> scripts/admin-smoke.sh <base-url>` | 单独 smoke `/_admin` 鉴权、CSRF、action confirm 和 file manager 边界 | local/live Space | 默认不执行真实 action；写 action 需显式 `ADMIN_SMOKE_ACTIONS=true` |
| `hf spaces info BlueSkyXN/dify-all-in-one` | 查看 Space runtime metadata | deployment | 需要 HF CLI、网络和必要登录态 |
| `hf spaces logs BlueSkyXN/dify-all-in-one -n 220` | 查看 app logs | deployment | 需要 HF CLI 和网络 |
| `hf spaces logs BlueSkyXN/dify-all-in-one --build -n 220` | 查看 build logs | deployment | 需要 HF CLI 和网络 |
| `curl https://blueskyxn-dify-all-in-one.hf.space/nginx-health` | 检查 Nginx public liveness | live Space | 需要网络 |
| `curl https://blueskyxn-dify-all-in-one.hf.space/healthz` | 检查综合健康探针 | live Space | 需要网络；warmup 时可能 503 |
| `curl -H "X-Ops-Token: dify_ops_demo_token" https://blueskyxn-dify-all-in-one.hf.space/_ops/health` | 查看只读 ops health | live Space | 需要网络和有效 `OPS_TOKEN` |

按修改范围选择最小验证集合。不要在不需要 runtime 验证时运行 Docker、Hugging Face 或 live curl 命令。

## 全局规则

- 始终把本仓库定位为 demo/all-in-one deployment bundle，不要写成生产级 Dify 部署。
- 优先复用 `Dockerfile` 已经引用的官方 Dify Web/API/Plugin/Sandbox 镜像资产，不要复制或 fork 大量上游源码到本仓库。
- 保持 Hugging Face Docker Space 约束：单 Docker 容器、单公开 app port、Nginx 对外监听 `7860`、运行时持久化数据在 `/data` 或明确配置的 persistence mount 下。
- `README.md` 的 `app_port: 7860`、`docker/nginx.conf` 的 `listen 7860`、`Dockerfile EXPOSE 7860`、docs 和 Space 设置必须保持一致。
- runtime 尽量以 UID `1000` 的 `user` 运行。不要新增依赖 root runtime 的启动逻辑，除非 `Dockerfile` 明确提供并说明该能力。
- `/data` 是 runtime persistence 边界。不要把 PostgreSQL、Redis、插件缓存、上传文件、日志、generated secrets 或运行状态放进 repo。
- `entrypoint.sh` 生成的 secrets 属于 `/data/config/generated.env`。不要提交 generated secret 文件，也不要在 docs 或 AGENTS 中粘贴真实 generated secret。
- `dify_demo_password`、`dify_redis_password`、`dify_ops_demo_token` 这类值只能作为 demo 默认值描述，不要写成生产安全建议。
- env 加载顺序是：Docker/HF 已注入 env 优先，`docker/dify.env.runtime` 用默认值补齐，`/data/config/generated.env` 补齐自动生成 secrets。不要破坏显式外部 env 覆盖。
- 新增或重命名 env var 时，同步检查 `docker/dify.env.runtime`、`docker/dify.env.demo`、相关 `docker/with-*` wrapper、`docker/entrypoint.sh`、`docker/supervisord.conf`、`docker/ops_service.py`、`docker/admin_service.py`、`docker/webssh_entrypoint.sh` 和 `docs/configuration.md`。
- `DB_USERNAME`、`DB_DATABASE`、`DB_PLUGIN_DATABASE` 在 `entrypoint.sh` 中必须保留 PostgreSQL identifier 校验。
- Plugin Daemon 必须在启动 server 前执行 migration：`/opt/dify/plugin-daemon/commandline migrate && exec /opt/dify/plugin-daemon/main`。
- Sandbox 默认 `SANDBOX_ENABLE_NETWORK=false`。如果开启网络，必须说明安全影响并同步 `docs/security.md`。
- Marketplace 默认开启，便于 demo/plugin 验证。若改为关闭或调整外部 Marketplace 地址，必须同步说明 Hugging Face 上的外部依赖和演示不确定性。
- `ops-service` 是只读诊断面。`/_ops` 不能新增重启服务、修改配置、执行 SQL、删除数据、任意命令执行、任意文件读取或返回 secret 原文的能力。
- `OPS_TOKEN` 只是 demo/lightweight diagnostic gate，不是生产级鉴权系统，不能用它为写操作背书。
- `admin-service` 承载独立 `/_admin` 管理面，默认 `ADMIN_ENABLED=false`。管理 action 必须保留白名单、`ADMIN_TOKEN`、CSRF/confirm 和审计边界；不要把写操作搬到 `/_ops`。
- `/_ops/logs` 必须保持 service 白名单，不要从请求参数读取任意文件路径。
- CLI 和自动化示例优先使用 `X-Ops-Token` 或 `Authorization: Bearer`；`?token=` 只适合临时浏览器调试。
- Nginx 路由修改必须保护 `/nginx-health`、`/healthz`、`/_ops/`、`/_admin/`、`/_admin/terminal/`、`/console/api`、`/api`、`/v1`、`/files`、`/mcp`、`/triggers`、`/socket.io/`、`/e/`、`/explore` 和 `/`，除非用户明确要求重做路由。
- `/socket.io/` 必须保留 WebSocket `Upgrade` / `Connection` header。
- `/_admin/terminal/` 必须保留 `auth_request /_admin_auth_terminal` 和 WebSocket `Upgrade` / `Connection` header；当前镜像没有 `ttyd`，默认只是 disabled placeholder。
- `/e/` 必须保留 `Dify-Hook-Url`，用于 Plugin Daemon endpoint hook。
- `NGINX_PORT` 和 `NGINX_CLIENT_MAX_BODY_SIZE` 是 env defaults；除非实现模板渲染，不要声称它们会动态改变静态 `docker/nginx.conf`。
- Shell 脚本保持 Bash 和 `set -euo pipefail` 风格，修改后跑 `bash -n`。
- `docker/ops_service.py` 当前是轻依赖标准库 HTTP 服务。引入框架会影响 `Dockerfile`、docs 和验证口径。
- 文档修改不要大段复制 README；只改发生变化的事实、命令、endpoint 或限制。
- 排查 live 502 时按顺序看：HF runtime stage/SHA、`/nginx-health`、`/healthz`、`/_ops/health`、`/_ops/status`、`/_ops/errors`、定向 `/_ops/logs`、Hugging Face app/build logs。
- Space 顶层 repo `sha` 更新不代表新镜像已接管流量；必须确认 `runtime.stage=RUNNING` 且 `runtime.raw.sha=<expected commit sha>`。
- 如果 GitHub 与 Hugging Face remotes 分叉，先 fetch 两边并对比 head，再决定 merge 或 push。不要假设任意 `<remote>/main` 与另一个 remote 等价。

## 不要做

- 不要在用户没有明确要求并确认目标 remote 前执行 `git push origin main`、`git push hf main` 或其他 main 分支推送。
- 不要在用户没有明确要求时推送 GitHub mirror；先确认要更新哪个 remote/branch。
- 不要在用户没有明确要求时执行 `docker volume rm dify-hf-demo-persist`。
- 不要执行 `git reset`、`git checkout`、`git clean`、`git stash` 等破坏性 Git 操作，除非用户明确要求。
- 不要把 `.DS_Store`、local cache、runtime data 或 generated files 当作正常代码改动处理。
- 不要新增 Compose/Kubernetes 生产部署并把它写成本 demo 的默认目标，除非用户明确要求生产化路线。
- 不要把 PostgreSQL、Redis、Sandbox、Plugin Daemon 内部端口、ops-service、admin-service 或 web-terminal 直接暴露到 Space 公网入口。
- 不要在 `/_ops` 下新增任意写操作；若用户要求 admin surface，必须单独设计鉴权、审计、白名单 action 和显式确认。
- 不要通过 `/_ops/config`、logs、docs 或示例暴露 secret 原文；secret presence boolean 可以保留。
- 不要静默升级 `DIFY_VERSION`、Plugin Daemon、Sandbox、Node.js、PostgreSQL major 或 uv 版本。版本升级必须配套 build 和 smoke。
- 不要移除 pgvector 初始化，除非同步替换 vector-store 设计和文档。
- 不要把 syntax check 通过写成 Docker image 可运行的证据；它只是轻量 gate。
- 不要在读取 `docker/AGENTS.md` 前修改 `docker/`。

## 验证标准

AGENTS-only 改动：

```bash
git diff --check -- AGENTS.md docker/AGENTS.md
```

如果 AGENTS 文件还未被 Git 跟踪，`git diff` 可能看不到内容；用只读命令额外检查 trailing whitespace 和可读性。

Docs-only 改动：

1. 运行 `git diff --check`，若有无关 dirty diff 则使用 path-limited 形式。
2. 检查新增 Markdown trailing whitespace。
3. 人工核对文档事实是否仍匹配当前 runtime 文件。

Shell、Nginx、Dockerfile、env、Supervisor、ops-service 或 runtime lifecycle 改动：

```bash
bash -n \
  docker/entrypoint.sh \
  docker/with-dify-env \
  docker/with-plugin-env \
  docker/with-sandbox-env \
  docker/wait-for-core \
  docker/healthcheck.sh \
  docker/postgres-backup-loop \
  docker/webssh_entrypoint.sh \
  scripts/build.sh \
  scripts/run-demo.sh \
  scripts/admin-smoke.sh \
  scripts/hf-space-smoke.sh \
  scripts/static-check.sh
python3 -m py_compile docker/ops_service.py
python3 -m py_compile docker/admin_service.py
git diff --check
```

如果 Docker 可用且修改影响 runtime 行为，继续跑：

```bash
scripts/build.sh
scripts/run-demo.sh
OPS_TOKEN=dify_ops_demo_token scripts/hf-space-smoke.sh http://localhost:8080
```

如果修改已部署到 Hugging Face，先确认 runtime metadata：

```bash
hf spaces info BlueSkyXN/dify-all-in-one
```

再跑线上 smoke：

```bash
OPS_TOKEN=dify_ops_demo_token scripts/hf-space-smoke.sh https://blueskyxn-dify-all-in-one.hf.space
```

无法运行的外部验证必须在最终回复里说明：缺 Docker、缺 HF CLI、缺网络、缺凭据、live Space 未就绪，或本次改动不涉及 runtime。

## 给后续 Agent 的提示

- 仓库很小，优先查真实文件，不要抽象推断。
- `docs/development.md` 是验证流程的人类入口。
- `docs/ops-runbook.md` 是 live 502 和 Hugging Face runtime 排障入口。
- `docs/file-reference.md` 有助于定位文件职责，但源码和脚本仍是最终事实源。
- 最终回复要区分：本地已验证、需要 Docker 才能验证、需要 live Hugging Face Space 才能验证。
