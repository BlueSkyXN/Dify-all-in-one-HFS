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
hf      https://huggingface.co/spaces/BlueSkyXN/dify-all-in-one
origin  https://github.com/BlueSkyXN/Dify-all-in-one-HFS.git
```

只有推送到指向 `https://huggingface.co/spaces/BlueSkyXN/dify-all-in-one` 的 remote 才会触发 Space Docker build。以上布局中应使用：

```bash
git push hf main
```

如果你的 remote 名称不同，使用实际指向 Hugging Face Space 的 remote。推送 GitHub remote 不会直接触发 Hugging Face Space rebuild。

## 查看 build / runtime

查看 Space 状态：

```bash
hf spaces info BlueSkyXN/dify-all-in-one
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
hf spaces logs BlueSkyXN/dify-all-in-one --build -n 220
```

查看 app logs：

```bash
hf spaces logs BlueSkyXN/dify-all-in-one -n 220
```

注意：刚推送后，顶层 `sha` 可能已经是新提交，但 `runtime.raw.sha` 仍是旧提交。只有 `runtime.stage=RUNNING` 且 `runtime.raw.sha` 等于目标提交，才代表新镜像已接管流量。

## 发布后 smoke

```bash
OPS_TOKEN=your-configured-ops-token \
  scripts/hf-space-smoke.sh https://blueskyxn-dify-all-in-one.hf.space
```

`dify_ops_demo_token` 只是未覆盖 `OPS_TOKEN` 时的镜像默认值。线上 Space 通常会在 Secrets 中覆盖它；发布验收必须使用 Space 当前配置的 token，否则 `/_ops/*` 会返回 401。

脚本检查：

```text
web-root
space-frame-headers
nginx-health
ops-healthz
admin-disabled
webssh-disabled
setup-api
init-api
ops-health
ops-system
ops-metrics
ops-errors
```

如果目标实例已显式开启 admin，可额外设置 `SMOKE_ADMIN_ENABLED=true` 和 `ADMIN_TOKEN=<admin-token>`，脚本会检查 `/_admin/api/status` 与 `/_admin/api/actions`。如果也开启 Web terminal，再加 `SMOKE_WEBSSH_ENABLED=true` 检查 `/_admin/terminal/`。默认不会触发 admin action；只有 `SMOKE_ADMIN_ACTIONS=true` 时才会调用 `run-health-checks`。

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
scripts/hf-space-smoke.sh https://blueskyxn-dify-all-in-one.hf.space
```

## 手工验证

基础健康：

```bash
curl https://blueskyxn-dify-all-in-one.hf.space/nginx-health
curl https://blueskyxn-dify-all-in-one.hf.space/healthz
curl -I https://blueskyxn-dify-all-in-one.hf.space/apps
```

`/apps` 响应不应带 `X-Frame-Options`，并应带允许 `https://huggingface.co` 的 `Content-Security-Policy: frame-ancestors ...`，否则 Hugging Face Space 页面 iframe 可能无法嵌入。

只读运维：

```bash
curl -H "X-Ops-Token: $OPS_TOKEN" \
  https://blueskyxn-dify-all-in-one.hf.space/_ops/health

curl -H "X-Ops-Token: $OPS_TOKEN" \
  https://blueskyxn-dify-all-in-one.hf.space/_ops/errors
```

浏览器：

```text
https://blueskyxn-dify-all-in-one.hf.space/
```

未初始化实例会跳转到 `/install` 并显示管理员账户设置页。

## 本地构建

要求本机有 Docker daemon。

```bash
scripts/build.sh
```

等价于：

```bash
docker build -t dify-all-in-one-hf-space:1.14.1 .
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
curl https://blueskyxn-dify-all-in-one.hf.space/nginx-health
curl https://blueskyxn-dify-all-in-one.hf.space/healthz
curl -H "X-Ops-Token: $OPS_TOKEN" \
  https://blueskyxn-dify-all-in-one.hf.space/_ops/health
```

完整流程见 [Operations Runbook](./ops-runbook.md)。

### build 通过但 runtime 仍是旧 SHA

等待 `runtime.raw.sha` 切换到目标提交。Hugging Face 有时会先更新仓库 `sha`，再切换 runtime。

### App logs 没有输出

先确认 stage：

```bash
hf spaces info BlueSkyXN/dify-all-in-one
```

如果仍在 build，查看 build logs：

```bash
hf spaces logs BlueSkyXN/dify-all-in-one --build -n 220
```

### 初始化后账号丢失

没有挂载 `/persist`，或 `PERSIST_MODE=legacy` 且 `/data` 没有保留。挂载 Storage Bucket 到 `/persist` 后重新初始化。
