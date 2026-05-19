我准备按“三层隔离”做，不把所有东西混进现有 `/_ops`。

**总体结构**

```text
/healthz              public health, 仍由 ops-service 提供
/_ops/*               只读诊断面，不做写操作
/_admin/*             受控管理面，默认关闭
/_admin/files/*       文件管理，归属 admin，不归属 ops
/_admin/terminal/*    Web terminal，默认关闭，最后做
```

核心原则：**OPS 只读，Admin 可写但必须白名单，File Manager 限根目录，WebSSH 默认关闭。**

**Phase 1：Admin Control Plane**

我会新建独立的 `docker/admin_service.py`，不把写操作塞进 `docker/ops_service.py`。原因是现在 `ops_service.py` 已经是稳定只读诊断面，继续保持边界更清楚。

新增能力：

```text
GET  /_admin/
GET  /_admin/api/status
GET  /_admin/api/actions
POST /_admin/api/actions/restart-service
POST /_admin/api/actions/reload-nginx
POST /_admin/api/actions/run-health-checks
```

第一批 action 我会控制得很保守：

- `restart-service`：只允许白名单 Supervisor service，例如 `dify-api`、`dify-worker`、`dify-beat`、`plugin-daemon`、`sandbox`、`dify-web`、`nginx`。
- `reload-nginx`：只做 reload，不改配置。
- `run-health-checks`：触发已有健康检查，本质仍是读。

我暂时不会先做 `run-dify-migration`、`clear-cache`、`SQL`、任意 command。Dify migration 的真实命令要先查上游 runtime，不能猜。

认证设计：

```bash
ADMIN_ENABLED=false
ADMIN_HOST=127.0.0.1
ADMIN_PORT=8082
ADMIN_TOKEN=
ADMIN_SESSION_TTL_SECONDS=3600
ADMIN_AUDIT_LOG=/data/logs/admin-audit.jsonl
```

行为：

- `ADMIN_ENABLED=false` 时，`/_admin/` 仍返回 `404`，保持当前 smoke 预期。
- 开启 admin 必须设置 `ADMIN_TOKEN`，空 token 不允许启动可用管理面。
- CLI 支持 `X-Admin-Token` / `Authorization: Bearer`。
- Browser UI 用 login 表单换 signed HttpOnly cookie，不长期用 `?token=`。
- 写操作要求 `POST` + CSRF header。
- 所有 action 写入 `/data/logs/admin-audit.jsonl`，但不记录 token、secret、文件内容。

**Phase 2：File Manager**

文件管理放在 `/_admin/files/*`，默认也关闭：

```bash
ADMIN_FILES_ENABLED=false
ADMIN_FILES_ROOT=/data
ADMIN_FILES_WRITE_ENABLED=false
ADMIN_FILES_MAX_UPLOAD_BYTES=10485760
```

第一版我建议先做只读 + 小范围写入：

```text
GET    /_admin/api/files/list?path=/
GET    /_admin/api/files/download?path=...
GET    /_admin/api/files/text?path=...
POST   /_admin/api/files/mkdir
PUT    /_admin/api/files/text
POST   /_admin/api/files/upload
PATCH  /_admin/api/files/rename
DELETE /_admin/api/files/delete
```

安全边界：

- 请求里的 path 全部当作相对路径处理，不接受任意绝对路径。
- 用 `Path(root, rel).resolve()` 后强制检查必须仍在 `ADMIN_FILES_ROOT` 内。
- symlink 如果跳出 root，直接拒绝。
- 默认 root 是 `/data`，不是 `/`。
- 默认禁止读取或编辑：
  - `/data/config/generated.env`
  - `*.pem`
  - `*.key`
  - `*secret*`
  - `*token*`
- 写操作独立受 `ADMIN_FILES_WRITE_ENABLED` 控制；不开启时只能浏览/下载。

我倾向自研最小 file manager，不先引入 File Browser。这个仓库体量小，自研更容易保证路径白名单和审计口径。

**Phase 3：WebSSH / Web Terminal**

这个最后做，而且作为 break-glass debug 工具，不作为默认管理入口。

配置：

```bash
WEBSSH_ENABLED=false
WEBSSH_HOST=127.0.0.1
WEBSSH_PORT=7681
WEBSSH_SHELL=/bin/bash
WEBSSH_MAX_CLIENTS=1
```

实现方向：

- 不开 `sshd`，不暴露 SSH 端口。
- 用 Web terminal，比如 `ttyd` 一类单 binary。
- 由 Supervisor 管理，但 disabled 时跑一个 404 placeholder，避免 Supervisor health 因 STOPPED/EXITED 变红。
- Nginx 对 `/_admin/terminal/` 保留 WebSocket `Upgrade` / `Connection` header。
- 通过 Nginx `auth_request` 或 admin signed cookie 校验后才代理到 terminal。
- 运行用户继续是当前 `USER user`，不提权、不 root。
- 记录 session open/close 审计。第一版不承诺命令级审计，因为完整 keystroke/command audit 会复杂很多。

**会改的文件**

主要改这些：

```text
docker/admin_service.py             新增 admin service
docker/webssh_entrypoint.sh          Phase 3 新增
docker/nginx.conf                    增加 /_admin 代理和 terminal WebSocket route
docker/supervisord.conf              增加 admin-service，Phase 3 增加 web-terminal
docker/dify.env.runtime              增加 ADMIN_* / ADMIN_FILES_* / WEBSSH_* env
Dockerfile                           copy 新文件，必要时安装 terminal binary
scripts/hf-space-smoke.sh            保持默认 admin-disabled；增加可选 admin-enabled smoke
docs/configuration.md                新 env 说明
docs/security.md                     Admin/File/WebSSH 风险边界
docs/ops-runbook.md                  使用方式和排障
docs/architecture.md                 更新路由和边界
```

如果改 `docker/`，我会先按仓库规则读取 `docker/AGENTS.md`。

**验证设计**

默认验证：

```bash
bash -n docker/entrypoint.sh docker/with-dify-env docker/with-plugin-env docker/with-sandbox-env docker/wait-for-core docker/healthcheck.sh scripts/build.sh scripts/run-demo.sh scripts/hf-space-smoke.sh
python3 -m py_compile docker/ops_service.py docker/admin_service.py
git diff --check
```

新增脚本级 smoke：

```bash
ADMIN_ENABLED=false scripts/hf-space-smoke.sh http://localhost:8080
ADMIN_ENABLED=true ADMIN_TOKEN=dify_admin_demo_token scripts/hf-space-smoke.sh http://localhost:8080
```

Docker 可用时再跑：

```bash
scripts/build.sh
scripts/run-demo.sh
OPS_TOKEN=dify_ops_demo_token scripts/hf-space-smoke.sh http://localhost:8080
```
