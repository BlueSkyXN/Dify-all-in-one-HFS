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
| NEXT Agent Runtime | `dify-agent` backend 与 loopback `shellctl` shell layer 在 NEXT 默认开启 | main 已把 Agent v2 / dify-agent 纳入主链路；本仓库提供 HFS 可观测的基础 backend 和 shell layer，不把它写成完整 Agent/Skills 验收完成态 |
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
|   |-- run-postgres           # 本地/外部 PostgreSQL 模式包装器
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
DIFY_API_IMAGE_REF=langgenius/dify-api@sha256:1625345656d367085adb258e9670f72ee359dcb434ad5d09f96fabe0cbcb423f
DIFY_WEB_IMAGE_REF=langgenius/dify-web@sha256:d0d6a28f7bbec140816f7e45f9b5b6cb2c32b9aadb9231697eef850fae4ac79a
PLUGIN_DAEMON_IMAGE_REF=langgenius/dify-plugin-daemon@sha256:3c694329357bc580b28bdec59321a981acd3279f8f69d1a3fb59a47cf7f770c3
SANDBOX_IMAGE_REF=langgenius/dify-sandbox@sha256:cb076f71cc84c14d4e4f7753ff95c4ba70a3b5816962b4f93bcf42f23a6e5cb8
DIFY_SOURCE_REPO=https://github.com/BlueSkyXN/dify.git
DIFY_SOURCE_MAIN_REF=4890f9e16557b3cbae6f9388b69f2cda1c39ee44
DIFY_AGENT_SOURCE_REF=4890f9e16557b3cbae6f9388b69f2cda1c39ee44
DIFY_UPSTREAM_MAIN_REF=abb9972e1960eea63041854cb6fbe15a7abe2bd6
DIFY_SANDBOX_SOURCE_REF=97c8097d51d0f46238bb720b1e9e9439ce68784d
BASE_IMAGE_REF=python:3.12-slim-bookworm
DIFY_VERSION=BlueSkyXN-dify-main-4890f9e16557b3cbae6f9388b69f2cda1c39ee44-upstream-images-abb9972e1960eea63041854cb6fbe15a7abe2bd6-agent-4890f9e16557b3cbae6f9388b69f2cda1c39ee44
UV_VERSION=0.11.21
PostgreSQL: 15 + pgvector
Node.js: 22.x
```

NEXT branch 默认值已 pin 到 Docker Hub 当前 `langgenius/dify-api:main` / `langgenius/dify-web:main` digest set、对应的 `DIFY_UPSTREAM_MAIN_REF`、`BlueSkyXN/dify` self main source ref、当前 Sandbox config/dependencies digest 和 patched Sandbox source ref。需要回到稳定版时不要只改 `DIFY_VERSION`，必须同时切换 `DIFY_API_IMAGE_REF`、`DIFY_WEB_IMAGE_REF`、`DIFY_UPSTREAM_MAIN_REF`、`DIFY_SOURCE_MAIN_REF`、`DIFY_AGENT_SOURCE_REF`、`PLUGIN_DAEMON_IMAGE_REF`、`SANDBOX_IMAGE_REF` 和 `DIFY_SANDBOX_SOURCE_REF`。

注意：上游 `main/docker/docker-compose.yaml` 的 release/service 组合和 Docker Hub `main` image 发布节奏不是同一个 truth source。NEXT/HFS 使用 Docker Hub 当前 `main` digest，再叠加本仓库 all-in-one runtime glue 与 `BlueSkyXN/dify` self main 的 `dify-agent` package。fork merge commit 通常没有 API/Web commit tag，所以不能只改 metadata 声称 Web/API 镜像由 fork SHA 选择。

## 与源码自建 main 的边界

截至当前 NEXT pin 的 `BlueSkyXN/dify` self main `4890f9e16557b3cbae6f9388b69f2cda1c39ee44`，fork 已选择性吸收最新上游安全、可靠性与 Agent DSL 变化，并保留 fork-specific Python shellctl/Agent Stub 以及 Agent monitoring correctness 修复。Web/API image 则明确记录来自 official upstream main `abb9972e1960eea63041854cb6fbe15a7abe2bd6`。当前 API image 要求 `graphon==0.6.0`，self `dify-agent` 要求 `graphon==0.5.2`，因此两者必须使用独立 virtualenv，不能继续把 Agent overlay 装进 `/app/api/.venv`。

当前 HFS NEXT 没有把完整 `BlueSkyXN/dify` 源码工作区复制进本仓库，也没有在 Space 内执行 `pnpm build` 或 `uv sync`。它的真实运行来源是 digest-pinned API/Web `main` image，加上从 maintained fork main 安装的 `dify-agent` package：

```text
DIFY_API_IMAGE_REF
DIFY_WEB_IMAGE_REF
DIFY_AGENT_SOURCE_REF
```

因此，源码自建路线需要额外处理的 `api/`、`web/`、`dify-agent/`、`packages/`、`sdks/`、`pnpm-workspace.yaml`、`api/uv.lock`、`dify-agent/uv.lock` 和 `tool.uv.sources` Git source mirror，并不属于当前 HFS NEXT 镜像的构建输入。当前 NEXT 在 `/opt/dify-agent/.venv` 独立安装 self package 的 `server`、`grpc` 和 `shellctl-server` extras，API image venv 保持原样。NEXT branch 默认打开 Agent v2 前端 gate、Collaboration、`dify-agent` backend、shell layer、Agent Stub 和 Agent Drive manifest；完整 Agent App / Skills / workflow Agent node 验收仍必须进入真实 Console 做上传、列表、删除、slash mention 和运行链路检查，不能只凭 env 开关或 `/_ops/health` 下结论。

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
