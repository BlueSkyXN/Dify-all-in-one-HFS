# Deployment Guide

本文档说明如何部署到 Hugging Face Docker Space、如何本地构建运行，以及如何确认发布结果。

## Hugging Face Space 部署

1. 创建 Hugging Face Space。
2. SDK 选择 `Docker`。
3. 将仓库根目录内容推送到 Space 仓库。
4. 确认 `README.md` 顶部包含：

```yaml
sdk: docker
app_port: 7860
```

5. 建议启用：

```text
Hardware: CPU Upgrade 或更高
Storage Bucket: mount 到 /persist
Visibility: Private 或 Protected
```

6. 建议设置 Variables / Secrets，详见 [Configuration Reference](./configuration.md)。

## 确认部署 remote 并推送

推送前先确认 remote，不要假设 `origin` 一定是 Hugging Face Space：

```bash
git remote -v
```

当前本机 checkout 的常见布局是：

```text
hf      https://huggingface.co/spaces/<space-id>
origin  https://github.com/BlueSkyXN/Dify-all-in-one-HFS.git
```

只有推送到指向 `https://huggingface.co/spaces/<space-id>` 的 remote 才会触发 Space Docker build。以上布局中应使用：

```bash
git push hf main
```

如果你的 remote 名称不同，使用实际指向 Hugging Face Space 的 remote。推送 GitHub remote 不会直接触发 Hugging Face Space rebuild。

## 查看 build / runtime

查看 Space 状态：

```bash
hf spaces info <space-id>
```

关键字段：

```text
sha
runtime.stage
runtime.raw.sha
runtime.raw.hardware.current
runtime.raw.domains[].stage
```

查看 build logs：

```bash
hf spaces logs <space-id> --build -n 220
```

查看 app logs：

```bash
hf spaces logs <space-id> -n 220
```

注意：刚推送后，顶层 `sha` 可能已经是新提交，但 `runtime.raw.sha` 仍是旧提交。只有 `runtime.stage=RUNNING` 且 `runtime.raw.sha` 等于目标提交，才代表新镜像已接管流量。

## 发布后 smoke

```bash
OPS_TOKEN=your-configured-ops-token \
  scripts/hf-space-smoke.sh https://your-space.hf.space
```

`dify_ops_demo_token` 只是本地 demo 默认值。未显式设置 `ALLOW_DEMO_OPS_TOKEN=true` 时，默认 token 会让 ops-service 进入 locked mode，`/healthz` 与 `/_ops/*` 返回 503。线上 Space 必须在 Secrets 中覆盖强随机 `OPS_TOKEN`；发布验收必须使用 Space 当前配置的 token，否则 `/_ops/*` 会返回 401。

脚本检查：

```text
web-root
space-frame-headers
nginx-health
ops-healthz
admin-disabled
setup-api
init-api
openapi-health    # 仅 SMOKE_OPENAPI_ENABLED=true 时
openapi-version   # 仅 SMOKE_OPENAPI_ENABLED=true 时
ops-health
ops-system
ops-persistence
ops-metrics
ops-errors
```

`ops-persistence` 不只检查 HTTP 200，还会断言 `/_ops/persistence` 的 `ok=true`，并要求 `missing_package_files`、`missing_installed_files`、`missing_runtime_states` 和 `plugin_storage_layout_issues` 为空；bucket-lite 下还会确认 Plugin Daemon 看到的 storage root 是真实 `/persist/...` 目录而不是 `/data/plugin_daemon/*` symlink root。

如果目标实例已显式开启 admin，可设置 `SMOKE_ADMIN_ENABLED=true`。未提供 `ADMIN_TOKEN` 时，脚本只验证 `/_admin/` 返回 200、`/_admin/api/status` 未鉴权返回 401，用于 protected NEXT Space 的无 secret 远程边界检查。提供 `ADMIN_TOKEN=<admin-token>` 后，脚本会继续检查 `/_admin/api/status`、`/_admin/api/actions` 与 `/_admin/api/audit`。默认不会触发 admin action；只有 `SMOKE_ADMIN_ACTIONS=true` 时才会调用 `run-health-checks`，且此时必须提供 `ADMIN_TOKEN`。Web terminal / WebSSH 已移除，不再属于 smoke 范围。

