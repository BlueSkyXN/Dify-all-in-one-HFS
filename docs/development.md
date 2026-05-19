# Development Guide

本文档说明如何在本仓库做开发、修改和验证。

## 开发原则

- 优先复用官方 Dify 镜像资产，不复制或 fork 大量上游源码。
- 修改保持在 Dockerfile、runtime scripts、Nginx、Supervisor、ops/admin service 和 docs 范围内。
- 改配置前先确认对应服务是否真的读取该变量。
- 不把演示环境默认值误写成生产安全建议。
- 每次改 runtime 启动链路后必须做线上或本地 smoke。

## 主要改动区域

| 区域 | 文件 | 典型改动 |
| --- | --- | --- |
| 镜像构建 | `Dockerfile` | 版本升级、系统依赖、复制 runtime assets |
| 初始化 | `docker/entrypoint.sh` | `/data` 准备、secret 生成、DB 初始化、迁移 |
| 环境变量 | `docker/dify.env.runtime`, `docker/dify.env.demo` | 默认值、demo env-file |
| 进程编排 | `docker/supervisord.conf` | 新增/调整进程、启动顺序、日志路径 |
| 路由 | `docker/nginx.conf` | 路径代理、健康探针、access log |
| 运维服务 | `docker/ops_service.py`, `docker/admin_service.py` | `/_ops` endpoint、健康检查、日志白名单、`/_admin` 受控管理面 |
| 辅助脚本 | `docker/with-*`, `docker/wait-for-core`, `docker/healthcheck.sh` | 环境转换、依赖等待、Docker healthcheck |
| 本地/线上脚本 | `scripts/*.sh` | build/run/smoke |
| 文档 | `README*.md`, `docs/*.md` | 用户说明和运维 runbook |

## 本地静态检查

推荐直接运行聚合脚本：

```bash
scripts/static-check.sh
```

它会执行下面这些轻量 gate。

`git diff --check` 不会检查未跟踪的新文件；`scripts/static-check.sh` 会额外扫描 changed/untracked 文件的 trailing whitespace。

Shell 语法：

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
  scripts/hf-space-smoke.sh \
  scripts/static-check.sh
```

Python 语法：

```bash
python3 -m py_compile docker/ops_service.py docker/admin_service.py
```

Git whitespace：

```bash
git diff --check
```

## Nginx 配置检查

如果本机装了 Nginx，可以用临时替换方式验证语法。因为仓库配置引用容器内路径 `/etc/nginx/mime.types` 和 `/data/...`，本机直接 `nginx -t -c docker/nginx.conf` 可能失败。

推荐做法是在临时文件中替换 mime path 和 `/data` 路径，再执行 `nginx -t`。不要把临时替换写回仓库。

## 本地 Docker 验证

构建：

```bash
scripts/build.sh
```

运行：

```bash
scripts/run-demo.sh
```

Smoke：

```bash
OPS_TOKEN=dify_ops_demo_token \
  scripts/hf-space-smoke.sh http://localhost:8080
```

查看 supervisor：

```bash
docker exec -it dify-aio-hf-demo \
  supervisorctl -c /etc/supervisor/conf.d/supervisord.conf status
```

查看日志：

```bash
docker logs -f dify-aio-hf-demo
```

## Hugging Face 验证

推送到 Hugging Face Space remote 后：

```bash
git remote -v
git push hf main
```

不要假设 `origin` 一定是 Hugging Face Space。当前本机 checkout 常见为 `hf` 指向 Hugging Face Space、`origin` 指向 GitHub mirror；如果你的 remote 名称不同，使用实际指向 `https://huggingface.co/spaces/BlueSkyXN/dify-all-in-one` 的 remote。

轮询：

```bash
hf spaces info BlueSkyXN/dify-all-in-one
```

确认：

```text
runtime.stage = RUNNING
runtime.raw.sha = <expected commit sha>
```

线上 smoke：

```bash
OPS_TOKEN=dify_ops_demo_token \
  scripts/hf-space-smoke.sh https://blueskyxn-dify-all-in-one.hf.space
```

错误摘要：

```bash
curl -H "X-Ops-Token: dify_ops_demo_token" \
  https://blueskyxn-dify-all-in-one.hf.space/_ops/errors
```

## 修改 Plugin Daemon 相关逻辑

必须保留 migration：

```bash
/opt/dify/plugin-daemon/commandline migrate && exec /opt/dify/plugin-daemon/main
```

验证点：

- build 日志中 `/opt/dify/plugin-daemon/commandline` 可执行检查通过。
- `plugin-daemon.log` 出现 `database migration completed successfully`。
- `/_ops/errors` 不出现 `install_tasks` 缺表错误。

