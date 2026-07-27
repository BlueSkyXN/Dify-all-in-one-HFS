# Project Overview

`dify-all-in-one` 是面向 Hugging Face Docker Space 的 Dify 单容器 Demo。它由 Supervisor 管理 Dify Web、API、Worker、Beat、Plugin Daemon、Sandbox、PostgreSQL、Redis、Nginx、只读 `ops-service` 和默认关闭的 `admin-service`，用于企业内训、课程演示、PoC 与快速功能验证。

## 目标和非目标

目标：单公开端口 `7860`、Dify 多服务编排、bucket-lite 状态边界、明确运行 provenance、只读 diagnostics 与受控 admin 边界。

非目标：生产 HA、Dify 源码 fork、托管大模型、把 `OPS_TOKEN` 变成生产级鉴权，或把 Space 当作完整产品代码仓。

## HFS v2 Delivery

本仓是 Pattern A / `port`，根目录同时是 GitHub wrapper 和 Space root。它已采用 artifact 车道：

- `BlueSkyXN/dify` producer 构建同源 Dify runtime bundle，并在 immutable GitHub Release 保存历史 archive；
- 本仓的 image 仅安装基础设施和 runtime glue；
- Space bootstrap 只读取一个 `hfs-dist/dify-all-in-one/<edge|release>/manifest.json`，下载 manifest 指定的唯一 archive，验证 SHA-256 与 runtime lock 后原子安装；
- API、Web、Agent、Plugin Daemon 与 Sandbox 必须在 `runtime-lock.json` 中有 provenance；API/Web/Agent 绑定同一个 fork commit；
- archive 或 manifest 任一错误均停止，不扫描 bucket、不回退 image assembly 或 direct URL/PATH/S3；
- PostgreSQL/Redis/插件/上传/生成配置继续属于 `/data`/`/persist`，不与 artifact 下载面混用。

目录责任：

```text
Dockerfile                         base infrastructure + artifact consumer
hfs-dev.toml                       minimal HFS v2 semantic registry
docker/dify-artifact-bootstrap     manifest-first bootstrap
docker/dify_artifact_contract.py   manifest/lock/archive verifier
docker/entrypoint.sh               Dify persistence, migration and Supervisor lifecycle
scripts/package-dify-runtime-artifact.py
                                   producer-side local packaging contract
scripts/prepare-dify-artifact-manifest.py
                                   immutable archive -> slot manifest helper
scripts/validate-hfs-contract.sh   local artifact contract gate
.github/workflows/publish-dify-runtime-artifact.yml
                                   approved manual manifest-last publisher
docs/                              operations, configuration and release evidence
```

## Runtime and persistence

Nginx remains the only public listener at `7860`; internal service ports and routes are unchanged. `/data` remains the application path. When a writable `/persist` mount is present, bucket-lite maps PostgreSQL, Dify files, generated config and Plugin assets there while logs/run/cache default to `/tmp/dify-aio`.

For a release/candidate artifact deployment, use a dedicated state mount, `PERSIST_MODE=bucket`, and `POSTGRES_BUCKET_FAILURE_MODE=exit`. Validate a fresh Dify bootstrap, state restart, dump backup and isolated restore before any production pointer change. Existing `fallback-to-runtime` remains a documented demo compatibility mode rather than a release success path.

## Operational endpoints

```text
/nginx-health      public Nginx liveness
/healthz           aggregate health
/_ops/             token-protected read-only diagnostics
/_admin/           independent, default-off controlled admin surface
```

Detailed architecture is in [Architecture](./architecture.md); delivery, settings, owner gates and limits are in [HFS v2 Alignment](./hfs-alignment.md), [Configuration](./configuration.md), and [Release Checklist](./release-checklist.md).