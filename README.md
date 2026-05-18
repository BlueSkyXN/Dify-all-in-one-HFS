---
title: Dify All-in-One Demo
emoji: 🧩
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
suggested_hardware: cpu-upgrade
pinned: false
---

# Dify All-in-One Demo for Hugging Face Space

这是一个面向 **Hugging Face Docker Space** 的 Dify 单容器 Demo 工程。它把 Dify 的多服务部署压缩到一个 Docker 容器中，用于企业内训、课程演示和 PoC。

> 该工程不是生产部署方案。生产环境应回到官方 Docker Compose、Kubernetes，或企业内网的拆分式部署。

## 文档入口

- [Hugging Face Space 部署说明](./README.hf-space.md)
- [运维与可观测 Runbook](./docs/ops-runbook.md)

## 组件布局

容器内由 `supervisord` 启动多个进程，并由 Nginx 在单一外部端口 `7860` 反向代理：

```text
nginx:7860
  ├─ Dify Web:3000
  ├─ Dify API:5001
  ├─ Dify Worker
  ├─ Dify Beat
  ├─ Plugin Daemon:5002
  ├─ Sandbox:8194
  ├─ PostgreSQL 15 + pgvector
  └─ Redis
```

关键裁剪：

- 使用 `pgvector` 替代 Weaviate，减少一个独立向量库服务。
- 使用本地文件系统 `/data/dify/storage`。
- 不内置大模型；模型服务建议外接 HTTPS 模型 API、OpenAI-compatible 网关或企业模型网关。
- 默认关闭 Marketplace：`MARKETPLACE_ENABLED=false`。
- 默认关闭 Sandbox 出网：`SANDBOX_ENABLE_NETWORK=false`。
- 运行时采用 UID `1000` 的非 root 用户，适配 Hugging Face Docker Space 权限模型。

## 直接部署到 Hugging Face Space

1. 新建 Space，SDK 选择 **Docker**。
2. 把本仓库所有文件推送到 Space 仓库根目录。根目录必须包含：

```text
README.md
Dockerfile
docker/
scripts/
```

3. Space 会根据 `README.md` 顶部 YAML 识别：

```yaml
sdk: docker
app_port: 7860
```

4. 在 Space Settings 中建议启用：

```text
Hardware: CPU Upgrade 或更高
Storage: Persistent Storage / Storage Bucket
Visibility: Private 或 Protected
```

5. 在 Space Settings → Variables / Secrets 中设置可选变量。

推荐 Variables：

```env
MARKETPLACE_ENABLED=false
SANDBOX_ENABLE_NETWORK=false
FORCE_VERIFYING_SIGNATURE=false
```

推荐 Secrets：

```env
SECRET_KEY=<固定强随机值>
PLUGIN_DAEMON_KEY=<固定强随机值>
PLUGIN_DIFY_INNER_API_KEY=<固定强随机值>
CODE_EXECUTION_API_KEY=<固定强随机值>
SANDBOX_API_KEY=<固定强随机值>
```

如果不设置这些 Secret，入口脚本会自动生成并写入 `/data/config/generated.env`。只有在 Space 启用了持久化 Storage 时，这些自动生成值才能跨重启保留。

## HF Space URL 处理

Hugging Face Spaces 的运行时环境包含 `SPACE_HOST`。如果未显式设置 `PUBLIC_URL`，本工程会自动使用：

```text
https://${SPACE_HOST}
```

并派生：

```text
CONSOLE_WEB_URL
CONSOLE_API_URL
APP_WEB_URL
APP_API_URL
FILES_URL
TRIGGER_URL
ENDPOINT_URL_TEMPLATE
```

因此，通常不需要手工设置 `PUBLIC_URL`。如果你使用自定义域名，可以在 Space Variables 中显式设置：

```env
PUBLIC_URL=https://your.custom.domain
```

## 本地构建和运行

```bash
docker build -t dify-all-in-one-hf-space:1.14.1 .
```

