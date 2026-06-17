# Project Overview

`dify-all-in-one` 是一个面向 Hugging Face Docker Space 的 Dify 单容器 Demo 工程。它把官方 Dify 多容器部署中的 Web、API、Worker、Beat、Plugin Daemon、Sandbox、PostgreSQL、Redis、Nginx、只读 `ops-service`和默认关闭的 `admin-service` 收敛到一个 Docker 容器中，目标是课程演示、企业内训、PoC 和快速功能验证。

## 项目目标

- 在 Hugging Face Docker Space 中用一个公开端口运行 Dify。
- 避免 `docker compose`，因为 Hugging Face Space 只运行一个应用容器。
- 使用 bucket-lite 布局：程序仍访问 `/data`，核心状态映射到 `/persist`，日志/cache/run 映射到 `/tmp/dify-aio`。
- 保留官方 Dify 镜像中的预构建 Web/API/Plugin/Sandbox 资产，减少自维护代码。
- 内置只读运维诊断入口，帮助定位 502、启动慢、迁移缺失、日志报错和进程状态问题。

## 非目标

- 不是生产部署方案。
- 不替代官方 Docker Compose 或 Kubernetes 部署。
- 不内置大模型服务。
- 不提供多副本、高可用、水平扩展或外部数据库编排。
- 不把 `OPS_TOKEN` 当作生产级鉴权系统。

## 核心取舍

| 主题 | 当前选择 | 原因 |
| --- | --- | --- |
| 容器形态 | 单容器多进程 | Hugging Face Docker Space 只暴露一个应用容器和端口 |
| 进程管理 | `supervisord` | 需要同时管理 Web/API/Worker/Postgres/Redis 等多个进程 |
| 外部入口 | Nginx `7860` | 对外单端口，内部按路径转发 |
| 向量库 | PostgreSQL + pgvector | 减少 Weaviate 等额外服务 |
| 文件存储 | `/data/dify/storage`，bucket-lite 下指向 `/persist/dify/storage` | 适配 Space Bucket 持久化 |
| Plugin 存储 | `/data/plugin_daemon`，插件包、已安装插件和 assets 指向 `/persist`，工作目录默认在 `/tmp/dify-aio` | 插件和 runtime relaunch 所需包保留，scratch/cache 不占 bucket |
| Sandbox 出网 | 默认关闭 | 演示环境更安全 |
| Marketplace | 默认开启 | 便于 demo/plugin 验证；公开或稳定演示环境可按需关闭以减少外部依赖 |
| NEXT Agent Runtime | `dify-agent` backend 默认关闭，可在 NEXT Space 单独开启 | main 已把 Agent v2 / dify-agent 纳入主链路；本仓库先提供 HFS 可观测的基础 backend，不把它写成生产完成态 |
| 运维入口 | 只读 `ops-service` + 默认关闭的 `admin-service` | 诊断和受控管理分离 |

## 目录结构

