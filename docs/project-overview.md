# Project Overview

`dify-all-in-one` 是一个面向 Hugging Face Docker Space 的 Dify 单容器 Demo 工程。它把官方 Dify 多容器部署中的 Web、API、Worker、Beat、Plugin Daemon、Sandbox、PostgreSQL、Redis 和 Nginx 收敛到一个 Docker 容器中，目标是课程演示、企业内训、PoC 和快速功能验证。

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
| Plugin 存储 | `/data/plugin_daemon`，核心插件文件指向 `/persist` | 插件保留，包缓存不占 bucket |
| Sandbox 出网 | 默认关闭 | 演示环境更安全 |
| Marketplace | 默认关闭 | 降低外部依赖和演示不确定性 |
| 运维入口 | 只读 `ops-service` + 默认关闭的 `admin-service` | 诊断和受控管理分离 |

## 目录结构

```text
.
|-- Dockerfile                 # Hugging Face Space 和本地 Docker 构建入口
|-- README.md                  # Space card + 项目首页
|-- README.hf-space.md         # Hugging Face Space 部署说明
|-- docker/
|   |-- dify.env.runtime       # 运行时默认环境变量
|   |-- dify.env.demo          # 本地 demo env-file
|   |-- entrypoint.sh          # 容器主入口，初始化数据和迁移
|   |-- supervisord.conf       # 多进程编排
|   |-- nginx.conf             # 外部路由和 access log
|   |-- ops_service.py         # 只读运维诊断 HTTP 服务
|   |-- admin_service.py       # 默认关闭的受控管理 HTTP 服务
|   |-- with-dify-env          # Dify API/Web/Worker 环境包装器
|   |-- with-plugin-env        # Plugin Daemon 环境包装器
|   |-- with-sandbox-env       # Sandbox 环境包装器
|   |-- wait-for-core          # 依赖等待脚本
|   `-- healthcheck.sh         # Docker HEALTHCHECK
|-- scripts/
|   |-- build.sh               # 本地 docker build 包装
|   |-- run-demo.sh            # 本地 docker run 包装
|   `-- hf-space-smoke.sh      # 线上 smoke 验证
`-- docs/                      # 完整工程文档
```

## 关键版本

默认版本来自 `Dockerfile`：

```text
Dify API/Web: 1.14.1
Plugin Daemon: 0.6.0-local
Sandbox: 0.2.15
Python runtime: 3.12 slim bookworm
PostgreSQL: 15 + pgvector
Node.js: 22.x
uv: 0.8.9
```

这些版本可以通过 Docker build args 覆盖，但升级前必须重新验证 API/Web/Plugin/Sandbox 的兼容性和迁移行为。

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

默认关闭的管理入口：

```text
/_admin/
/_admin/api/status
```

完整排障流程见 [Operations Runbook](./ops-runbook.md)。