```bash
docker run -d \
  --name dify-aio-hf \
  -p 8080:7860 \
  -v dify-hf-demo-data:/data \
  --env-file docker/dify.env.demo \
  dify-all-in-one-hf-space:1.14.1
```

打开：

```text
http://localhost:8080
```

查看日志：

```bash
docker logs -f dify-aio-hf
docker exec -it dify-aio-hf supervisorctl status
```

## 数据目录

所有运行时数据都放在 `/data`：

```text
/data/postgres          PostgreSQL 数据
/data/redis             Redis AOF/RDB
/data/dify/storage      Dify 文件存储
/data/plugin_daemon     插件存储与运行目录
/data/config            自动生成的密钥环境文件
/data/logs              日志
/data/run               pid / runtime config
/data/run/nginx         Nginx 临时目录
```

在 Hugging Face Space 上，如果没有启用持久化 Storage，Space 重启后这些数据会丢失。

## 运维与可观测入口

本工程在 Dify 前面保留 Nginx 作为单一入口，并内置一个只读 `ops-service`。Nginx 会暴露：

```text
/nginx-health          Nginx 存活探针
/healthz               综合健康探针
/_ops/                 只读运维诊断入口
```

`/_ops/` 默认需要 `OPS_TOKEN`。Demo 默认值是：

```env
OPS_TOKEN=dify_ops_demo_token
```

如果 Space 是公开的，建议在 Space Settings → Variables 中覆盖成你自己的固定值：

```env
OPS_TOKEN=<fixed-random-token>
```

CLI 访问示例：

```bash
curl -H "X-Ops-Token: $OPS_TOKEN" \
  https://your-space.hf.space/_ops/health
```

浏览器临时访问可使用：

```text
https://your-space.hf.space/_ops/?token=<OPS_TOKEN>
```

只读接口包括：

```text
/_ops/health           综合健康、内部端口、API/Web 探针
/_ops/status           supervisor 进程状态
/_ops/config           非敏感配置摘要与密钥存在性
/_ops/version          运行版本与 Space 元数据
/_ops/errors           近期错误摘要
/_ops/logs             白名单服务日志 tail
```

Nginx access log 使用 JSON 格式输出到 stdout，包含 `request_id`、`uri`、`status`、`request_time`、`upstream_addr`、`upstream_status` 和 `upstream_response_time`，便于从 Hugging Face App logs 里快速区分 Web/API/Plugin/Ops 的上游问题。

部署后 smoke：

```bash
OPS_TOKEN=dify_ops_demo_token \
  scripts/hf-space-smoke.sh https://your-space.hf.space
```

更完整的 endpoint 说明、502 排障流程、Plugin Daemon migration 说明和发布后验收步骤见 [运维与可观测 Runbook](./docs/ops-runbook.md)。

## 运行限制

- Hugging Face Docker Space 不支持 `docker compose`；本工程用单容器多进程方式替代。
- Space 对外只暴露一个应用端口；本工程使用 Nginx 对外监听 `7860`。
- Hugging Face 免费硬件会休眠；建议使用 CPU Upgrade + 持久化 Storage。
- Space 运行时出站网络通常只适合 HTTP/HTTPS 端口；如果要接企业模型网关，建议暴露 HTTPS/443。
- 构建阶段需要访问 GitHub、PyPI、npm/pnpm registry、APT 源和 Docker Hub。无外网环境需要提前做制品缓存。
- 当前工程未在此对话环境中执行完整 Docker build；需要在有 Docker daemon 的机器或 Hugging Face Space 构建日志中验证。

## 课程演示建议

1. 初始化管理员账号。
2. 配置模型 Provider。
3. 创建 Chat App。
4. 上传文档并建立知识库。
5. 创建 Workflow。
6. 演示 Code 节点和 Sandbox。
7. 演示通过 `/v1/workflows/run` 调用 Workflow API。
8. 查看日志、任务、token 和错误排查。
9. 解释为什么 Demo 架构不等于生产架构。
