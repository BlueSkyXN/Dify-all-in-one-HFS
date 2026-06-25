# docker/ navigation card

本目录是容器 runtime 合同：entrypoint、env、Supervisor、Nginx、ops/admin 服务、PostgreSQL backup loop 和 healthcheck。改任何 `docker/` 文件前读本卡；重点看 `entrypoint.sh`、`dify.env.*`、`supervisord.conf`、`nginx.conf`、`ops_service.py`、`admin_service.py`、`postgres-backup-loop`、`with-*`。

## 高风险

- 小改动会导致 HF readiness 失败、iframe header 回归或外部 502。
- `entrypoint.sh` 管 `/data`、generated secrets、Redis/Sandbox、PostgreSQL/pgvector 和 Dify migration。
- `nginx.conf` 是 `7860` 唯一公网入口；`ops_service.py` 只读，`admin_service.py` 承载默认关闭的 `/_admin` 管理面。

## 修改前

- 读目标文件和 `docs/development.md` 对应段落。
- Env 变更追踪 runtime/demo env、wrappers、entrypoint、Supervisor、ops/admin、`docs/configuration.md`。
- Route 变更保护 upstream、headers、smoke、WebSocket、`Dify-Hook-Url`。
- Admin 变更保护 `ADMIN_TOKEN`、CSRF/confirm、审计日志和 file root 限制。
- Ops/admin dashboard 文案或 UI 结构变更必须同步 English / 中文文案，并保留浏览器语言检测与 `localStorage` 选择逻辑。
- Persistence/PostgreSQL 变更覆盖 `/data`、generated env、`/data/run/postgresql`、pgvector、backup/fallback。

## 不变量

- runtime rootless；可写状态只在 `/data` 或明确的 persistence mount。
- Docker/HF env 优先于 defaults 和 generated secrets；secrets 不原文返回。
- `OPS_TOKEN=dify_ops_demo_token` 默认 locked；本地 demo 需要显式 `ALLOW_DEMO_OPS_TOKEN=true`。
- `/_ops/` dashboard 不能内联完整 `OPS_TOKEN`，query token 只能作为临时 cookie migration 入口。
- `HF_HOME` / `HF_HUB_CACHE` 默认在 `${RUNTIME_ROOT}/hf-cache`，属于 runtime cache，不是 bucket-lite 核心持久状态。
- PostgreSQL identifier 先校验再拼 SQL。
- Plugin Daemon migration 后再启动 `main`。
- `SANDBOX_ENABLE_NETWORK=false` 是默认值；改变时同步 security docs。
- `/_admin` 默认 disabled；写 action 只能留在 admin 白名单，不能进入 `/_ops`。
- admin header token auth 跳过 CSRF；browser cookie session 写操作必须校验 CSRF。登录失败应写 audit 并受内存级限速保护。
- admin file manager rename/delete 必须继续受 `ADMIN_FILES_DESTRUCTIVE_ENABLED` 单独 gate。
- Nginx 保留 `listen 7860`、`/nginx-health`、`/healthz`、`/_ops/`、`/_admin/`、`/socket.io/`、`/e/`。
- `/_ops/logs` 只读 service 白名单；`ops-service` 保持只读。

## 不要做

- 不要在 `/_ops` 暴露 raw secrets、任意文件、shell command、SQL、restart 或 config write。
- 不要把 PostgreSQL、Redis、Sandbox、Plugin Daemon、ops-service、admin-service 绑到公网。
- 不要移除 pgvector 初始化或 Plugin Daemon migration，除非同步替换设计和文档。

## 验证

```bash
bash -n docker/entrypoint.sh docker/with-dify-env docker/with-plugin-env docker/with-sandbox-env docker/run-dify-agent docker/run-shellctl docker/wait-for-core docker/healthcheck.sh docker/postgres-backup-loop
python3 -m py_compile docker/ops_service.py docker/admin_service.py
git diff --check -- docker
```
