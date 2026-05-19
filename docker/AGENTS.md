# docker/ navigation card

本目录是容器 runtime 合同：entrypoint、env、Supervisor、Nginx、ops/admin 服务、web terminal placeholder、PostgreSQL backup loop 和 healthcheck。改任何 `docker/` 文件前读本卡；重点看 `entrypoint.sh`、`dify.env.*`、`supervisord.conf`、`nginx.conf`、`ops_service.py`、`admin_service.py`、`webssh_entrypoint.sh`、`postgres-backup-loop`、`with-*`。

## 高风险

- 小改动会导致 HF readiness 失败、iframe header 回归或外部 502。
- `entrypoint.sh` 管 `/data`、generated secrets、Redis/Sandbox、PostgreSQL/pgvector 和 Dify migration。
- `nginx.conf` 是 `7860` 唯一公网入口；`ops_service.py` 只读，`admin_service.py` 承载默认关闭的 `/_admin` 管理面。

## 修改前

- 读目标文件和 `docs/development.md` 对应段落。
- Env 变更追踪 runtime/demo env、wrappers、entrypoint、Supervisor、ops/admin、`docs/configuration.md`。
- Route 变更保护 upstream、headers、smoke、WebSocket、`Dify-Hook-Url`。
- Admin/terminal 变更保护 `ADMIN_TOKEN`、CSRF/confirm、审计日志、file root 限制和 `/_admin_auth_terminal`。
- Persistence/PostgreSQL 变更覆盖 `/data`、generated env、`/data/run/postgresql`、pgvector、backup/fallback。

## 不变量

- runtime rootless；可写状态只在 `/data` 或明确的 persistence mount。
- Docker/HF env 优先于 defaults 和 generated secrets；secrets 不原文返回。
- PostgreSQL identifier 先校验再拼 SQL。
- Plugin Daemon migration 后再启动 `main`。
- `SANDBOX_ENABLE_NETWORK=false` 是默认值；改变时同步 security docs。
- `/_admin` 默认 disabled；写 action 只能留在 admin 白名单，不能进入 `/_ops`。
- Web terminal 默认 placeholder；没有 `ttyd` 时 `WEBSSH_ENABLED=true` 也只能返回 503。
- Nginx 保留 `listen 7860`、`/nginx-health`、`/healthz`、`/_ops/`、`/_admin/`、`/_admin/terminal/`、`/socket.io/`、`/e/`。
- `/_ops/logs` 只读 service 白名单；`ops-service` 保持只读。

## 不要做

- 不要在 `/_ops` 暴露 raw secrets、任意文件、shell command、SQL、restart 或 config write。
- 不要把 PostgreSQL、Redis、Sandbox、Plugin Daemon、ops-service、admin-service 或 web-terminal 绑到公网。
- 不要移除 pgvector 初始化或 Plugin Daemon migration，除非同步替换设计和文档。

## 验证

```bash
bash -n docker/entrypoint.sh docker/with-dify-env docker/with-plugin-env docker/with-sandbox-env docker/wait-for-core docker/healthcheck.sh docker/postgres-backup-loop docker/webssh_entrypoint.sh
python3 -m py_compile docker/ops_service.py docker/admin_service.py
git diff --check -- docker
```