如果目标实例是 NEXT Space 且已设置 `OPENAPI_ENABLED=true`、`ENABLE_OAUTH_BEARER=true`，可额外设置 `SMOKE_OPENAPI_ENABLED=true`，脚本会检查 `/openapi/v1/_health` 和 `/openapi/v1/_version`。这只验证 OpenAPI route 和服务端版本探针；`difyctl auth login` 仍需要人工在 `/device` 页面批准，属于单独的半自动验收。

默认重试：

```env
SMOKE_RETRIES=30
SMOKE_DELAY=5
```

可以调整：

```bash
OPS_TOKEN=your-configured-ops-token \
SMOKE_RETRIES=60 \
SMOKE_DELAY=5 \
scripts/hf-space-smoke.sh https://your-space.hf.space
```

## 手工验证

基础健康：

```bash
curl https://your-space.hf.space/nginx-health
curl https://your-space.hf.space/healthz
curl -I https://your-space.hf.space/apps
```

`/apps` 响应不应带 `X-Frame-Options`，并应带允许 `https://huggingface.co` 的 `Content-Security-Policy: frame-ancestors ...`，否则 Hugging Face Space 页面 iframe 可能无法嵌入。

只读运维：

```bash
curl -H "X-Ops-Token: $OPS_TOKEN" \
  https://your-space.hf.space/_ops/health

curl -H "X-Ops-Token: $OPS_TOKEN" \
  https://your-space.hf.space/_ops/errors
```

NEXT Space 如果开启 `DIFY_AGENT_ENABLED=true`，还要检查 `/_ops/health` 里的 `agent_backend` 字段；如果同时开启 `AGENT_SHELL_ENABLED=true`，还要检查 `shellctl.status=ok` 且 `shellctl.enabled=true`。这些只说明内部 backend 和 shell layer 进程可达；完整 Agent v2 / Skills 验收仍需要在 Console 里跑真实 Agent App 或 workflow Agent node。

浏览器：

```text
https://your-space.hf.space/
```

未初始化实例会跳转到 `/install` 并显示管理员账户设置页。

## 本地构建

要求本机有 Docker daemon。

```bash
scripts/build.sh
```

等价于：

```bash
docker build -t dify-all-in-one-hf-space:latest .
```

自定义 tag：

```bash
scripts/build.sh my-dify-aio:dev
```

## 本地运行

```bash
scripts/run-demo.sh
```

默认：

```text
container name: dify-aio-hf-demo
host port: 8080
container port: 7860
volume: dify-hf-demo-persist:/persist
PUBLIC_URL=http://localhost:8080
env-file: docker/dify.env.demo
```

打开：

```text
http://localhost:8080
```

查看日志：

```bash
docker logs -f dify-aio-hf-demo
```

查看 supervisor：

```bash
docker exec -it dify-aio-hf-demo supervisorctl -c /etc/supervisor/conf.d/supervisord.conf status
```

停止并删除：

```bash
docker rm -f dify-aio-hf-demo
```

删除本地数据 volume：

```bash
docker volume rm dify-hf-demo-persist
```

## 常见部署问题

### Space 502

先看：

```bash
curl https://your-space.hf.space/nginx-health
curl https://your-space.hf.space/healthz
curl -H "X-Ops-Token: $OPS_TOKEN" \
  https://your-space.hf.space/_ops/health
```

完整流程见 [Operations Runbook](./ops-runbook.md)。

### build 通过但 runtime 仍是旧 SHA

等待 `runtime.raw.sha` 切换到目标提交。Hugging Face 有时会先更新仓库 `sha`，再切换 runtime。

### App logs 没有输出

先确认 stage：

```bash
hf spaces info <space-id>
```

如果仍在 build，查看 build logs：

```bash
hf spaces logs <space-id> --build -n 220
```

### 初始化后账号丢失

没有挂载 `/persist`，或 `PERSIST_MODE=legacy` 且 `/data` 没有保留。挂载 Storage Bucket 到 `/persist` 后重新初始化。
