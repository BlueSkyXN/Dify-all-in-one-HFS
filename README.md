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

- [完整工程文档](./docs/README.md)
- [Hugging Face Space 部署说明](./README.hf-space.md)
- [架构说明](./docs/architecture.md)
- [HFS 范式对齐](./docs/hfs-alignment.md)
- [项目状态与下一步计划](./docs/project-status-and-roadmap.md)
- [配置参考](./docs/configuration.md)
- [部署指南](./docs/deployment.md)
- [发布检查清单](./docs/release-checklist.md)
- [bucket-lite 持久化演练](./docs/bucket-lite-drill.md)
- [运维与可观测 Runbook](./docs/ops-runbook.md)
- [开发指南](./docs/development.md)
- [文件职责说明](./docs/file-reference.md)
- [安全说明](./docs/security.md)

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
  ├─ ops-service:8081
  ├─ admin-service:8082
  ├─ PostgreSQL 15 + pgvector
  └─ Redis
```

关键裁剪：

- 使用 `pgvector` 替代 Weaviate，减少一个独立向量库服务。
- 使用本地文件系统 `/data/dify/storage`。
- 不内置大模型；模型服务建议外接 HTTPS 模型 API、OpenAI-compatible 网关或企业模型网关。
- 默认启用 Marketplace：`MARKETPLACE_ENABLED=true`，便于 demo/plugin 验证。
- 默认关闭 Sandbox 出网：`SANDBOX_ENABLE_NETWORK=false`。
- 运行时采用 UID `1000` 的非 root 用户，适配 Hugging Face Docker Space 权限模型。

## HFS 范式定位

本仓库按本机 HFS 开发范式归类为 **Pattern A: HFS Port Repository**，runtime 获取模式为 **image-assembly**。仓库根目录就是 Hugging Face Space root，也是 GitHub 维护 root；`hfs-dev.toml` 是 alignment manifest；`docker/` 是多进程 runtime glue，不应迁入 `cloud/hfs/`。详细对齐说明见 [HFS 范式对齐](./docs/hfs-alignment.md)。

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

5. 在 Space Settings → Variables / Secrets 中按本地 `.env.local` 的分区上传配置。

`.env.local` 是本地唯一配置事实源，已被 `.gitignore` 忽略。`[HF Secrets]` 区上传到 Space Secrets，`[HF Variables]` 区上传到 Space Variables；与 `docker/dify.env.runtime` 默认值一致的变量不要重复上传。

推荐 Variables：

```env
PERSIST_MODE=bucket
POSTGRES_BUCKET_FAILURE_MODE=fallback-to-runtime
```

推荐 Secrets：

```env
OPS_TOKEN=<强随机值>
DB_PASSWORD=<固定 demo 值或强随机值>
REDIS_PASSWORD=<固定 demo 值或强随机值>
SECRET_KEY=<固定 demo 值或强随机值>
PLUGIN_DAEMON_KEY=<固定 demo 值或强随机值>
PLUGIN_DIFY_INNER_API_KEY=<固定 demo 值或强随机值>
CODE_EXECUTION_API_KEY=<固定 demo 值或强随机值>
```

不要单独上传 `SANDBOX_API_KEY` 和 `INNER_API_KEY_FOR_PLUGIN`，除非你明确要拆分内部 key。默认情况下，`SANDBOX_API_KEY` 继承 `CODE_EXECUTION_API_KEY`，`INNER_API_KEY_FOR_PLUGIN` 继承 `PLUGIN_DIFY_INNER_API_KEY`。

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
docker build -t dify-all-in-one-hf-space:latest .
```

