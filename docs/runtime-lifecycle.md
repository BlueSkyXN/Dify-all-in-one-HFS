# Runtime Lifecycle

本文档以 artifact 车道描述容器构建、bootstrap、初始化和长期进程阶段。Dify 是演示/PoC all-in-one，不是生产部署方案。

## Image Build

`Dockerfile` 只构建 wrapper 基础设施：Python/Debian、PostgreSQL 15 + pgvector、Redis、Nginx、Supervisor、Node、uv、diagnostic/admin services、runtime wrappers 与健康检查。它不 `FROM` 或 `COPY --from` Dify API/Web/Agent/Plugin/Sandbox 业务镜像，也不 clone Dify product source。

唯一与 Sandbox 有关的 image-built component 是 `docker/sandbox-artifact-launcher.c` 编译出的 root-owned setuid launcher。它在运行时只 exec `/opt/dify/runtime/opt/dify/sandbox/main`，使非 root artifact bootstrap 无需、也无法提升权限，同时保持现有 HFS rootless Sandbox privilege boundary。

## Manifest-first Bootstrap

容器入口仍是：

```text
/usr/bin/tini -- /usr/local/bin/dify-all-in-one-entrypoint
```

`entrypoint.sh` 的首个业务动作是 `/usr/local/bin/dify-artifact-bootstrap`。它要求：

```text
DIFY_ARTIFACT_MANIFEST_HF_URI
DIFY_ARTIFACT_BEARER_TOKEN
```

bootstrap 只接受如下 URI：

```text
hf://buckets/<namespace>/hfs-dist/dify-all-in-one/<edge|release>/manifest.json
```

它先验证 URI，再下载一次 schema v2 manifest；随后只下载 manifest 选择的 `dify-runtime-<40-char-commit>.tar.gz`。archive 必须匹配压缩与解包大小、SHA-256，并包含与 manifest hash 一致的 `runtime-lock.json`、API、Web、Agent、Plugin Daemon、Sandbox、`/conf` 和 `/dependencies` 所需路径。unsafe path、link escape、重复 member、缺组件、错误 source ref 或 component pin、错误 lock、解包失败、下载失败或缺凭据均非零退出；不会扫描 slot、读取 direct URL/PATH/S3、使用旧 OCI image 或继续启动旧的 `/app`。

验证成功后 payload 通过同目录 release target 和 symlink swap 原子安装到 `/opt/dify/runtime`。切换成功后只回收该 symlink 能证明由本合同创建的上一版 release target；不会跟随或删除任意外部 symlink，也不会触碰 `/data` 或 `/persist`。随后恢复上游期望的路径：

```text
/app                         -> /opt/dify/runtime/app
/opt/dify/plugin-daemon      -> /opt/dify/runtime/opt/dify/plugin-daemon
/conf                         <- /opt/dify/runtime/conf
/dependencies                 <- /opt/dify/runtime/dependencies
```

产品 payload 不进入 `/data`。`/opt/dify/runtime/MANIFEST_PROVENANCE.json` 是仅运行时 provenance 记录；`/_ops/version` 的 artifact provenance readback 和 Space runtime SHA 仍需在部署窗口验证。

## 初始化顺序

artifact 安装成功后，原有流程保持：

```text
prepare_dirs
artifact bootstrap
configure plugin storage root
write_generated_env
source runtime env
render Redis config
render Sandbox config
init local PostgreSQL or validate external PostgreSQL
start temporary Redis
run Dify API migration
stop temporary services
exec supervisord
```

`write_generated_env` 继续遵循 Space/Docker 显式值优先、持久化 `/data/config/generated.env` 次之、随机生成最后的顺序。生成值不可作为 artifact seed 或发布输入。

`PERSIST_MODE=auto` 仍在 `/persist` 已挂载且可写时启用 bucket-lite。release/candidate 运行建议 `PERSIST_MODE=bucket` 和 `POSTGRES_BUCKET_FAILURE_MODE=exit`；现有 `fallback-to-runtime` 仅保留兼容逻辑，不能作为持久化成功或恢复成功的证明。

## Supervisor 阶段

artifact 安装、Dify migration 和 Plugin Daemon migration 完成后，仍由：

```bash
/usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
```

长期进程和端口不变：PostgreSQL `127.0.0.1:5432`、Redis `127.0.0.1:6379`、Plugin Daemon `5002`、Sandbox `8194`、Dify API `5001`、Web `3000`、ops `8081`、admin `8082`、Nginx public `7860`。Nginx、`/_ops`、`/_admin`、WebSocket、Plugin endpoint 和 health route 的现有路由/鉴权边界不因 artifact delivery 改变。

Plugin Daemon 启动仍必须先执行：

```bash
/opt/dify/plugin-daemon/commandline migrate && exec /opt/dify/plugin-daemon/main
```

## Health and validation limits

Docker healthcheck 仍检查 API、ops health 与 Nginx。它只能在 bootstrap 已成功、长期进程已启动后成为可用信号。发布前还必须分别验证：runtime manifest/lock/archive negative path、PostgreSQL migration、Redis/Celery、Dify login/API、file storage、Plugin tool、Sandbox execution、restart persistence 和 isolated dump restore。

静态检查、Docker build、local smoke 和 live Space smoke 是不同层次的证据；本轮本地静态检查不宣称 artifact producer、Docker build、bucket download 或 live runtime 已通过。
