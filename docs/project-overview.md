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
DIFY_API_IMAGE_REF=langgenius/dify-api:latest
DIFY_WEB_IMAGE_REF=langgenius/dify-web:latest
PLUGIN_DAEMON_IMAGE_REF=langgenius/dify-plugin-daemon:main-local
SANDBOX_IMAGE_REF=langgenius/dify-sandbox:latest
BASE_IMAGE_REF=python:3.12-slim-bookworm
DIFY_VERSION=latest
UV_VERSION=latest
PostgreSQL: 15 + pgvector
Node.js: 22.x
```

开发默认值允许使用可移动 tag。发布或长期演示应把 image ref 换成 `image@sha256:...` digest，并固定 `UV_VERSION`；`DIFY_VERSION` 只作为 metadata，不再决定 Web/API 镜像内容。

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