```bash
docker run -d \
  --name dify-aio-hf \
  -p 8080:7860 \
  -v dify-hf-demo-persist:/persist \
  --env-file docker/dify.env.demo \
  dify-all-in-one-hf-space:latest
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

程序仍通过 `/data` 访问运行时目录；默认 `PERSIST_MODE=auto`。如果 `/persist` 是挂载点且可写，会启用 bucket-lite 布局：

```text
/data/postgres                 -> /persist/postgres
/data/dify/storage             -> /persist/dify/storage
/data/config                   -> /persist/config
/data/plugin_daemon/plugin     -> /persist/plugin_daemon/plugin
/data/plugin_daemon/assets     -> /persist/plugin_daemon/assets
/data/plugin_daemon/plugin_packages -> /persist/plugin_daemon/plugin_packages
/data/plugin_daemon/cwd        -> /tmp/dify-aio/plugin_cwd
/data/logs                     -> /tmp/dify-aio/logs
/data/run                      -> /tmp/dify-aio/run
/data/redis                    -> /tmp/dify-aio/redis
HF_HOME/HF_HUB_CACHE           -> /tmp/dify-aio/hf-cache(/hub)
```

`/persist/postgres-backups/` 会由 `postgres-backup` 进程定期生成 timestamped dump，并在校验通过后更新 `latest.sql.gz`、`latest.created_at` 和 `latest.sha256`。默认 `POSTGRES_BUCKET_FAILURE_MODE=fallback-to-runtime`：如果 `/persist/postgres` 在重启后无法作为 live PGDATA 启动，入口脚本会打印 PostgreSQL 失败上下文，然后把 `/data/postgres` 切到 `/tmp/dify-aio/postgres`，并在有可用 dump 时先从 `latest.sql.gz` 恢复。若没有挂载 `/persist`，容器回退到旧的 `/data` 布局。

bucket-lite 下 Plugin Daemon 默认直接以 `/persist/plugin_daemon` 作为 `PLUGIN_STORAGE_LOCAL_ROOT`，避免启动时从 `/data/plugin_daemon/plugin` 这个 symlink root 枚举 installed 插件失败。`/data/plugin_daemon/*` 仍作为兼容访问路径保留。

如果显式设置 `PLUGIN_CWD_PERSISTENCE=true`，`/data/plugin_daemon/cwd` 会改为映射到 `/persist/plugin_daemon/cwd`。

## 运维与可观测入口

本工程在 Dify 前面保留 Nginx 作为单一入口，并内置一个只读 `ops-service`。Nginx 会暴露：

```text
/nginx-health          Nginx 存活探针
/healthz               综合健康探针
/_ops/                 只读运维诊断入口
/_admin/               受控管理入口，默认关闭
```

`/_ops/` 默认需要 `OPS_TOKEN`。镜像仍保留 demo 默认值，但除非显式设置 `ALLOW_DEMO_OPS_TOKEN=true`，否则 ops-service 会进入 locked mode 并返回 503：

```env
OPS_TOKEN=dify_ops_demo_token
ALLOW_DEMO_OPS_TOKEN=true
```

如果 Space 是公开的，必须在 Space Settings → Secrets 中覆盖成你自己的固定值，并不要开启 `ALLOW_DEMO_OPS_TOKEN`：

```env
OPS_TOKEN=<fixed-random-token>
```

CLI 访问示例：

```bash
curl -H "X-Ops-Token: $OPS_TOKEN" \
  https://your-space.hf.space/_ops/health
```

`/_ops/` dashboard 支持 English / 中文切换，默认跟随浏览器语言，选择会保存在浏览器本地。Dashboard 使用 signed HttpOnly cookie，不会把完整 `OPS_TOKEN` 注入页面脚本。

浏览器临时访问可使用；成功后会跳转到无 query 的 `/_ops/`：

```text
https://your-space.hf.space/_ops/?token=<OPS_TOKEN>
```

只读接口包括：

```text
/_ops/health           综合健康、内部端口、API/Web 探针
/_ops/status           Supervisor XML-RPC 进程状态
/_ops/system           CPU、memory、disk、/data、uptime、process count
/_ops/persistence      持久化、插件包和 runtime state 摘要
/_ops/provider-models  模型/provider 绑定和 credential 配置安全摘要
/_ops/config           非敏感配置摘要与密钥存在性
/_ops/version          运行版本与 Space 元数据
/_ops/errors           按 service 分组的近期错误摘要
/_ops/logs             白名单服务日志 tail
/_ops/metrics          Prometheus-style text metrics
```

`/_admin/` 默认 `ADMIN_ENABLED=false`，因此返回 404。确需演示受控管理能力时，需要设置独立 `ADMIN_TOKEN`，再按需打开 `ADMIN_FILES_ENABLED` 或 `ADMIN_FILES_WRITE_ENABLED`。当前白名单 action 包括 restart service、reload nginx、run health checks、force postgres backup、ensure app API token、restore plugin installed package from cache，以及 dry-run-first provider model `read_timeout` patch；`/_admin/api/audit` 可读取最近的 admin 审计事件；`/_ops` 仍保持只读。`/_admin/` 登录页和管理页也支持 English / 中文切换，并会在浏览器本地保存选择。

Nginx access log 使用 JSON 格式写到 Nginx stdout；当前 `supervisord` 会把 Nginx stdout 收进 `/data/logs/nginx.log`，可通过 `/_ops/logs?service=nginx` 查看。字段包含 `time`、`request_id`、`remote_addr`、`method`、`uri`、`status`、`request_time`、`upstream_addr`、`upstream_status`、`upstream_response_time` 和 `host`，便于区分 Web/API/Plugin/Ops 的上游问题。

部署后 smoke：

```bash
OPS_TOKEN=your-configured-ops-token \
  scripts/hf-space-smoke.sh https://your-space.hf.space
```

提交前轻量检查：

```bash
scripts/static-check.sh
```

更完整的 endpoint 说明、502 排障流程、Plugin Daemon migration 说明和发布后验收步骤见 [运维与可观测 Runbook](./docs/ops-runbook.md)。

## 运行限制

- Hugging Face Docker Space 不支持 `docker compose`；本工程用单容器多进程方式替代。
- Space 对外只暴露一个应用端口；本工程使用 Nginx 对外监听 `7860`。
- Hugging Face 免费硬件会休眠；建议使用 CPU Upgrade + 持久化 Storage。
- Space 运行时出站网络通常只适合 HTTP/HTTPS 端口；如果要接企业模型网关，建议暴露 HTTPS/443。
- 构建阶段需要访问 GitHub、PyPI、npm/pnpm registry、APT 源和 Docker Hub。无外网环境需要提前做制品缓存。
- `scripts/static-check.sh` 只证明脚本/Python 语法和 whitespace；Docker image 可运行性需要 Docker build/run、Hugging Face build logs 或 live smoke 作为证据。

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