```text
.
|-- AGENTS.md                  # Codex 根级 router 和项目指令
|-- Dockerfile                 # Hugging Face Space 和本地 Docker 构建入口
|-- README.md                  # Space card + 项目首页
|-- README.hf-space.md         # Hugging Face Space 部署说明
|-- docker/
|   |-- AGENTS.md              # docker/ runtime navigation card
|   |-- dify.env.runtime       # 运行时默认环境变量
|   |-- dify.env.demo          # 本地 demo env-file
|   |-- sandbox-python-requirements.txt # Sandbox Python 依赖清单
|   |-- entrypoint.sh          # 容器主入口，初始化数据和迁移
|   |-- supervisord.conf       # 多进程编排
|   |-- nginx.conf             # 外部路由和 access log
|   |-- ops_service.py         # 只读运维诊断 HTTP 服务
|   |-- admin_service.py       # 默认关闭的受控管理 HTTP 服务
|   |-- postgres-backup-loop   # bucket-lite PostgreSQL dump 备份循环
|   |-- with-dify-env          # Dify API/Web/Worker 环境包装器
|   |-- with-plugin-env        # Plugin Daemon 环境包装器
|   |-- with-sandbox-env       # Sandbox 环境包装器
|   |-- wait-for-core          # 依赖等待脚本
|   `-- healthcheck.sh         # Docker HEALTHCHECK
|-- scripts/
|   |-- build.sh               # 本地 docker build 包装
|   |-- run-demo.sh            # 本地 docker run 包装
|   |-- hf-space-smoke.sh      # 线上或本地 smoke 验证
|   `-- static-check.sh        # 无 Docker 依赖的静态检查聚合脚本
`-- docs/                      # 完整工程文档
```

## 默认构建输入

开发默认值来自 `Dockerfile`：

```text
DIFY_API_IMAGE_REF=langgenius/dify-api@sha256:62aa0af97dd1fd53b07e03aca90304414cc8bf9019c003dcf199c70e7c885d96
DIFY_WEB_IMAGE_REF=langgenius/dify-web@sha256:8dc4959fe0353003c9dab558652764dfba111440bddb6f3d94716b05415b08c5
PLUGIN_DAEMON_IMAGE_REF=langgenius/dify-plugin-daemon@sha256:cee05a3cbfd8308d2c7a053035a00fb0b32fedec924cb06c8e803bf51ebb871c
SANDBOX_IMAGE_REF=langgenius/dify-sandbox@sha256:41632ad63bddd8bcea83453270f3284d287c9e7cb463dac96644268770270788
DIFY_SANDBOX_SOURCE_REF=44cdbd5d1991b97e40cb113c669800f4628920bb
BASE_IMAGE_REF=python:3.12-slim-bookworm
DIFY_VERSION=main-872b5a081f0d3ac608ee167553abdd7c7e5cdf0b
UV_VERSION=0.11.21
PostgreSQL: 15 + pgvector
Node.js: 22.x
```

NEXT branch 默认值已 pin 到官方 main commit-tag image digest set、HFS 已验证的 Sandbox config/dependencies digest 和 patched Sandbox source ref。需要回到稳定版时不要只改 `DIFY_VERSION`，必须同时切换 `DIFY_API_IMAGE_REF`、`DIFY_WEB_IMAGE_REF`、`PLUGIN_DAEMON_IMAGE_REF`、`SANDBOX_IMAGE_REF` 和 `DIFY_SANDBOX_SOURCE_REF`。

注意：上游 `main/docker/docker-compose.yaml` 仍可能引用最新 release 镜像 tag，例如 `1.14.2`。这不代表 main 源码未变化，也不代表 `docker compose up` 会跑到 main 代码。NEXT/HFS 使用的是官方 Docker Hub 上按 main commit 发布的 `dify-api` / `dify-web` commit-tag 镜像 digest，再叠加本仓库的 all-in-one runtime glue。如果上游 main 源码已经前进但 Docker Hub 尚未发布对应 commit-tag 镜像，NEXT 只能记录差距或改走源码自建镜像，不能只改 metadata 声称已运行该 commit。

## 与源码自建 main 的边界

截至当前 NEXT pin 的上游 `main-872b5a081f0d3ac608ee167553abdd7c7e5cdf0b`，Dify 主仓已经明显不同于 `v1.14.2` 发布边界：`api/pyproject.toml` 把 `dify-agent` 放进生产依赖，`graphon==0.5.1` 进入 API 主依赖，前端工作区使用 `pnpm@11.6.0`、`vinext`、`vite-plus`、`packages/*` 与 `sdks/*`。这些是“源码自建 main”路线的 P0 输入。

当前 HFS NEXT 没有把完整 `langgenius/dify` 源码工作区复制进本仓库，也没有在 Space 内执行 `pnpm build` 或 `uv sync`。它的真实运行来源是官方 main commit image digest：

```text
DIFY_API_IMAGE_REF
DIFY_WEB_IMAGE_REF
```

因此，源码自建路线需要额外处理的 `api/`、`web/`、`dify-agent/`、`packages/`、`sdks/`、`pnpm-workspace.yaml`、`api/uv.lock`、`dify-agent/uv.lock` 和 `tool.uv.sources` Git source mirror，并不属于当前 HFS NEXT 镜像的构建输入。当前 NEXT 只在官方 API venv 上补齐并 build-gate `dify-agent` backend server extras，用于提前验证 Agent v2 runtime 方向；完整 Agent App / workflow Agent node 验收仍必须在开启 `DIFY_AGENT_ENABLED=true` 后单独执行。

## 运行状态入口

普通用户入口：

```text
https://<space>.hf.space/
```

健康检查：

```text
/nginx-health
/healthz
```

只读运维入口：

```text
/_ops/
/_ops/system
/_ops/metrics
```

`/_ops/` dashboard 支持 English / 中文切换，默认跟随浏览器语言。

默认关闭的管理入口：

```text
/_admin/
/_admin/api/status
/_admin/api/audit
```

开启 `ADMIN_ENABLED=true` 后，`/_admin/` 登录页和管理页同样支持 English / 中文切换，并可查看最近 admin 审计事件。默认关闭状态下入口返回 404。

完整排障流程见 [Operations Runbook](./ops-runbook.md)。