## 修改 Nginx 路由

每次修改 `docker/nginx.conf` 后检查：

- `/nginx-health` 是否返回 `ok`。
- `/healthz` 是否代理到 ops-service。
- `/console/api/setup` 和 `/console/api/init` 是否为 200。
- `/apps` 是否移除了上游 `X-Frame-Options`，并保留允许 Hugging Face iframe 的 `Content-Security-Policy frame-ancestors`。
- `/socket.io/` 是否保留 Upgrade / Connection header。
- `/e/` 是否保留 `Dify-Hook-Url`。
- `/` 是否仍代理 Dify Web。

## 修改 ops-service

修改 `docker/ops_service.py` 后检查：

```bash
python3 -m py_compile docker/ops_service.py
```

线上或本地验证：

```bash
curl -H "X-Ops-Token: $OPS_TOKEN" <base>/_ops/health
curl -H "X-Ops-Token: $OPS_TOKEN" <base>/_ops/status
curl -H "X-Ops-Token: $OPS_TOKEN" <base>/_ops/system
curl -H "X-Ops-Token: $OPS_TOKEN" <base>/_ops/config
curl -H "X-Ops-Token: $OPS_TOKEN" <base>/_ops/errors
curl -H "X-Ops-Token: $OPS_TOKEN" <base>/_ops/metrics
curl -H "X-Ops-Token: $OPS_TOKEN" "<base>/_ops/logs?service=dify-api&lines=80"
```

安全要求：

- 不返回 secret 原文。
- 日志 service 必须白名单。
- `OPS_LOG_SERVICES_JSON` 只接受相对日志文件名，不允许绝对路径或 `..`。
- `OPS_EXTRA_COMMAND_CHECKS_JSON` 只配置只读命令；不要把写操作、迁移、清理数据放进健康检查。
- 只读接口不要执行破坏性命令。
- `ops-service` 本体不要依赖可写 `/data`；自身日志走 stdout/stderr，`/_ops/logs` 只读读取 `OPS_LOG_DIR`。
- query token 不应进入 ops-service 自身日志。

## 修改 admin-service

修改 `docker/admin_service.py` 后检查：

```bash
python3 -m py_compile docker/admin_service.py
```

本地或线上验证默认关闭状态：

```bash
curl -i <base>/_admin/
```

开启 admin 后验证：

```bash
curl -H "X-Admin-Token: $ADMIN_TOKEN" <base>/_admin/api/status
curl -H "X-Admin-Token: $ADMIN_TOKEN" <base>/_admin/api/actions
```

安全要求：

- `ADMIN_ENABLED=false` 时 `/_admin/` 必须返回 404。
- `ADMIN_ENABLED=true` 时必须设置 `ADMIN_TOKEN`。
- 不复用 `OPS_TOKEN`。
- action 必须是白名单，不允许请求传入任意 shell command。
- 写 action 必须有 CSRF header，重启和 reload 必须要求 `confirm=true`。
- file manager path 必须限制在 `ADMIN_FILES_ROOT` 内。
- 不读取或写入 generated secret、pem/key、secret/token 类路径。
- 删除只支持文件或空目录，不做递归删除。

## 修改配置变量

增加变量时需要同步：

1. `docker/dify.env.runtime`
2. `docker/dify.env.demo`，如果本地 demo 需要暴露
3. 对应 wrapper，如 `with-plugin-env` 或 `with-sandbox-env`
4. [Configuration Reference](./configuration.md)
5. smoke 或 ops-service 检查，如果变量影响健康状态

## 提交前检查清单

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
  scripts/hf-space-smoke.sh \
  scripts/static-check.sh
python3 -m py_compile docker/ops_service.py
python3 -m py_compile docker/admin_service.py
git diff --check
```

如果本机有 Docker：

```bash
scripts/build.sh
scripts/run-demo.sh
OPS_TOKEN=dify_ops_demo_token scripts/hf-space-smoke.sh http://localhost:8080
```

如果部署到 Hugging Face：

```bash
OPS_TOKEN=dify_ops_demo_token \
  scripts/hf-space-smoke.sh https://blueskyxn-dify-all-in-one.hf.space
```

## 当前已知限制

- 本仓库没有单元测试框架，主要依赖 shell/Python 静态检查和 Docker/HF smoke。
- 本地没有 Docker daemon 时，无法完整验证镜像构建，只能依赖 HF build。
- `sandbox`、`dify-web`、`ops-service`、`admin-service` 和 `web-terminal` 直接输出到容器 stdout/stderr，`/_ops/logs` 不暴露它们的专用文件。
- Nginx port/body size 变量目前不是动态模板。
